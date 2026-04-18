import pytest
from unittest.mock import AsyncMock
from uuid import uuid4
from secretary.memory import MemoryManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_recent_conversations = AsyncMock(return_value=[])
    repo.search_documents = AsyncMock(return_value=[])
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
    from shared.db.models import Conversation
    from datetime import datetime
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
