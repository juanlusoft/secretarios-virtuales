from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from shared.vault.syncer import SyncResult, VaultSyncer

EMPLOYEE_ID = uuid4()
OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW = datetime(2026, 4, 20, tzinfo=timezone.utc)


def _make_pool(conn):
    pool = MagicMock()
    @asynccontextmanager
    async def acquire():
        yield conn
    pool.acquire = acquire
    return pool


def _make_syncer(tmp_path: Path, pool, embed) -> VaultSyncer:
    return VaultSyncer(
        pool=pool,
        employee_id=EMPLOYEE_ID,
        employee_name="Maria",
        embed=embed,
        vaults_dir=tmp_path,
    )


async def test_sync_adds_new_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()
    (vault / "nota.md").write_text("# Hola\nContenido.", encoding="utf-8")

    conn = AsyncMock()
    conn.fetch.return_value = []
    conn.execute = AsyncMock()

    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.added == 1
    assert result.skipped == 0
    embed.embed.assert_called_once()
    conn.execute.assert_called()


async def test_sync_skips_unchanged_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()
    note_path = vault / "nota.md"
    note_path.write_text("# Hola\nContenido.", encoding="utf-8")

    future = datetime.now(timezone.utc) + timedelta(hours=1)

    conn = AsyncMock()
    conn.fetch.return_value = [{"vault_path": "nota.md", "modified_at": future}]
    conn.execute = AsyncMock()

    embed = AsyncMock()

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.skipped == 1
    assert result.added == 0
    embed.embed.assert_not_called()


async def test_sync_deletes_removed_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()

    conn = AsyncMock()
    conn.fetch.return_value = [{"vault_path": "vieja.md", "modified_at": OLD}]
    conn.execute = AsyncMock()

    embed = AsyncMock()

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.deleted == 1
    delete_calls = [call for call in conn.execute.call_args_list if "DELETE" in str(call)]
    assert len(delete_calls) >= 1


async def test_sync_personal_vault(tmp_path):
    personal = tmp_path / "maria"
    personal.mkdir()
    (personal / "privada.md").write_text("Nota privada.", encoding="utf-8")

    conn = AsyncMock()
    conn.fetch.return_value = []
    conn.execute = AsyncMock()

    embed = AsyncMock()
    embed.embed.return_value = [0.2] * 1024

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.added == 1
