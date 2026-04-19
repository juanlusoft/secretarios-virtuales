from __future__ import annotations

import json
from enum import Enum, auto
from uuid import UUID

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository


class _Step(Enum):
    IMAP_HOST = auto()
    IMAP_PORT = auto()
    SMTP_HOST = auto()
    SMTP_PORT = auto()
    USERNAME = auto()
    PASSWORD = auto()
    CONFIRM = auto()


_PROMPTS: dict[_Step, str] = {
    _Step.IMAP_HOST: "Paso 1/6 — Servidor IMAP _(ej: imap.gmail.com)_:",
    _Step.IMAP_PORT: "Paso 2/6 — Puerto IMAP _(pulsa Enter para usar 993)_:",
    _Step.SMTP_HOST: "Paso 3/6 — Servidor SMTP _(ej: smtp.gmail.com)_:",
    _Step.SMTP_PORT: "Paso 4/6 — Puerto SMTP _(pulsa Enter para usar 587)_:",
    _Step.USERNAME: "Paso 5/6 — Usuario (tu dirección de email):",
    _Step.PASSWORD: "Paso 6/6 — Contraseña _(o contraseña de aplicación)_:",
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
        self._step = _Step.IMAP_HOST
        self._data = {}
        return "⚙️ *Configuración de email* — escribe `cancelar` en cualquier momento para salir.\n\n" + _PROMPTS[_Step.IMAP_HOST]

    async def handle(self, text: str) -> tuple[str, bool]:
        """Process one step. Returns (reply, email_saved)."""
        text = text.strip()

        if text.lower() in _CANCEL_WORDS:
            self._step = None
            return "❌ Configuración cancelada.", False

        step = self._step
        reply, saved = await self._advance(step, text)  # type: ignore[arg-type]
        return reply, saved

    async def _advance(self, step: _Step, text: str) -> tuple[str, bool]:
        if step == _Step.IMAP_HOST:
            self._data["imap_host"] = text
            self._step = _Step.IMAP_PORT
            return _PROMPTS[_Step.IMAP_PORT], False

        if step == _Step.IMAP_PORT:
            try:
                self._data["imap_port"] = int(text) if text else 993
            except ValueError:
                return "❌ Puerto inválido, introduce un número:", False
            self._step = _Step.SMTP_HOST
            return _PROMPTS[_Step.SMTP_HOST], False

        if step == _Step.SMTP_HOST:
            self._data["smtp_host"] = text
            self._step = _Step.SMTP_PORT
            return _PROMPTS[_Step.SMTP_PORT], False

        if step == _Step.SMTP_PORT:
            try:
                self._data["smtp_port"] = int(text) if text else 587
            except ValueError:
                return "❌ Puerto inválido, introduce un número:", False
            self._step = _Step.USERNAME
            return _PROMPTS[_Step.USERNAME], False

        if step == _Step.USERNAME:
            self._data["username"] = text
            self._step = _Step.PASSWORD
            domain = text.split("@")[-1].lower() if "@" in text else ""
            if domain in ("gmail.com", "googlemail.com"):
                return (
                    "⚠️ *Gmail requiere una contraseña de aplicación*, no tu contraseña normal.\n\n"
                    "Cómo obtenerla:\n"
                    "1. Ve a myaccount.google.com/apppasswords\n"
                    "2. Selecciona *Otra (nombre personalizado)* → escribe 'Secretario'\n"
                    "3. Google te dará una clave de 16 caracteres\n\n"
                    "Pégala aquí sin espacios:"
                ), False
            return _PROMPTS[_Step.PASSWORD], False

        if step == _Step.PASSWORD:
            self._data["password"] = text
            self._step = _Step.CONFIRM
            d = self._data
            return (
                f"✅ *Resumen:*\n"
                f"• IMAP: `{d['imap_host']}:{d['imap_port']}`\n"
                f"• SMTP: `{d['smtp_host']}:{d['smtp_port']}`\n"
                f"• Usuario: `{d['username']}`\n\n"
                f"¿Confirmar? *(sí / no)*"
            ), False

        if step == _Step.CONFIRM:
            if text.lower() in ("sí", "si", "s", "yes", "y"):
                await self._save()
                self._step = None
                return "✅ Email configurado. Usa */email* para revisar tu bandeja de entrada.", True
            else:
                self._step = None
                return "❌ Cancelado. Usa */config email* para volver a intentarlo.", False

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
        })
        enc_imap = self._store.encrypt(imap_json)
        enc_smtp = self._store.encrypt(smtp_json)
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("email_imap", enc_imap)
            await repo.save_credential("email_smtp", enc_smtp)
