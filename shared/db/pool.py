from contextlib import asynccontextmanager
from typing import AsyncGenerator
from uuid import UUID

import asyncpg


class DatabasePool:
    def __init__(self, dsn: str, employee_id: UUID) -> None:
        self._dsn = dsn
        self._employee_id = employee_id
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        if self._pool is None:
            raise RuntimeError("Call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_employee_id', $1, false)",
                str(self._employee_id),
            )
            yield conn
