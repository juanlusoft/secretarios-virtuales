import logging
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers.audio import handle_audio
from secretary.handlers.document import handle_document
from secretary.handlers.email import handle_check_email
from secretary.handlers.photo import handle_photo
from secretary.handlers.text import handle_text
from secretary.memory import MemoryManager
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository
from shared.email.client import EmailClient
from shared.email.models import EmailConfig
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class SecretaryAgent:
    def __init__(
        self,
        employee_id: UUID,
        employee_name: str,
        allowed_chat_id: str,
        db_pool: DatabasePool,
        chat: ChatClient,
        embed: EmbeddingClient,
        whisper: WhisperClient,
        documents_dir: Path,
        fernet_key: bytes,
        redis_url: str,
    ) -> None:
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._allowed_chat_id = str(allowed_chat_id)
        self._pool = db_pool
        self._chat = chat
        self._embed = embed
        self._whisper = whisper
        self._documents_dir = documents_dir
        self._store = CredentialStore(fernet_key)
        self._redis_url = redis_url

    async def _is_authorized(self, update: Update) -> bool:
        return str(update.effective_chat.id) == self._allowed_chat_id  # type: ignore[union-attr]

    async def _get_email_client(self) -> EmailClient | None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            enc_imap = await repo.get_credential("email_imap")
            enc_smtp = await repo.get_credential("email_smtp")
        if not enc_imap or not enc_smtp:
            return None
        import json
        imap = json.loads(self._store.decrypt(enc_imap))
        smtp = json.loads(self._store.decrypt(enc_smtp))
        return EmailClient(
            EmailConfig(
                imap_host=imap["host"],
                imap_port=int(imap["port"]),
                smtp_host=smtp["host"],
                smtp_port=int(smtp["port"]),
                username=imap["username"],
                password=imap["password"],
            )
        )

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        msg = update.message.text or ""  # type: ignore[union-attr]

        if msg.lower().startswith("/email"):
            email_client = await self._get_email_client()
            if not email_client:
                await update.message.reply_text("❌ Email no configurado.")  # type: ignore[union-attr]
                return
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                memory = MemoryManager(repo=repo, embed_client=self._embed)
                response = await handle_check_email(
                    email_client=email_client,
                    chat=self._chat,
                    employee_name=self._employee_name,
                )
                await memory.save_turn(msg, response)
            await update.message.reply_text(response)  # type: ignore[union-attr]
            return

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(
                message=msg,
                employee_name=self._employee_name,
                memory=memory,
                chat=self._chat,
            )
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        voice = update.message.voice  # type: ignore[union-attr]
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            transcription, response = await handle_audio(
                audio_bytes=bytes(audio_bytes),
                filename="audio.ogg",
                employee_name=self._employee_name,
                whisper=self._whisper,
                memory=memory,
                chat=self._chat,
            )
            await memory.save_turn(transcription, response)

        await update.message.reply_text(  # type: ignore[union-attr]
            f"🎙 _{transcription}_\n\n{response}", parse_mode="Markdown"
        )

    async def _handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        doc = update.message.document  # type: ignore[union-attr]
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            response = await handle_document(
                file_bytes=bytes(file_bytes),
                filename=doc.file_name or "document",
                mime_type=doc.mime_type or "application/octet-stream",
                employee_id=self._employee_id,
                documents_dir=self._documents_dir,
                repo=repo,
                embed=self._embed,
            )
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        photo = update.message.photo[-1]  # type: ignore[union-attr]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        caption = update.message.caption  # type: ignore[union-attr]

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_photo(
                photo_bytes=bytes(photo_bytes),
                caption=caption,
                employee_name=self._employee_name,
                chat=self._chat,
                memory=memory,
            )
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _listen_redis(self, app: Application) -> None:  # type: ignore[type-arg]
        redis = await aioredis.from_url(self._redis_url)
        pubsub = redis.pubsub()
        channel = f"secretary.{self._employee_id}"
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            import json
            data = json.loads(message["data"])
            if data.get("type") == "admin_message":
                await app.bot.send_message(
                    chat_id=self._allowed_chat_id,
                    text=data["content"],
                )

    async def run(self, bot_token: str) -> None:
        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info(
            "Secretary %s starting (chat_id=%s)", self._employee_name, self._allowed_chat_id
        )
        await app.run_polling(drop_pending_updates=True)
