from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from secretary.handlers.config_email import EmailConfigFlow

pytestmark = pytest.mark.asyncio

_EMPLOYEE_ID = uuid4()


def _make_flow() -> tuple[EmailConfigFlow, MagicMock]:
    pool = MagicMock()
    store = MagicMock()
    store.encrypt = lambda v: f"enc:{v}"
    flow = EmailConfigFlow(_EMPLOYEE_ID, pool, store)
    return flow, pool


def _mock_pool_conn(pool: MagicMock) -> AsyncMock:
    """Configure pool.acquire() to return a usable async context manager."""
    conn = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm
    return conn


async def _complete_flow(flow: EmailConfigFlow) -> tuple[str, bool]:
    """Run through all steps with valid data."""
    flow.start()
    await flow.handle("imap.example.com")
    await flow.handle("993")
    await flow.handle("smtp.example.com")
    await flow.handle("587")
    await flow.handle("user@example.com")
    await flow.handle("s3cr3t")
    return await flow.handle("sí")


async def test_flow_not_active_initially():
    flow, _ = _make_flow()
    assert not flow.active


async def test_flow_active_after_start():
    flow, _ = _make_flow()
    flow.start()
    assert flow.active


async def test_cancel_mid_flow():
    flow, _ = _make_flow()
    flow.start()
    await flow.handle("imap.example.com")
    reply, saved = await flow.handle("cancelar")
    assert not saved
    assert not flow.active
    assert "cancelad" in reply.lower()


async def test_invalid_port_retries():
    flow, _ = _make_flow()
    flow.start()
    await flow.handle("imap.example.com")
    reply, saved = await flow.handle("no-es-un-puerto")
    assert not saved
    assert flow.active
    assert "inválido" in reply.lower()


async def test_full_flow_saves_credentials():
    flow, pool = _make_flow()
    _mock_pool_conn(pool)

    with patch("secretary.handlers.config_email.Repository") as MockRepo:
        repo_instance = AsyncMock()
        MockRepo.return_value = repo_instance

        reply, saved = await _complete_flow(flow)

    assert saved
    assert not flow.active
    assert "configurado" in reply.lower()
    assert repo_instance.save_credential.call_count == 2


async def test_confirm_no_cancels():
    flow, _ = _make_flow()
    flow.start()
    await flow.handle("imap.example.com")
    await flow.handle("")          # default port
    await flow.handle("smtp.example.com")
    await flow.handle("")          # default port
    await flow.handle("user@example.com")
    await flow.handle("pass")
    reply, saved = await flow.handle("no")
    assert not saved
    assert not flow.active


async def test_default_ports():
    flow, pool = _make_flow()
    _mock_pool_conn(pool)

    flow.start()
    await flow.handle("imap.example.com")
    await flow.handle("")   # should default to 993
    await flow.handle("smtp.example.com")
    await flow.handle("")   # should default to 587
    await flow.handle("user@example.com")
    await flow.handle("pass")

    with patch("secretary.handlers.config_email.Repository") as MockRepo:
        repo_instance = AsyncMock()
        MockRepo.return_value = repo_instance
        await flow.handle("sí")

    import json
    saved_imap = json.loads(repo_instance.save_credential.call_args_list[0][0][1].replace("enc:", ""))
    saved_smtp = json.loads(repo_instance.save_credential.call_args_list[1][0][1].replace("enc:", ""))
    assert saved_imap["port"] == 993
    assert saved_smtp["port"] == 587
