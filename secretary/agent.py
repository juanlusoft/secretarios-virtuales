import asyncio
import html
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
from secretary.handlers.config_calendar import CalendarConfigFlow
from secretary.handlers.config_email import EmailConfigFlow
from shared.calendar.client import CalendarClient, make_calendar_client
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
from datetime import datetime, timedelta

from shared.llm.chat import ToolCall
from shared.tools import TOOL_DEFINITIONS, ToolExecutor, is_destructive

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
        vision: ChatClient | None = None,
        executor: ToolExecutor | None = None,
        calendar_client: CalendarClient | None = None,
        google_client_id: str = "",
        google_client_secret: str = "",
    ) -> None:
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._allowed_chat_id = str(allowed_chat_id)
        self._allowed_chat_ids: frozenset[str] = frozenset(
            cid.strip() for cid in str(allowed_chat_id).split(",") if cid.strip()
        )
        self._pool = db_pool
        self._chat = chat
        self._vision = vision or chat  # fallback al modelo de texto si no hay visión
        self._embed = embed
        self._whisper = whisper
        self._documents_dir = documents_dir
        self._store = CredentialStore(fernet_key)
        self._redis_url = redis_url
        self._config_email = EmailConfigFlow(employee_id, db_pool, self._store)
        self._email_configured: bool | None = None  # lazily checked, invalidated on save
        self._profile: dict | None = None  # lazily loaded from credentials table
        self._executor = executor
        self._calendar = calendar_client
        self._config_calendar = CalendarConfigFlow(
            employee_id=employee_id,
            pool=db_pool,
            store=self._store,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
        )
        self._superuser_until: datetime | None = None
        self._pending_tool: ToolCall | None = None
        self._pending_messages: list[dict] | None = None
        self._pending_used_tools: list[str] | None = None
        self._pending_system: str | None = None
        self._pending_original_msg: str = ""

    async def _is_authorized(self, update: Update) -> bool:
        return str(update.effective_chat.id) in self._allowed_chat_ids  # type: ignore[union-attr]

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

    def _is_superuser(self) -> bool:
        if self._superuser_until is None:
            return False
        return datetime.now() < self._superuser_until

    def _reset_superuser_timer(self) -> None:
        if self._superuser_until is not None:
            self._superuser_until = datetime.now() + timedelta(minutes=30)

    async def _run_tool_loop(
        self,
        messages: list[dict],
        system: str,
        used_tools: list[str],
    ) -> str:
        for _ in range(10):
            text, tool_calls = await self._chat.complete_with_tools(
                messages, system, TOOL_DEFINITIONS
            )
            if not tool_calls:
                suffix = (
                    f"\n\n_Herramientas usadas: {', '.join(used_tools)}_"
                    if used_tools
                    else ""
                )
                return (text or "") + suffix

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                if is_destructive(tc.name, tc.args) and not self._is_superuser():
                    self._pending_tool = tc
                    self._pending_messages = messages
                    self._pending_used_tools = used_tools
                    self._pending_system = system
                    cmd_str = tc.args.get("command", json.dumps(tc.args))
                    return f"⚠️ Voy a ejecutar:\n`{cmd_str}`\n¿Confirmas? (sí/no)"

                result = await self._executor.run(tc.name, tc.args)  # type: ignore[union-attr]
                used_tools.append(tc.name)
                self._reset_superuser_timer()
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "⚠️ Límite de 10 iteraciones alcanzado."

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

        if self._config_calendar.active:
            reply, saved = await self._config_calendar.handle(msg)
            if saved:
                # Reload calendar client from fresh credentials
                async with self._pool.acquire() as conn:
                    repo = Repository(conn, self._employee_id)
                    enc_provider = await repo.get_credential("calendar_provider")
                    if enc_provider:
                        provider = self._store.decrypt(enc_provider)
                        if provider == "google":
                            enc = await repo.get_credential("calendar_google_token")
                            creds = json.loads(self._store.decrypt(enc))
                        else:
                            enc = await repo.get_credential("calendar_caldav")
                            creds = json.loads(self._store.decrypt(enc))
                        self._calendar = make_calendar_client(provider, creds)
                        if self._executor is not None:
                            self._executor._calendar = self._calendar
            await update.message.reply_text(reply, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        # Superuser activation
        if msg == "/superuser":
            self._superuser_until = datetime.now() + timedelta(minutes=30)
            await update.message.reply_text(  # type: ignore[union-attr]
                "🔓 Modo superusuario activo durante 30 minutos de inactividad.\n"
                "Los comandos destructivos se ejecutarán sin confirmación."
            )
            return

        # Pending destructive confirmation
        if self._pending_tool is not None:
            tc = self._pending_tool
            if msg.lower().strip() in ("sí", "si", "s", "yes", "y"):
                self._pending_tool = None
                result = await self._executor.run(tc.name, tc.args)  # type: ignore[union-attr]
                self._pending_used_tools.append(tc.name)  # type: ignore[union-attr]
                self._reset_superuser_timer()
                self._pending_messages.append({  # type: ignore[union-attr]
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                messages = self._pending_messages
                system = self._pending_system
                used_tools = self._pending_used_tools
                original_msg = self._pending_original_msg
                self._pending_messages = None
                self._pending_system = None
                self._pending_used_tools = None
                self._pending_original_msg = ""
                response = await self._run_tool_loop(messages, system, used_tools)  # type: ignore[arg-type]
                async with self._pool.acquire() as conn:
                    repo = Repository(conn, self._employee_id)
                    memory = MemoryManager(repo=repo, embed_client=self._embed)
                    await memory.save_turn(original_msg, response)
                await update.message.reply_text(response, parse_mode="Markdown")  # type: ignore[union-attr]
            else:
                self._pending_tool = None
                self._pending_messages = None
                self._pending_system = None
                self._pending_used_tools = None
                self._pending_original_msg = ""
                await update.message.reply_text("❌ Comando cancelado.")  # type: ignore[union-attr]
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

        if msg.lower() == "/config_calendar":
            reply = self._config_calendar.start()
            await update.message.reply_text(reply, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        if msg.lower() in ("/calendario", "/calendar"):
            if self._calendar is None:
                await update.message.reply_text(  # type: ignore[union-attr]
                    "Calendario no configurado. Usa /config_calendar para configurarlo."
                )
                return
            events = await self._calendar.list_events(days_ahead=7)
            if not events:
                await update.message.reply_text("📅 No tienes eventos en los próximos 7 días.")  # type: ignore[union-attr]
                return
            lines = ["📅 *Próximos eventos:*"]
            for e in events:
                lines.append(f"• *{e.title}* — {e.start.strftime('%d/%m %H:%M')}")
                if e.location:
                    lines.append(f"  📍 {e.location}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")  # type: ignore[union-attr]
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

        if self._executor is not None:
            cal_context = await _build_calendar_context(self._calendar)
            system = _build_tool_system(self._employee_name, self._profile, cal_context)
            self._pending_original_msg = msg
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                recent = await repo.get_recent_conversations(limit=10)
            history = [{"role": c.role, "content": c.content} for c in reversed(recent)]
            response = await self._run_tool_loop(
                messages=history + [{"role": "user", "content": msg}],
                system=system,
                used_tools=[],
            )
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                memory = MemoryManager(repo=repo, embed_client=self._embed)
                await memory.save_turn(msg, response)
            await update.message.reply_text(response, parse_mode="Markdown")  # type: ignore[union-attr]
            return

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
                    chat=self._vision,
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
                            lines.append(
                                f"📧 <b>{html.escape(m.sender)}</b>\n"
                                f"<i>{html.escape(m.subject)}</i>"
                            )
                            seen.add(str(m.uid))
                        text = f"📬 Tienes {len(new_messages)} email(s) nuevo(s):\n\n" + "\n\n".join(lines)
                        await app.bot.send_message(
                            chat_id=self._allowed_chat_id,
                            text=text,
                            parse_mode="HTML",
                        )
                        # Save updated seen UIDs
                        encrypted = self._store.encrypt(json.dumps(list(seen)))
                        async with self._pool.acquire() as conn:
                            repo = Repository(conn, self._employee_id)
                            await repo.save_credential("email_seen_uids", encrypted)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Email poller error for secretary %s", self._employee_id)
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


def _build_tool_system(employee_name: str, profile: dict | None, cal_context: str = "") -> str:
    from datetime import datetime as _dt
    bot_name = (profile or {}).get("bot_name") or employee_name
    preferred_name = (profile or {}).get("preferred_name") or employee_name
    language = (profile or {}).get("language") or "español"
    tool_names = ", ".join(t["function"]["name"] for t in TOOL_DEFINITIONS)
    now_str = _dt.now().strftime("%A %d/%m/%Y %H:%M")
    base = (
        f"Eres {bot_name}, asistente técnico personal de {preferred_name}. "
        f"Responde en {language}. "
        f"Tienes acceso a herramientas de sistema: {tool_names}. "
        "Úsalas para completar las tareas. Ejecuta en silencio y da un resumen al final. "
        "NUNCA uses chino ni muestres razonamiento interno."
        f"\n\nFecha y hora actual: {now_str}"
    )
    if cal_context:
        base = f"{base}\n\n{cal_context}"
    return base


async def _build_calendar_context(calendar: CalendarClient | None) -> str:
    if calendar is None:
        return ""
    try:
        events = await calendar.list_events(days_ahead=3)
        if not events:
            return ""
        lines = ["Próximos eventos (3 días):"]
        for e in events[:3]:
            lines.append(f"- {e.title} ({e.start.strftime('%d/%m/%Y %H:%M')})")
        return "\n".join(lines)
    except Exception:
        return ""
