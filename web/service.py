from __future__ import annotations

import json
from dataclasses import dataclass

import asyncpg

_CHANNEL_LIFECYCLE = "secretary.lifecycle"


@dataclass
class StatsRow:
    secretaries_total: int
    secretaries_active: int
    msgs_today: int
    shared_docs: int
    vault_notes: int


@dataclass
class SecretaryRow:
    id: str
    name: str
    telegram_chat_id: str | None
    is_active: bool
    msgs_today: int
    tools_enabled: bool = False


class WebAdminService:
    """Admin service for cross-employee queries.

    IMPORTANT: This service must use a SUPERUSER database connection
    to bypass Row Level Security policies. Never use svapp role credentials.
    """

    def __init__(self, pool: asyncpg.Pool, redis, credential_store) -> None:
        self._pool = pool
        self._redis = redis
        self._store = credential_store

    async def get_stats(self) -> StatsRow:
        async with self._pool.acquire() as conn:
            sec = await conn.fetchrow(
                "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_active) AS active "
                "FROM employees WHERE NOT is_orchestrator"
            )
            msgs = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM conversations WHERE created_at >= CURRENT_DATE"
            )
            docs = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM vault_notes WHERE source = 'shared'"
            )
            notes = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM vault_notes"
            )
        return StatsRow(
            secretaries_total=sec["total"],
            secretaries_active=sec["active"],
            msgs_today=msgs["count"],
            shared_docs=docs["count"],
            vault_notes=notes["count"],
        )

    async def list_secretaries(self) -> list[SecretaryRow]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    e.id::text AS id,
                    e.name,
                    e.telegram_chat_id,
                    e.is_active,
                    COUNT(c.id) FILTER (WHERE c.created_at >= CURRENT_DATE)::int AS msgs_today,
                    EXISTS(
                        SELECT 1 FROM credentials cr
                        WHERE cr.employee_id = e.id AND cr.service_type = 'tools_enabled'
                    ) AS tools_enabled
                FROM employees e
                LEFT JOIN conversations c ON c.employee_id = e.id
                WHERE NOT e.is_orchestrator
                GROUP BY e.id, e.name, e.telegram_chat_id, e.is_active
                ORDER BY e.name
                """
            )
        return [
            SecretaryRow(
                id=r["id"],
                name=r["name"],
                telegram_chat_id=r["telegram_chat_id"],
                is_active=r["is_active"],
                msgs_today=r["msgs_today"] or 0,
                tools_enabled=r["tools_enabled"],
            )
            for r in rows
        ]

    async def create_secretary(
        self,
        name: str,
        token: str,
        chat_id: str,
        tools_enabled: bool = False,
    ) -> str:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                emp_id = await conn.fetchval(
                    "INSERT INTO employees (name, telegram_chat_id) VALUES ($1, $2) RETURNING id::text",
                    name,
                    chat_id,
                )
                encrypted_token = self._store.encrypt(token)
                await conn.execute(
                    "INSERT INTO credentials (employee_id, service_type, encrypted) VALUES ($1, $2, $3)",
                    emp_id,
                    "telegram_token",
                    encrypted_token,
                )
                if tools_enabled:
                    await conn.execute(
                        "INSERT INTO credentials (employee_id, service_type, encrypted) VALUES ($1, $2, $3)",
                        emp_id,
                        "tools_enabled",
                        self._store.encrypt("true"),
                    )
        await self._redis.publish(
            _CHANNEL_LIFECYCLE,
            json.dumps({"event": "created", "employee_id": str(emp_id)}),
        )
        return str(emp_id)

    async def deactivate_secretary(self, employee_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE employees SET is_active = false WHERE id = $1::uuid",
                employee_id,
            )
        await self._redis.publish(
            _CHANNEL_LIFECYCLE,
            json.dumps({"event": "destroyed", "employee_id": employee_id}),
        )

    async def toggle_tools(self, employee_id: str) -> bool:
        async with self._pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT encrypted FROM credentials WHERE employee_id=$1::uuid AND service_type='tools_enabled'",
                employee_id,
            )
            if existing:
                await conn.execute(
                    "DELETE FROM credentials WHERE employee_id=$1::uuid AND service_type='tools_enabled'",
                    employee_id,
                )
                enabled = False
            else:
                await conn.execute(
                    "INSERT INTO credentials (employee_id, service_type, encrypted) VALUES ($1::uuid, $2, $3)",
                    employee_id, "tools_enabled", self._store.encrypt("true"),
                )
                enabled = True

        msg = "⚡ Superpower ON — ahora tengo acceso a herramientas del sistema." if enabled else "🔒 Superpower OFF — herramientas desactivadas."
        await self._redis.publish(f"secretary.{employee_id}", json.dumps({"type": "admin_message", "content": msg}))
        await self._redis.publish("secretary.lifecycle", json.dumps({"event": "tools_updated", "employee_id": employee_id}))
        return enabled

    async def send_message(self, employee_ids: list[str], text: str) -> None:
        payload = json.dumps({"type": "admin_message", "content": text})
        for emp_id in employee_ids:
            await self._redis.publish(f"secretary.{emp_id}", payload)

    async def list_shared_docs(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT vault_path, title, modified_at::text FROM vault_notes "
                "WHERE source = 'shared' ORDER BY modified_at DESC LIMIT 100"
            )
        return [dict(r) for r in rows]
