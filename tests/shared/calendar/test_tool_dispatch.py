import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta

from shared.tools.executor import ToolExecutor
from shared.calendar.models import CalendarEvent


def make_calendar_client():
    client = MagicMock()
    now = datetime.now(tz=timezone.utc)
    event = CalendarEvent(id="e1", title="Reunión", start=now, end=now + timedelta(hours=1))
    client.list_events = AsyncMock(return_value=[event])
    client.create_event = AsyncMock(return_value=event)
    client.modify_event = AsyncMock(return_value=event)
    client.cancel_event = AsyncMock()
    return client


@pytest.fixture
def executor():
    ssh_store = MagicMock()
    cal = make_calendar_client()
    return ToolExecutor(ssh_store=ssh_store, calendar_client=cal)


@pytest.mark.asyncio
async def test_calendar_list_returns_formatted_events(executor):
    result = await executor.run("calendar_list", {"days_ahead": 7})
    assert "Reunión" in result


@pytest.mark.asyncio
async def test_calendar_create_calls_client(executor):
    now = datetime.now(tz=timezone.utc)
    result = await executor.run("calendar_create", {
        "title": "Demo",
        "start_iso": now.isoformat(),
        "end_iso": (now + timedelta(hours=1)).isoformat(),
    })
    executor._calendar.create_event.assert_called_once()
    assert "creado" in result.lower() or "Demo" in result


@pytest.mark.asyncio
async def test_calendar_modify_calls_client(executor):
    result = await executor.run("calendar_modify", {"event_id": "e1", "title": "Nuevo"})
    executor._calendar.modify_event.assert_called_once_with("e1", title="Nuevo")


@pytest.mark.asyncio
async def test_calendar_cancel_calls_client(executor):
    result = await executor.run("calendar_cancel", {"event_id": "e1"})
    executor._calendar.cancel_event.assert_called_once_with("e1")
    assert "cancelado" in result.lower() or "e1" in result


@pytest.mark.asyncio
async def test_calendar_list_no_client():
    ssh_store = MagicMock()
    executor = ToolExecutor(ssh_store=ssh_store, calendar_client=None)
    result = await executor.run("calendar_list", {})
    assert "configur" in result.lower()
