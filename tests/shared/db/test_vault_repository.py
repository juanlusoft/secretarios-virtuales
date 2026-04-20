from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shared.db.models import VaultNote
from shared.db.repository import Repository

EMPLOYEE_ID = uuid4()
NOW = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)


def _make_repo(conn):
    return Repository(conn, EMPLOYEE_ID)


async def test_get_vault_note_mtimes_empty():
    conn = AsyncMock()
    conn.fetch.return_value = []
    repo = _make_repo(conn)
    result = await repo.get_vault_note_mtimes("shared")
    assert result == {}
    conn.fetch.assert_called_once()


async def test_get_vault_note_mtimes_returns_dict():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"vault_path": "a.md", "modified_at": NOW},
        {"vault_path": "b.md", "modified_at": NOW},
    ]
    repo = _make_repo(conn)
    result = await repo.get_vault_note_mtimes("personal")
    assert result == {"a.md": NOW, "b.md": NOW}


async def test_upsert_vault_note_calls_execute():
    conn = AsyncMock()
    repo = _make_repo(conn)
    await repo.upsert_vault_note(
        source="shared",
        vault_path="nota.md",
        title="Mi nota",
        tags=["tag1"],
        content_text="Contenido",
        embedding=[0.1] * 1024,
        modified_at=NOW,
    )
    conn.execute.assert_called_once()
    sql, *args = conn.execute.call_args[0]
    assert "INSERT INTO vault_notes" in sql
    assert "ON CONFLICT" in sql


async def test_delete_vault_notes_not_in():
    conn = AsyncMock()
    repo = _make_repo(conn)
    await repo.delete_vault_notes_not_in("shared", ["a.md", "b.md"])
    conn.execute.assert_called_once()
    sql, *args = conn.execute.call_args[0]
    assert "DELETE FROM vault_notes" in sql


async def test_search_vault_notes_returns_list():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": uuid4(),
            "employee_id": EMPLOYEE_ID,
            "source": "shared",
            "vault_path": "nota.md",
            "title": "Nota",
            "tags": ["tag1"],
            "content_text": "Contenido",
            "modified_at": NOW,
            "indexed_at": NOW,
        }
    ]
    repo = _make_repo(conn)
    result = await repo.search_vault_notes([0.1] * 1024, limit=3)
    assert len(result) == 1
    assert isinstance(result[0], VaultNote)
    assert result[0].vault_path == "nota.md"
