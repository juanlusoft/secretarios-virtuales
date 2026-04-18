from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


@pytest.fixture
def supervisor():
    return Supervisor(
        dsn="postgresql://svuser:svpassword@localhost:5432/secretarios",
        redis_url="redis://localhost:6379",
    )


async def test_spawn_creates_process(supervisor):
    employee_id = uuid4()
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.pid = 12345

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_spawn:
        await supervisor._spawn(employee_id)

    mock_spawn.assert_called_once()
    assert employee_id in supervisor._processes


async def test_spawn_skips_already_running(supervisor):
    employee_id = uuid4()
    mock_proc = AsyncMock()
    mock_proc.returncode = None

    supervisor._processes[employee_id] = mock_proc

    with patch("asyncio.create_subprocess_exec") as mock_spawn:
        await supervisor._spawn(employee_id)

    mock_spawn.assert_not_called()


async def test_terminate_stops_process(supervisor):
    employee_id = uuid4()
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    supervisor._processes[employee_id] = mock_proc

    await supervisor._terminate(employee_id)

    mock_proc.terminate.assert_called_once()
    assert employee_id not in supervisor._processes
