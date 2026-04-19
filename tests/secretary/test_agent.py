import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from secretary.agent import SecretaryAgent
from shared.crypto import CredentialStore

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


async def test_load_profile_returns_none_when_missing(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    # repo.get_credential returns None
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    profile = await agent._load_profile()
    assert profile is None


async def test_save_and_load_profile_roundtrip(agent_deps):
    key = CredentialStore.generate_key()
    agent_deps["fernet_key"] = key
    agent = SecretaryAgent(**agent_deps)

    saved_encrypted: dict = {}

    async def mock_execute(sql, *args):
        if "INSERT INTO credentials" in sql:
            saved_encrypted["value"] = args[2]  # third param is encrypted

    async def mock_fetchrow(sql, *args):
        if saved_encrypted:
            return {"encrypted": saved_encrypted["value"]}
        return None

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))

    profile = {"bot_name": "Clara", "gender": "feminine", "preferred_name": "Francis",
               "language": "español", "has_email": False, "has_calendar": False}
    await agent._save_profile(profile)
    loaded = await agent._load_profile()
    assert loaded == profile


async def test_save_email_credentials_stores_both(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    stored: list = []

    async def mock_execute(sql, *args):
        if "INSERT INTO credentials" in sql:
            stored.append(args[1])  # service_type

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))

    await agent._save_email_credentials(
        '{"host": "imap.gmail.com", "port": 993, "username": "a@b.com", "password": "x"}',
        '{"host": "smtp.gmail.com", "port": 587, "username": "a@b.com", "password": "x"}',
    )
    assert "email_imap" in stored
    assert "email_smtp" in stored
