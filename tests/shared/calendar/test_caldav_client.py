import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone, timedelta

from shared.calendar.caldav_client import CalDAVClient
from shared.calendar.models import CalendarEvent


CREDS = {"server": "https://cal.example.com/dav", "username": "user", "password": "pass"}


@pytest.fixture
def client():
    return CalDAVClient(CREDS)


@pytest.mark.asyncio
async def test_list_events_returns_events(client):
    mock_event = MagicMock()
    vevent = MagicMock()
    vevent.uid.value = "event-uid-1"
    vevent.summary.value = "Reunión"
    start_dt = datetime.now(tz=timezone.utc)
    vevent.dtstart.value = start_dt
    vevent.dtend.value = start_dt + timedelta(hours=1)
    vevent.description.value = "Desc"
    vevent.location.value = ""
    mock_event.vobject_instance.vevent = vevent
    mock_cal = MagicMock()
    mock_cal.date_search.return_value = [mock_event]

    with patch("caldav.DAVClient") as mock_dav:
        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]
        mock_dav.return_value.principal.return_value = mock_principal

        events = await client.list_events(days_ahead=7)

    assert len(events) == 1
    assert events[0].id == "event-uid-1"
    assert events[0].title == "Reunión"


@pytest.mark.asyncio
async def test_list_events_no_calendars_returns_empty(client):
    with patch("caldav.DAVClient") as mock_dav:
        mock_principal = MagicMock()
        mock_principal.calendars.return_value = []
        mock_dav.return_value.principal.return_value = mock_principal

        events = await client.list_events()

    assert events == []


@pytest.mark.asyncio
async def test_cancel_event_deletes(client):
    mock_event = MagicMock()
    mock_event.vobject_instance.vevent.uid.value = "uid-to-delete"
    mock_cal = MagicMock()
    mock_cal.search.return_value = [mock_event]

    with patch("caldav.DAVClient") as mock_dav:
        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]
        mock_dav.return_value.principal.return_value = mock_principal

        await client.cancel_event("uid-to-delete")

    mock_event.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_event_not_found_raises(client):
    mock_cal = MagicMock()
    mock_cal.search.return_value = []

    with patch("caldav.DAVClient") as mock_dav:
        mock_principal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]
        mock_dav.return_value.principal.return_value = mock_principal

        with pytest.raises(ValueError, match="not found"):
            await client.cancel_event("nonexistent-uid")
