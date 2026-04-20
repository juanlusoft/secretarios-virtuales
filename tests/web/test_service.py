import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import date

from web.service import WebAdminService, SecretaryRow, StatsRow


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock()
    return redis


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.encrypt.return_value = "encrypted_token"
    return store


@pytest.fixture
def service(mock_pool, mock_redis, mock_store):
    pool, _ = mock_pool
    return WebAdminService(pool=pool, redis=mock_redis, credential_store=mock_store)


@pytest.mark.asyncio
async def test_get_stats_returns_expected_shape(service, mock_pool):
    _, conn = mock_pool
    conn.fetchrow.side_effect = [
        {"total": 3, "active": 2},  # secretaries
        {"count": 847},              # msgs today
        {"count": 12},               # shared docs
        {"count": 38},               # vault notes
    ]

    result = await service.get_stats()

    assert result.secretaries_total == 3
    assert result.secretaries_active == 2
    assert result.msgs_today == 847
    assert result.shared_docs == 12
    assert result.vault_notes == 38


@pytest.mark.asyncio
async def test_list_secretaries_returns_rows(service, mock_pool):
    _, conn = mock_pool
    emp_id = uuid4()
    conn.fetch.return_value = [
        {
            "id": emp_id,
            "name": "María",
            "telegram_chat_id": "987654321",
            "is_active": True,
            "msgs_today": 234,
        }
    ]

    result = await service.list_secretaries()

    assert len(result) == 1
    assert result[0].name == "María"
    assert result[0].msgs_today == 234
    assert result[0].is_active is True


@pytest.mark.asyncio
async def test_create_secretary_inserts_and_publishes(service, mock_pool, mock_redis, mock_store):
    _, conn = mock_pool
    new_id = uuid4()
    conn.fetchval.return_value = new_id

    result = await service.create_secretary(
        name="Ana", token="bot:TOKEN", chat_id="111222333", tools_enabled=False
    )

    assert result == str(new_id)
    mock_store.encrypt.assert_called_with("bot:TOKEN")
    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "secretary.lifecycle"


@pytest.mark.asyncio
async def test_deactivate_secretary_soft_deletes(service, mock_pool, mock_redis):
    _, conn = mock_pool
    emp_id = uuid4()
    conn.execute = AsyncMock()

    await service.deactivate_secretary(str(emp_id))

    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "is_active" in sql.lower()
    mock_redis.publish.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_publishes_to_each_recipient(service, mock_redis):
    ids = [str(uuid4()), str(uuid4())]
    await service.send_message(employee_ids=ids, text="Reunión mañana")

    assert mock_redis.publish.call_count == 2


@pytest.mark.asyncio
async def test_list_shared_docs_returns_vault_notes(service, mock_pool):
    _, conn = mock_pool
    conn.fetch.return_value = [
        {"vault_path": "shared/doc.md", "title": "Documento", "modified_at": "2026-01-01"}
    ]

    result = await service.list_shared_docs()

    assert len(result) == 1
    assert result[0]["title"] == "Documento"
