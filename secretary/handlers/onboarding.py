# secretary/handlers/onboarding.py
import json

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers._email_providers import get_provider

# States
(
    BOT_NAME,
    USER_NAME,
    LANGUAGE,
    EMAIL_ADDRESS,
    EMAIL_PASS,
    EMAIL_CUSTOM_IMAP_HOST,
    EMAIL_CUSTOM_IMAP_PORT,
    EMAIL_CUSTOM_SMTP_HOST,
    EMAIL_CUSTOM_SMTP_PORT,
    EMAIL_CUSTOM_USER,
    EMAIL_CUSTOM_PASS,
    CALENDAR,
) = range(12)


def _detect_gender(name: str) -> str:
    return "feminine" if name.strip().lower().endswith("a") else "masculine"


def build_onboarding_handler(agent) -> ConversationHandler:  # type: ignore[type-arg]

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not await agent._is_authorized(update):
            return ConversationHandler.END
        profile = agent._profile or await agent._load_profile()
        if profile:
            bot_name = profile.get("bot_name", "tu secretario")
            preferred_name = profile.get("preferred_name", agent._employee_name)
            await update.message.reply_text(  # type: ignore[union-attr]
                f"👋 ¡Hola {preferred_name}! Soy {bot_name}, ya estoy listo para ayudarte."
            )
            return ConversationHandler.END
        await update.message.reply_text(  # type: ignore[union-attr]
            "👋 ¡Hola! Soy tu nuevo secretario virtual.\n\n"
            "Vamos a configurarme juntos en unos pocos pasos.\n\n"
            "¿Cómo quieres llamarme? (ej: Clara, Marcos, Alex...)"
        )
        return BOT_NAME

    async def receive_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        bot_name = update.message.text.strip()  # type: ignore[union-attr]
        context.user_data["bot_name"] = bot_name  # type: ignore[index]
        gender = _detect_gender(bot_name)
        context.user_data["gender"] = gender  # type: ignore[index]
        gender_word = "encantada" if gender == "feminine" else "encantado"
        await update.message.reply_text(  # type: ignore[union-attr]
            f"¡{gender_word}! Me llamaré *{bot_name}*.\n\n"
            "¿Cómo quieres que me dirija a ti?",
            parse_mode="Markdown",
        )
        return USER_NAME

    async def receive_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        preferred_name = update.message.text.strip()  # type: ignore[union-attr]
        context.user_data["preferred_name"] = preferred_name  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            f"Perfecto, {preferred_name}.\n\n"
            "¿En qué idioma prefieres que me comunique contigo?\n"
            "(ej: español, English, français...)"
        )
        return LANGUAGE

    async def receive_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["language"] = update.message.text.strip()  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "¿Quieres conectar tu cuenta de email?\n\n"
            "Escribe tu dirección de correo y lo configuro automáticamente,\n"
            "o envía /skip para hacerlo más adelante con /config\\_email.",
            parse_mode="Markdown",
        )
        return EMAIL_ADDRESS

    async def receive_email_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        email = update.message.text.strip().lower()  # type: ignore[union-attr]
        context.user_data["email_username"] = email  # type: ignore[index]
        provider = get_provider(email)
        if provider:
            context.user_data["email_provider"] = provider  # type: ignore[index]
            domain = email.split("@")[-1]
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Proveedor detectado: *{domain}*.\n\n"
                "Ahora necesito tu contraseña.\n"
                "_(Para Gmail usa una contraseña de aplicación)_",
                parse_mode="Markdown",
            )
            return EMAIL_PASS
        await update.message.reply_text(  # type: ignore[union-attr]
            "Dominio personalizado. Voy a pedirte los datos del servidor.\n\n"
            "¿Cuál es el servidor IMAP? (ej: mail.tuempresa.com)"
        )
        return EMAIL_CUSTOM_IMAP_HOST

    async def skip_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_email"] = False  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "Sin problema, puedes configurarlo más adelante con /config\\_email.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_email_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        await update.message.delete()  # type: ignore[union-attr]
        provider = context.user_data["email_provider"]  # type: ignore[index]
        username = context.user_data["email_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": provider["imap_host"], "port": provider["imap_port"],
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": provider["smtp_host"], "port": provider["smtp_port"],
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        context.user_data["has_email"] = True  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "✅ Email configurado.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_custom_imap_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["imap_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto IMAP (normalmente 993):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_IMAP_PORT

    async def receive_custom_imap_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw = update.message.text.strip()  # type: ignore[union-attr]
        if not raw.isdigit():
            await update.message.reply_text("Por favor, ingresa un número de puerto válido (ej: 993):")  # type: ignore[union-attr]
            return EMAIL_CUSTOM_IMAP_PORT
        context.user_data["imap_port"] = raw  # type: ignore[index]
        await update.message.reply_text("Servidor SMTP (ej: smtp.tuempresa.com):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_SMTP_HOST

    async def receive_custom_smtp_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["smtp_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto SMTP (normalmente 587):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_SMTP_PORT

    async def receive_custom_smtp_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw = update.message.text.strip()  # type: ignore[union-attr]
        if not raw.isdigit():
            await update.message.reply_text("Por favor, ingresa un número de puerto válido (ej: 587):")  # type: ignore[union-attr]
            return EMAIL_CUSTOM_SMTP_PORT
        context.user_data["smtp_port"] = raw  # type: ignore[index]
        await update.message.reply_text("Usuario del correo (normalmente tu dirección completa):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_USER

    async def receive_custom_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["email_username"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Contraseña:")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_PASS

    async def receive_custom_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        await update.message.delete()  # type: ignore[union-attr]
        username = context.user_data["email_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": context.user_data["imap_host"],  # type: ignore[index]
            "port": int(context.user_data["imap_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": context.user_data["smtp_host"],  # type: ignore[index]
            "port": int(context.user_data["smtp_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        context.user_data["has_email"] = True  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "✅ Email configurado.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_calendar"] = True  # type: ignore[index]
        context.user_data["calendar_type"] = update.message.text.strip()  # type: ignore[union-attr, index]
        return await _finish_onboarding(update, context)

    async def skip_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_calendar"] = False  # type: ignore[index]
        return await _finish_onboarding(update, context)

    async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        profile = {
            "bot_name": context.user_data["bot_name"],  # type: ignore[index]
            "gender": context.user_data["gender"],  # type: ignore[index]
            "preferred_name": context.user_data["preferred_name"],  # type: ignore[index]
            "language": context.user_data["language"],  # type: ignore[index]
            "has_email": context.user_data.get("has_email", False),  # type: ignore[union-attr]
            "has_calendar": context.user_data.get("has_calendar", False),  # type: ignore[union-attr]
            "calendar_type": context.user_data.get("calendar_type", ""),  # type: ignore[union-attr]
        }
        try:
            await agent._save_profile(profile)
            agent._profile = profile
        except Exception:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Error al guardar la configuración. Por favor, intenta /start de nuevo."
            )
            return ConversationHandler.END

        capabilities = [
            "📄 Documentos y PDFs",
            "🎙 Mensajes de voz",
            "🖼 Imágenes y fotos",
            "✅ Tareas y recordatorios",
        ]
        if profile["has_email"]:
            capabilities.append("📧 Email")
        if profile["has_calendar"]:
            capabilities.append("📅 Calendario (próximamente)")
        caps_text = "\n".join(f"  • {c}" for c in capabilities)
        gender_word = "lista" if profile["gender"] == "feminine" else "listo"

        await update.message.reply_text(  # type: ignore[union-attr]
            f"¡Todo configurado! Estoy {gender_word} para ayudarte, "
            f"{profile['preferred_name']}.\n\n"
            f"*Capacidades activas:*\n{caps_text}\n\n"
            "¡Envíame lo que necesites!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text(  # type: ignore[union-attr]
            "Configuración cancelada. Envía /start cuando quieras empezar de nuevo."
        )
        return ConversationHandler.END

    _text = filters.TEXT & ~filters.COMMAND

    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            BOT_NAME:              [MessageHandler(_text, receive_bot_name)],
            USER_NAME:             [MessageHandler(_text, receive_user_name)],
            LANGUAGE:              [MessageHandler(_text, receive_language)],
            EMAIL_ADDRESS:         [MessageHandler(_text, receive_email_address),
                                    CommandHandler("skip", skip_email)],
            EMAIL_PASS:            [MessageHandler(_text, receive_email_pass)],
            EMAIL_CUSTOM_IMAP_HOST:[MessageHandler(_text, receive_custom_imap_host)],
            EMAIL_CUSTOM_IMAP_PORT:[MessageHandler(_text, receive_custom_imap_port)],
            EMAIL_CUSTOM_SMTP_HOST:[MessageHandler(_text, receive_custom_smtp_host)],
            EMAIL_CUSTOM_SMTP_PORT:[MessageHandler(_text, receive_custom_smtp_port)],
            EMAIL_CUSTOM_USER:     [MessageHandler(_text, receive_custom_user)],
            EMAIL_CUSTOM_PASS:     [MessageHandler(_text, receive_custom_pass)],
            CALENDAR:              [MessageHandler(_text, receive_calendar),
                                    CommandHandler("skip", skip_calendar)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )
