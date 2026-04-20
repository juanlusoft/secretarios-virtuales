from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from secretary.memory import MemoryManager
from shared.db.models import VaultNote, Conversation

pytestmark = pytest.mark.asyncio

EMPLOYEE_ID = uuid4()
NOW = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)


def _make_note(source: str, title: str, content: str) -> VaultNote:
    return VaultNote(
        id=uuid4(),
        employee_id=EMPLOYEE_ID,
        source=source,
        vault_path=f"{title}.md",
        title=title,
        tags=[],
        content_text=content,
        modified_at=NOW,
        indexed_at=NOW,
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_recent_conversations = AsyncMock(return_value=[])
    repo.search_documents = AsyncMock(return_value=[])
    repo.search_vault_notes = AsyncMock(return_value=[])
    repo.save_conversation = AsyncMock()
    return repo


@pytest.fixture
def mock_embed():
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[0.1] * 1024)
    return embed


async def test_build_context_empty(mock_repo, mock_embed):
    manager = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    context = await manager.build_context("hola")
    assert isinstance(context, str)


async def test_build_context_includes_conversations(mock_repo, mock_embed):
    conv = Conversation(
        id=uuid4(), employee_id=uuid4(), role="user",
        content="Reunión ayer", source="telegram", created_at=datetime.now()
    )
    mock_repo.get_recent_conversations = AsyncMock(return_value=[conv])
    manager = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    context = await manager.build_context("qué pasó ayer")
    assert "Reunión ayer" in context


async def test_save_turn(mock_repo, mock_embed):
    manager = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    await manager.save_turn(user_msg="hola", assistant_msg="hola a ti")
    assert mock_repo.save_conversation.call_count == 2


async def test_build_context_includes_vault_notes(mock_repo, mock_embed):
    mock_repo.get_recent_conversations.return_value = []
    mock_repo.search_documents.return_value = []
    mock_repo.search_vault_notes.return_value = [
        _make_note("shared", "Política empresa", "No usar redes sociales en horario laboral."),
    ]

    memory = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    context = await memory.build_context("política de empresa")

    assert "Base de conocimiento" in context
    assert "Política empresa" in context
    assert "No usar redes sociales" in context


async def test_build_context_personal_notes_labeled(mock_repo, mock_embed):
    mock_repo.get_recent_conversations.return_value = []
    mock_repo.search_documents.return_value = []
    mock_repo.search_vault_notes.return_value = [
        _make_note("personal", "Notas reunión", "Reunión el lunes a las 10h."),
    ]

    memory = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    context = await memory.build_context("reunión")

    assert "Notas personales" in context
    assert "Notas reunión" in context


async def test_build_context_empty_vault_notes_no_section(mock_repo, mock_embed):
    mock_repo.get_recent_conversations.return_value = []
    mock_repo.search_documents.return_value = []
    mock_repo.search_vault_notes.return_value = []

    memory = MemoryManager(repo=mock_repo, embed_client=mock_embed)
    context = await memory.build_context("algo")

    assert context == ""
