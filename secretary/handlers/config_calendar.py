from __future__ import annotations

import json
from enum import Enum, auto
from uuid import UUID

from shared.calendar.caldav_client import CalDAVClient
from shared.calendar.google_client import build_auth_url, exchange_code
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

_CANCEL_WORDS = {"cancelar", "/cancelar", "cancel", "/cancel"}


class _Step(Enum):
    PROVIDER = auto()
    GOOGLE_CODE = auto()
    CALDAV_SERVER = auto()
    CALDAV_USER = auto()
    CALDAV_PASS = auto()
    REMINDER = auto()


class CalendarConfigFlow:
    """Multi-step wizard to configure Google Calendar or CalDAV credentials."""

    def __init__(
        self,
        employee_id: UUID,
        pool: DatabasePool,
        store: CredentialStore,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        self._employee_id = employee_id
        self._pool = pool
        self._store = store
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret
        self._step: _Step | None = None
        self._data: dict = {}

    @property
    def active(self) -> bool:
        return self._step is not None

    def start(self) -> str:
        self._step = _Step.PROVIDER
        self._data = {}
        return (
            "⚙️ *Configuración de calendario* — escribe `cancelar` para salir.\n\n"
            "¿Qué proveedor quieres usar?\n"
            "1️⃣ Google Calendar\n"
            "2️⃣ CalDAV (Nextcloud, iCloud, etc.)"
        )

    async def handle(self, text: str) -> tuple[str, bool]:
        text = text.strip()
        if text.lower() in _CANCEL_WORDS:
            self._step = None
            return "❌ Configuración de calendario cancelada.", False
        return await self._advance(self._step, text)

    async def _advance(self, step: _Step, text: str) -> tuple[str, bool]:
        if step == _Step.PROVIDER:
            if text == "1":
                self._data["provider"] = "google"
                self._step = _Step.GOOGLE_CODE
                url = build_auth_url(self._google_client_id, self._google_client_secret)
                return (
                    f"🔗 Abre este enlace en tu navegador y autoriza el acceso:\n\n{url}\n\n"
                    "Luego pega aquí el código que te muestra Google:"
                ), False
            if text == "2":
                self._data["provider"] = "caldav"
                self._step = _Step.CALDAV_SERVER
                return "¿URL del servidor CalDAV? _(ej: https://nextcloud.ejemplo.com/remote.php/dav)_:", False
            return "Elige *1* para Google Calendar o *2* para CalDAV:", False

        if step == _Step.GOOGLE_CODE:
            try:
                token_data = exchange_code(
                    self._google_client_id, self._google_client_secret, text
                )
            except Exception as e:
                return f"❌ Error al verificar el código: {e}\n\nInténtalo de nuevo o escribe `cancelar`:", False
            self._data["token"] = token_data
            self._step = _Step.REMINDER
            return "✅ Google Calendar conectado.\n\n¿Con cuántos minutos de antelación quieres recibir recordatorios? _(ej: 60)_:", False

        if step == _Step.CALDAV_SERVER:
            self._data["server"] = text
            self._step = _Step.CALDAV_USER
            return "¿Usuario CalDAV?:", False

        if step == _Step.CALDAV_USER:
            self._data["username"] = text
            self._step = _Step.CALDAV_PASS
            return "🔒 ¿Contraseña? _(borra el mensaje después de enviarlo)_:", False

        if step == _Step.CALDAV_PASS:
            creds = {
                "server": self._data["server"],
                "username": self._data["username"],
                "password": text,
            }
            try:
                test_client = CalDAVClient(creds)
                await test_client.list_events(days_ahead=1)
            except Exception as e:
                return f"❌ No se pudo conectar: {e}\n\n¿Contraseña correcta? Inténtalo de nuevo o escribe `cancelar`:", False
            self._data["caldav"] = creds
            self._step = _Step.REMINDER
            return "✅ CalDAV conectado.\n\n¿Con cuántos minutos de antelación quieres recibir recordatorios? _(ej: 60)_:", False

        if step == _Step.REMINDER:
            try:
                minutes = int(text)
                if minutes <= 0:
                    raise ValueError
            except ValueError:
                return "❌ Introduce un número entero positivo (ej: 30, 60, 120):", False
            self._data["reminder_minutes"] = str(minutes)
            await self._save()
            self._step = None
            return (
                f"✅ Calendario configurado. Recibirás recordatorios {minutes} minutos antes de cada evento.\n"
                "Usa */calendario* para ver tus próximos eventos."
            ), True

        return "Error interno.", False

    async def _save(self) -> None:
        provider = self._data["provider"]
        reminder = self._data["reminder_minutes"]

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("calendar_provider", self._store.encrypt(provider))
            await repo.save_credential("calendar_reminder_minutes", self._store.encrypt(reminder))

            if provider == "google":
                token_json = json.dumps(self._data["token"])
                await repo.save_credential("calendar_google_token", self._store.encrypt(token_json))
            else:
                caldav_json = json.dumps(self._data["caldav"])
                await repo.save_credential("calendar_caldav", self._store.encrypt(caldav_json))
