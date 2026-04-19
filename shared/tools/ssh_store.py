from __future__ import annotations

import json
from uuid import UUID

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

_PREFIX = "ssh:"


class SSHStore:
    def __init__(self, pool: DatabasePool, employee_id: UUID, store: CredentialStore) -> None:
        self._pool = pool
        self._employee_id = employee_id
        self._store = store

    async def save(
        self,
        name: str,
        host: str,
        user: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 22,
    ) -> None:
        data = {"host": host, "user": user, "port": port}
        if password:
            data["password"] = password
        if ssh_key:
            data["ssh_key"] = ssh_key
        encrypted = self._store.encrypt(json.dumps(data))
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential(f"{_PREFIX}{name}", encrypted)

    async def load(self, name: str) -> dict:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            raw = await repo.get_credential(f"{_PREFIX}{name}")
        if raw is None:
            raise KeyError(f"No existe conexión SSH con nombre '{name}'. Usa ssh_list para ver las disponibles.")
        return json.loads(self._store.decrypt(raw))

    async def list_all(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            rows = await repo.get_credentials_by_prefix(_PREFIX)
        result = []
        for service_type, encrypted in rows:
            name = service_type[len(_PREFIX):]
            try:
                data = json.loads(self._store.decrypt(encrypted))
                result.append({"name": name, "host": data.get("host", "?"), "port": data.get("port", 22), "user": data.get("user", "?")})
            except Exception:
                pass
        return result
