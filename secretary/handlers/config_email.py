from __future__ import annotations

import json
from enum import Enum, auto
from uuid import UUID

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

from ._email_providers import get_provider


class _Step(Enum):
    EMAIL = auto()
    PASSWORD = auto()
    IMAP_HOST = auto()
    IMAP_PORT = auto()
    SMTP_HOST = auto()
    SMTP_PORT = auto()
    CUSTOM_PASS = auto()
    CONFIRM = auto()


_APP_PASSWORD_NOTES: dict[str, str] = {
    "gmail.com": (
        "⚠️ *Gmail requiere una contraseña de aplicación*, no tu contraseña normal.\n\n"
        "Cómo obtenerla:\n"
        "1. Ve a myaccount.google.com/apppasswords\n"
        "2. Selecciona *Otra* → escribe 'Secretario'\n"
        "3. Copia la clave de 16 caracteres que te da Google\n\n"
        "Pégala aquí sin espacios:"
    ),
    "yahoo.com": (
        "⚠️ *Yahoo requiere una contraseña de aplicación*.\n\n"
        "Cómo obtenerla:\n"
        "1. Ve a login.yahoo.com → Seguridad de la cuenta\n"
        "2. Activa la verificación en dos pasos si no la tienes\n"
        "3. Genera una contraseña de aplicación\n\n"
        "Pégala aquí:"
    ),
    "outlook.com": (
        "Introduce tu contraseña de Outlook/Microsoft:"
    ),
    "hotmail.com": (
        "Introduce tu contraseña de Hotmail/Microsoft:"
    ),
}

_CANCEL_WORDS = {"cancelar", "/cancelar", "cancel", "/cancel"}


class EmailConfigFlow:
    """Multi-step wizard to collect and save IMAP/SMTP credentials."""

    def __init__(self, employee_id: UUID, pool: DatabasePool, store: CredentialStore) -> None:
        self._employee_id = employee_id
        self._pool = pool
        self._store = store
        self._step: _Step | None = None
        self._data: dict[str, str | int] = {}

    @property
    def active(self) -> bool:
        return self._step is not None

    def start(self) -> str:
        self._step = _Step.EMAIL
        self._data = {}
        return (
            "⚙️ *Configuración de email* — escribe `cancelar` en cualquier momento para salir.\n\n"
            "¿Cuál es tu dirección de correo?"
        )

    async def handle(self, text: str) -> tuple[str, bool]:
        text = text.strip()
        if text.lower() in _CANCEL_WORDS:
            self._step = None
            return "❌ Configuración cancelada.", False
        return await self._advance(self._step, text)  # type: ignore[arg-type]

    async def _advance(self, step: _Step, text: str) -> tuple[str, bool]:
        if step == _Step.EMAIL:
            email = text.lower()
            self._data["username"] = email
            provider = get_provider(email)
            if provider:
                domain = email.split("@")[-1]
                self._data.update({
                    "imap_host": provider["imap_host"],
                    "imap_port": provider["imap_port"],
                    "smtp_host": provider["smtp_host"],
                    "smtp_port": provider["smtp_port"],
                })
                self._step = _Step.PASSWORD
                note = _APP_PASSWORD_NOTES.get(domain, "Introduce tu contraseña:")
                return f"✅ Proveedor detectado: *{domain}*\n\n{note}", False
            self._step = _Step.IMAP_HOST
            return "Dominio personalizado. ¿Servidor IMAP? _(ej: mail.tuempresa.com)_:", False

        if step == _Step.IMAP_HOST:
            self._data["imap_host"] = text
            self._step = _Step.IMAP_PORT
            return "Puerto IMAP _(pulsa Enter para usar 993)_:", False

        if step == _Step.IMAP_PORT:
            try:
                self._data["imap_port"] = int(text) if text else 993
            except ValueError:
                return "❌ Puerto inválido, introduce un número:", False
            self._step = _Step.SMTP_HOST
            return "¿Servidor SMTP? _(ej: smtp.tuempresa.com)_:", False

        if step == _Step.SMTP_HOST:
            self._data["smtp_host"] = text
            self._step = _Step.SMTP_PORT
            return "Puerto SMTP _(pulsa Enter para usar 587)_:", False

        if step == _Step.SMTP_PORT:
            try:
                self._data["smtp_port"] = int(text) if text else 587
            except ValueError:
                return "❌ Puerto inválido, introduce un número:", False
            self._step = _Step.CUSTOM_PASS
            return "Contraseña:", False

        if step in (_Step.PASSWORD, _Step.CUSTOM_PASS):
            self._data["password"] = text
            self._step = _Step.CONFIRM
            d = self._data
            return (
                f"✅ *Resumen:*\n"
                f"• Cuenta: `{d['username']}`\n"
                f"• IMAP: `{d['imap_host']}:{d['imap_port']}`\n"
                f"• SMTP: `{d['smtp_host']}:{d['smtp_port']}`\n\n"
                "¿Confirmar? *(sí / no)*"
            ), False

        if step == _Step.CONFIRM:
            if text.lower() in ("sí", "si", "s", "yes", "y"):
                await self._save()
                self._step = None
                return "✅ Email configurado. Usa */email* para revisar tu bandeja de entrada.", True
            self._step = None
            return "❌ Cancelado. Usa */config_email* para volver a intentarlo.", False

        return "Error interno.", False

    async def _save(self) -> None:
        d = self._data
        imap_json = json.dumps({
            "host": d["imap_host"],
            "port": d["imap_port"],
            "username": d["username"],
            "password": d["password"],
        })
        smtp_json = json.dumps({
            "host": d["smtp_host"],
            "port": d["smtp_port"],
            "username": d["username"],
            "password": d["password"],
        })
        enc_imap = self._store.encrypt(imap_json)
        enc_smtp = self._store.encrypt(smtp_json)
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("email_imap", enc_imap)
            await repo.save_credential("email_smtp", enc_smtp)
