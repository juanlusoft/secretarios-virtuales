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

(
    CE_ADDRESS,
    CE_PASS,
    CE_IMAP_HOST,
    CE_IMAP_PORT,
    CE_SMTP_HOST,
    CE_SMTP_PORT,
    CE_USER,
    CE_PASS_CUSTOM,
) = range(8)


def build_config_email_handler(agent) -> ConversationHandler:  # type: ignore[type-arg]

    async def cmd_config_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not await agent._is_authorized(update):
            return ConversationHandler.END
        await update.message.reply_text(  # type: ignore[union-attr]
            "📧 *Configuración de email*\n\nEscribe tu dirección de correo:",
            parse_mode="Markdown",
        )
        return CE_ADDRESS

    async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        email = update.message.text.strip().lower()  # type: ignore[union-attr]
        context.user_data["ce_username"] = email  # type: ignore[index]
        provider = get_provider(email)
        if provider:
            context.user_data["ce_provider"] = provider  # type: ignore[index]
            domain = email.split("@")[-1]
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Proveedor detectado: *{domain}*.\n\nContraseña del email:",
                parse_mode="Markdown",
            )
            return CE_PASS
        await update.message.reply_text("Servidor IMAP (ej: mail.tuempresa.com):")  # type: ignore[union-attr]
        return CE_IMAP_HOST

    async def receive_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        await update.message.delete()  # type: ignore[union-attr]
        provider = context.user_data["ce_provider"]  # type: ignore[index]
        username = context.user_data["ce_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": provider["imap_host"], "port": provider["imap_port"],
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": provider["smtp_host"], "port": provider["smtp_port"],
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        await _set_has_email(agent)
        await update.message.reply_text("✅ Email configurado correctamente.")  # type: ignore[union-attr]
        return ConversationHandler.END

    async def receive_imap_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_imap_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto IMAP (normalmente 993):")  # type: ignore[union-attr]
        return CE_IMAP_PORT

    async def receive_imap_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw = update.message.text.strip()  # type: ignore[union-attr]
        if not raw.isdigit():
            await update.message.reply_text("Por favor, ingresa un número de puerto válido (ej: 993):")  # type: ignore[union-attr]
            return CE_IMAP_PORT
        context.user_data["ce_imap_port"] = raw  # type: ignore[index]
        await update.message.reply_text("Servidor SMTP (ej: smtp.tuempresa.com):")  # type: ignore[union-attr]
        return CE_SMTP_HOST

    async def receive_smtp_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_smtp_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto SMTP (normalmente 587):")  # type: ignore[union-attr]
        return CE_SMTP_PORT

    async def receive_smtp_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raw = update.message.text.strip()  # type: ignore[union-attr]
        if not raw.isdigit():
            await update.message.reply_text("Por favor, ingresa un número de puerto válido (ej: 587):")  # type: ignore[union-attr]
            return CE_SMTP_PORT
        context.user_data["ce_smtp_port"] = raw  # type: ignore[index]
        await update.message.reply_text("Usuario del correo:")  # type: ignore[union-attr]
        return CE_USER

    async def receive_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_username"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Contraseña:")  # type: ignore[union-attr]
        return CE_PASS_CUSTOM

    async def receive_pass_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        await update.message.delete()  # type: ignore[union-attr]
        username = context.user_data["ce_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": context.user_data["ce_imap_host"],  # type: ignore[index]
            "port": int(context.user_data["ce_imap_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": context.user_data["ce_smtp_host"],  # type: ignore[index]
            "port": int(context.user_data["ce_smtp_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        await _set_has_email(agent)
        await update.message.reply_text("✅ Email configurado correctamente.")  # type: ignore[union-attr]
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text("Configuración de email cancelada.")  # type: ignore[union-attr]
        return ConversationHandler.END

    _text = filters.TEXT & ~filters.COMMAND

    return ConversationHandler(
        entry_points=[CommandHandler("config_email", cmd_config_email)],
        states={
            CE_ADDRESS:    [MessageHandler(_text, receive_address)],
            CE_PASS:       [MessageHandler(_text, receive_pass)],
            CE_IMAP_HOST:  [MessageHandler(_text, receive_imap_host)],
            CE_IMAP_PORT:  [MessageHandler(_text, receive_imap_port)],
            CE_SMTP_HOST:  [MessageHandler(_text, receive_smtp_host)],
            CE_SMTP_PORT:  [MessageHandler(_text, receive_smtp_port)],
            CE_USER:       [MessageHandler(_text, receive_user)],
            CE_PASS_CUSTOM:[MessageHandler(_text, receive_pass_custom)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )


async def _set_has_email(agent) -> None:  # type: ignore[type-arg]
    profile = await agent._load_profile()
    if profile:
        profile["has_email"] = True
        await agent._save_profile(profile)
        agent._profile = profile
