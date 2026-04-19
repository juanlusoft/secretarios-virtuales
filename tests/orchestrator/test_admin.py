from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from orchestrator.admin import AdminService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def admin():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    return AdminService(
        dsn="postgresql://svuser:svpassword@localhost:5432/secretarios",
        redis_url="redis://localhost:6379",
        fernet_key=key,
    )


async def test_send_message_publishes_to_redis(admin):
    employee_id = uuid4()
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("redis.asyncio.from_url", return_value=mock_redis):
        await admin.send_message_to_secretary(employee_id, "Reunión a las 10h")

    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert f"secretary.{employee_id}" == call_args[0][0]
    import json
    data = json.loads(call_args[0][1])
    assert data["type"] == "admin_message"
    assert data["content"] == "Reunión a las 10h"
