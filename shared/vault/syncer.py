from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from shared.db.repository import Repository
from shared.vault.parser import parse_note

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0


class VaultSyncer:
    def __init__(
        self,
        pool,
        employee_id: UUID,
        employee_name: str,
        embed,
        vaults_dir: Path,
    ) -> None:
        self._pool = pool
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._embed = embed
        self._vaults_dir = Path(vaults_dir)

    async def sync(self) -> SyncResult:
        result = SyncResult()
        for source, vault_dir in self._vault_dirs():
            await self._sync_source(source, vault_dir, result)
        return result

    def _vault_dirs(self) -> list[tuple[str, Path]]:
        dirs = []
        shared = self._vaults_dir / "shared"
        if shared.is_dir():
            dirs.append(("shared", shared))
        personal = self._vaults_dir / self._employee_name.lower()
        if personal.is_dir():
            dirs.append(("personal", personal))
        return dirs

    async def _sync_source(
        self, source: str, vault_dir: Path, result: SyncResult
    ) -> None:
        md_files = list(vault_dir.rglob("*.md"))

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            existing = await repo.get_vault_note_mtimes(source)

            disk_paths: list[str] = []
            for path in md_files:
                note = parse_note(path, vault_root=vault_dir)
                disk_paths.append(note.vault_path)

                db_mtime = existing.get(note.vault_path)
                if db_mtime is not None:
                    note_mtime = note.modified_at
                    if db_mtime.tzinfo is None:
                        db_mtime = db_mtime.replace(tzinfo=timezone.utc)
                    if note_mtime <= db_mtime:
                        result.skipped += 1
                        continue
                    is_update = True
                else:
                    is_update = False

                embedding = await self._embed.embed(note.content_text or note.title)
                await repo.upsert_vault_note(
                    source=source,
                    vault_path=note.vault_path,
                    title=note.title,
                    tags=note.tags,
                    content_text=note.content_text,
                    embedding=embedding,
                    modified_at=note.modified_at,
                )
                if is_update:
                    result.updated += 1
                else:
                    result.added += 1

            stale = [p for p in existing if p not in disk_paths]
            if stale:
                await repo.delete_vault_notes_not_in(source, disk_paths)
                result.deleted += len(stale)
