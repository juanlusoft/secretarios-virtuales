from __future__ import annotations

import json
import logging
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

logger = logging.getLogger(__name__)


async def handle_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    employee_id: UUID,
    pool: DatabasePool,
    store: CredentialStore,
    executor,
) -> str:
    loc = update.message.location  # type: ignore[union-attr]
    if loc is None:
        return "No encontré ubicación en el mensaje."

    lat = loc.latitude
    lon = loc.longitude

    location_data = json.dumps({"lat": lat, "lon": lon})
    async with pool.acquire() as conn:
        repo = Repository(conn, employee_id)
        await repo.save_credential("last_location", store.encrypt(location_data))

    if executor is not None:
        executor.update_location(lat=lat, lon=lon)

    return (
        f"📍 Ubicación guardada: {lat:.5f}, {lon:.5f}\n"
        "Ahora puedo buscar lugares cercanos. Dime qué buscas (ej: 'farmacia cercana')."
    )
