from __future__ import annotations

from uuid import UUID

from shared.db.models import Task
from shared.db.pool import DatabasePool


class TasksClient:
    def __init__(self, pool: DatabasePool, employee_id: UUID) -> None:
        self._pool = pool
        self._employee_id = employee_id

    async def create(self, title: str, description: str | None = None) -> str:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            task_id = await repo.save_task(title=title, description=description)
            return str(task_id)

    async def list_all(self) -> list[Task]:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.get_all_tasks()

    async def mark_done(self, task_id: str) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.mark_task_done(task_id=task_id)

    async def update(self, task_id: str, title: str | None = None, description: str | None = None) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.update_task(task_id=task_id, title=title, description=description)
