from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from secretary.agent import SecretaryAgent

pytestmark = pytest.mark.asyncio


@pytest.fixture
def agent_deps():
    return {
        "employee_id": uuid4(),
        "employee_name": "Alejandro",
        "allowed_chat_id": "123456789",
        "db_pool": AsyncMock(),
        "chat": AsyncMock(),
        "embed": AsyncMock(),
        "whisper": AsyncMock(),
        "documents_dir": MagicMock(),
        "fernet_key": b"glKFCTFI1LlqFJLsdDCDccpjGpVxfo7O7cwxvaov7jE=",
        "redis_url": "redis://localhost:6379",
    }


async def test_agent_ignores_unauthorized_chat(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    update = MagicMock()
    update.effective_chat.id = "999999"

    result = await agent._is_authorized(update)
    assert result is False


async def test_agent_allows_authorized_chat(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    update = MagicMock()
    update.effective_chat.id = "123456789"

    result = await agent._is_authorized(update)
    assert result is True
