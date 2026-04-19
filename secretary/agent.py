import asyncio
import json
import logging
from contextlib import suppress
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
from secretary.handlers.config_email import EmailConfigFlow
from secretary.handlers.document import handle_document
from secretary.handlers.email import handle_check_email
from secretary.handlers.onboarding import build_onboarding_handler
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
        self._config_email = EmailConfigFlow(employee_id, db_pool, self._store)
        self._email_configured: bool | None = None  # lazily checked, invalidated on save
        self._profile: dict | None = None  # lazily loaded from credentials table

    async def _is_authorized(self, update: Update) -> bool:
        return str(update.effective_chat.id) == self._allowed_chat_id  # type: ignore[union-attr]

    async def _get_email_client(self) -> EmailClient | None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            enc_imap = await repo.get_credential("email_imap")
            enc_smtp = await repo.get_credential("email_smtp")
        if not enc_imap or not enc_smtp:
            return None
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

    async def _check_email_configured(self) -> bool:
        if self._email_configured is None:
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                self._email_configured = await repo.get_credential("email_imap") is not None
        return self._email_configured

    async def _load_profile(self) -> dict | None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            raw = await repo.get_credential("profile")
        if raw is None:
            return None
        try:
            return json.loads(self._store.decrypt(raw))  # type: ignore[no-any-return]
        except Exception:
            return None

    async def _save_profile(self, profile: dict) -> None:
        encrypted = self._store.encrypt(json.dumps(profile))
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("profile", encrypted)

    async def _save_email_credentials(self, imap_json: str, smtp_json: str) -> None:
        enc_imap = self._store.encrypt(imap_json)
        enc_smtp = self._store.encrypt(smtp_json)
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("email_imap", enc_imap)
            await repo.save_credential("email_smtp", enc_smtp)
        self._email_configured = True

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        msg = (update.message.text or "").strip()  # type: ignore[union-attr]

        # Active config wizard intercepts all input
        if self._config_email.active:
            reply, saved = await self._config_email.handle(msg)
            if saved:
                self._email_configured = True
            await update.message.reply_text(reply, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        if msg.lower() in ("/ayuda", "/help", "/start help"):
            email_configured = await self._check_email_configured()
            email_line = "✅ `/email` — revisar bandeja de entrada" if email_configured else "⚙️ `/config_email` — conectar cuenta de email"
            text = (
                "🤖 *¿Qué puedo hacer por ti?*\n\n"
                "💬 *Conversación*\n"
                "  Escríbeme lo que necesites en lenguaje natural\n\n"
                "📧 *Email*\n"
                f"  {email_line}\n\n"
                "📄 *Documentos*\n"
                "  Adjunta un PDF o archivo de texto y pregúntame sobre su contenido\n\n"
                "🎙 *Voz*\n"
                "  Mándame un audio y te respondo\n\n"
                "🖼 *Imágenes*\n"
                "  Mándame una foto y te digo qué contiene\n\n"
                "⚙️ *Configuración*\n"
                "  `/config_email` — configurar o cambiar cuenta de email\n"
                "  `/start` — ver estado del perfil"
            )
            await update.message.reply_text(text, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        if msg.lower() in ("/config email", "/config_email"):
            reply = self._config_email.start()
            await update.message.reply_text(reply, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        if msg.lower().startswith("/email"):
            email_client = await self._get_email_client()
            if not email_client:
                await update.message.reply_text(  # type: ignore[union-attr]
                    "❌ Email no configurado. Usa */config_email* para activarlo.",
                    parse_mode="Markdown",
                )
                return
            try:
                async with self._pool.acquire() as conn:
                    repo = Repository(conn, self._employee_id)
                    memory = MemoryManager(repo=repo, embed_client=self._embed)
                    response = await asyncio.wait_for(
                        handle_check_email(
                            email_client=email_client,
                            chat=self._chat,
                            employee_name=self._employee_name,
                        ),
                        timeout=30.0,
                    )
                    await memory.save_turn(msg, response)
            except asyncio.TimeoutError:
                response = "⏱ El servidor de email tardó demasiado. Comprueba los datos con /config_email."
            except Exception as exc:
                response = f"❌ Error al conectar con el email: {exc}"
            await update.message.reply_text(response)  # type: ignore[union-attr]
            return

        email_configured = await self._check_email_configured()
        if self._profile is None:
            self._profile = await self._load_profile()
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(
                message=msg,
                employee_name=self._employee_name,
                memory=memory,
                chat=self._chat,
                email_configured=email_configured,
                profile=self._profile,
            )
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        voice = update.message.voice  # type: ignore[union-attr]
        if voice is None:
            return
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
        if doc is None:
            return
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        try:
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
        except Exception as exc:
            response = f"❌ No pude procesar el archivo: {exc}"
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        photo = update.message.photo[-1]  # type: ignore[union-attr]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        caption = update.message.caption  # type: ignore[union-attr]

        try:
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
        except Exception as exc:
            response = f"❌ No pude analizar la imagen: {exc}"
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _listen_redis(self, app: Application) -> None:  # type: ignore[type-arg]
        import json
        channel = f"secretary.{self._employee_id}"
        retry_delay = 1.0
        while True:
            try:
                redis = aioredis.from_url(self._redis_url)  # type: ignore[no-untyped-call]
                pubsub = redis.pubsub()
                await pubsub.subscribe(channel)
                logger.info("Redis listener subscribed to channel %s", channel)
                retry_delay = 1.0  # reset back-off on successful connection
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    data = json.loads(message["data"])
                    if data.get("type") == "admin_message":
                        await app.bot.send_message(
                            chat_id=self._allowed_chat_id,
                            text=data["content"],
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Redis listener error on channel %s; retrying in %.1fs",
                    channel,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)

    async def _poll_email(self, app: Application, interval: int = 600) -> None:  # type: ignore[type-arg]
        await asyncio.sleep(interval)  # wait before first check
        while True:
            try:
                email_client = await self._get_email_client()
                if email_client:
                    messages = await asyncio.wait_for(
                        email_client.fetch_inbox(limit=20, since_days=1),
                        timeout=30.0,
                    )
                    # Load seen UIDs
                    async with self._pool.acquire() as conn:
                        repo = Repository(conn, self._employee_id)
                        raw = await repo.get_credential("email_seen_uids")
                    seen: set[str] = set(json.loads(self._store.decrypt(raw)) if raw else [])

                    new_messages = [m for m in messages if str(m.uid) not in seen]
                    if new_messages:
                        lines = []
                        for m in new_messages:
                            lines.append(f"📧 *{m.sender}*\n_{m.subject}_")
                            seen.add(str(m.uid))
                        text = f"📬 Tienes {len(new_messages)} email(s) nuevo(s):\n\n" + "\n\n".join(lines)
                        await app.bot.send_message(
                            chat_id=self._allowed_chat_id,
                            text=text,
                            parse_mode="Markdown",
                        )
                        # Save updated seen UIDs
                        encrypted = self._store.encrypt(json.dumps(list(seen)))
                        async with self._pool.acquire() as conn:
                            repo = Repository(conn, self._employee_id)
                            await repo.save_credential("email_seen_uids", encrypted)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Email poller error")
            await asyncio.sleep(interval)

    async def run(self, bot_token: str) -> None:
        app = Application.builder().token(bot_token).build()
        app.add_handler(build_onboarding_handler(self))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info(
            "Secretary %s starting (chat_id=%s)", self._employee_name, self._allowed_chat_id
        )
        async with app:
            if app.updater is None:
                raise RuntimeError("Telegram updater is not available")

            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            redis_task = asyncio.create_task(self._listen_redis(app))
            email_task = asyncio.create_task(self._poll_email(app, interval=600))
            try:
                await asyncio.Event().wait()
            finally:
                redis_task.cancel()
                email_task.cancel()
                with suppress(asyncio.CancelledError):
                    await redis_task
                with suppress(asyncio.CancelledError):
                    await email_task
