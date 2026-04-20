import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from secretary.handlers.config_calendar import CalendarConfigFlow


@pytest.fixture
def flow():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    store = MagicMock()
    store.encrypt.return_value = "encrypted"
    return CalendarConfigFlow(
        employee_id=uuid4(),
        pool=pool,
        store=store,
        google_client_id="cid",
        google_client_secret="csecret",
    )


def test_not_active_initially(flow):
    assert not flow.active


def test_start_activates_flow(flow):
    msg = flow.start()
    assert flow.active
    assert "Google" in msg or "CalDAV" in msg


@pytest.mark.asyncio
async def test_cancel_deactivates(flow):
    flow.start()
    reply, saved = await flow.handle("/cancelar")
    assert not flow.active
    assert saved is False


@pytest.mark.asyncio
async def test_caldav_full_flow(flow):
    flow.start()
    # Choose CalDAV
    reply, _ = await flow.handle("2")
    assert "servidor" in reply.lower() or "url" in reply.lower()
    reply, _ = await flow.handle("https://cal.example.com/dav")
    assert "usuario" in reply.lower() or "user" in reply.lower()
    reply, _ = await flow.handle("myuser")
    assert "contraseña" in reply.lower() or "password" in reply.lower()

    with patch("secretary.handlers.config_calendar.CalDAVClient") as mock_dav:
        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(return_value=[])
        mock_dav.return_value = mock_client

        reply, _ = await flow.handle("mypassword")

    assert "recordatorio" in reply.lower() or "minutos" in reply.lower() or "aviso" in reply.lower()
    reply, saved = await flow.handle("60")
    assert saved is True
    assert not flow.active


@pytest.mark.asyncio
async def test_google_flow_sends_url(flow):
    flow.start()
    # Choose Google
    with patch("secretary.handlers.config_calendar.build_auth_url", return_value="https://accounts.google.com/fake"):
        reply, _ = await flow.handle("1")
    assert "https://accounts.google.com" in reply
    assert flow.active


@pytest.mark.asyncio
async def test_invalid_reminder_minutes_retries(flow):
    flow.start()
    reply, _ = await flow.handle("2")
    reply, _ = await flow.handle("https://cal.example.com/dav")
    reply, _ = await flow.handle("user")
    with patch("secretary.handlers.config_calendar.CalDAVClient") as mock_dav:
        mock_dav.return_value.list_events = AsyncMock(return_value=[])
        reply, _ = await flow.handle("pass")
    reply, _ = await flow.handle("not-a-number")
    assert "número" in reply.lower() or "inválido" in reply.lower()
    assert flow.active
