import json
import os
from uuid import UUID

import asyncpg

from shared.crypto import CredentialStore


class AdminService:
    def __init__(self, dsn: str, redis_url: str, fernet_key: bytes) -> None:
        self._dsn = dsn
        self._redis_url = redis_url
        self._store = CredentialStore(fernet_key)

    async def create_secretary(
        self,
        name: str,
        telegram_token: str,
        telegram_chat_id: str,
    ) -> UUID:
        conn = await asyncpg.connect(self._dsn)
        try:
            employee_id = await conn.fetchval(
                """
                INSERT INTO employees (name, telegram_chat_id)
                VALUES ($1, $2)
                RETURNING id
                """,
                name, telegram_chat_id,
            )
            await conn.execute(
                "SELECT set_config('app.current_employee_id', $1, true)", str(employee_id)
            )
            encrypted_token = self._store.encrypt(telegram_token)
            await conn.execute(
                """
                INSERT INTO credentials (employee_id, service_type, encrypted)
                VALUES ($1, 'telegram_token', $2)
                """,
                employee_id, encrypted_token,
            )
        finally:
            await conn.close()

        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish("secretary.lifecycle", json.dumps({
            "event": "created",
            "employee_id": str(employee_id),
        }))
        await r.aclose()

        return employee_id

    async def destroy_secretary(self, employee_id: UUID) -> None:
        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute(
                "UPDATE employees SET is_active = false WHERE id = $1", employee_id
            )
        finally:
            await conn.close()

        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish("secretary.lifecycle", json.dumps({
            "event": "destroyed",
            "employee_id": str(employee_id),
        }))
        await r.aclose()

    async def list_secretaries(self) -> list[dict]:
        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT id, name, telegram_chat_id, is_active, created_at
                FROM employees
                WHERE is_orchestrator = false
                ORDER BY created_at
                """
            )
        finally:
            await conn.close()
        return [dict(r) for r in rows]

    async def send_message_to_secretary(
        self, employee_id: UUID, content: str
    ) -> None:
        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish(
            f"secretary.{employee_id}",
            json.dumps({"type": "admin_message", "content": content}),
        )
        await r.aclose()
