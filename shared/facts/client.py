from __future__ import annotations

from uuid import UUID

from shared.db.models import Fact
from shared.db.pool import DatabasePool


class FactsClient:
    def __init__(self, pool: DatabasePool, employee_id: UUID) -> None:
        self._pool = pool
        self._employee_id = employee_id

    async def save(self, key: str, value: str, category: str = "general") -> None:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_fact(key=key, value=value, category=category)

    async def list_all(self, category: str | None = None) -> list[Fact]:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.list_facts(category=category)

    async def delete(self, key: str) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.delete_fact(key=key)
