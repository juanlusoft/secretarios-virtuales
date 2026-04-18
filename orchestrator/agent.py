import asyncio
import logging
from pathlib import Path
from uuid import UUID

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from orchestrator.admin import AdminService
from orchestrator.parser import (
    CreateSecretaryCommand,
    DestroySecretaryCommand,
    ListSecretariesCommand,
    SendMessageCommand,
    parse_command,
)
from secretary.agent import SecretaryAgent
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class OrchestratorAgent(SecretaryAgent):
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
        dsn: str,
    ) -> None:
        super().__init__(
            employee_id=employee_id,
            employee_name=employee_name,
            allowed_chat_id=allowed_chat_id,
            db_pool=db_pool,
            chat=chat,
            embed=embed,
            whisper=whisper,
            documents_dir=documents_dir,
            fernet_key=fernet_key,
            redis_url=redis_url,
        )
        self._admin = AdminService(
            dsn=dsn,
            redis_url=redis_url,
            fernet_key=fernet_key,
        )
        self._dsn = dsn

    async def _handle_admin_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Try to handle as admin command. Returns True if handled."""
        msg = update.message.text or ""  # type: ignore[union-attr]
        command = parse_command(msg)

        if command is None:
            return False

        if isinstance(command, ListSecretariesCommand):
            secretaries = await self._admin.list_secretaries()
            if not secretaries:
                text = "No hay secretarios activos."
            else:
                lines = [
                    f"{'✅' if s['is_active'] else '❌'} {s['name']} — chat_id: {s['telegram_chat_id']}"
                    for s in secretaries
                ]
                text = "Secretarios:\n" + "\n".join(lines)
            await update.message.reply_text(text)  # type: ignore[union-attr]
            return True

        if isinstance(command, CreateSecretaryCommand):
            employee_id = await self._admin.create_secretary(
                name=command.name,
                telegram_token=command.telegram_token,
                telegram_chat_id=command.telegram_chat_id,
            )
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Secretario {command.name} creado (id: {employee_id}).\n"
                f"El supervisor lo arrancará en breve."
            )
            return True

        if isinstance(command, DestroySecretaryCommand):
            secretaries = await self._admin.list_secretaries()
            match = next(
                (s for s in secretaries if s["name"].lower() == command.name.lower()), None
            )
            if not match:
                await update.message.reply_text(f"❌ No encontré secretario con nombre {command.name}.")  # type: ignore[union-attr]
                return True
            await self._admin.destroy_secretary(UUID(str(match["id"])))
            await update.message.reply_text(f"🗑 Secretario {command.name} eliminado.")  # type: ignore[union-attr]
            return True

        if isinstance(command, SendMessageCommand):
            secretaries = await self._admin.list_secretaries()
            match = next(
                (s for s in secretaries if s["name"].lower() == command.name.lower()), None
            )
            if not match:
                await update.message.reply_text(f"❌ No encontré secretario con nombre {command.name}.")  # type: ignore[union-attr]
                return True
            await self._admin.send_message_to_secretary(
                employee_id=UUID(str(match["id"])),
                content=command.message,
            )
            await update.message.reply_text(f"✅ Mensaje enviado a {command.name}.")  # type: ignore[union-attr]
            return True

        return False

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        if await self._handle_admin_command(update, context):
            return
        await super()._handle_text(update, context)

    async def run(self, bot_token: str) -> None:  # type: ignore[override]
        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info("OrchestratorAgent starting (chat_id=%s)", self._allowed_chat_id)
        async with app:
            await app.updater.start_polling(drop_pending_updates=True)
            await app.start()
            await asyncio.Event().wait()
