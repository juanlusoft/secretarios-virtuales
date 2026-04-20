import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from shared.calendar.google_client import GoogleCalendarClient, build_auth_url, exchange_code
from shared.calendar.models import CalendarEvent


TOKEN = {
    "token": "access",
    "refresh_token": "refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
    "expiry": None,
}


def test_build_auth_url_returns_url():
    url = build_auth_url(client_id="cid", client_secret="csecret")
    assert url.startswith("https://accounts.google.com")


@pytest.mark.asyncio
async def test_list_events_returns_events():
    client = GoogleCalendarClient(TOKEN)
    now = datetime.now(tz=timezone.utc)
    mock_item = {
        "id": "event-google-1",
        "summary": "Google Meet",
        "start": {"dateTime": now.isoformat()},
        "end": {"dateTime": (now + timedelta(hours=1)).isoformat()},
        "description": "",
        "location": "",
    }
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [mock_item]
    }

    with patch("shared.calendar.google_client.build", return_value=mock_service):
        with patch("shared.calendar.google_client.Credentials"):
            events = await client.list_events(days_ahead=7)

    assert len(events) == 1
    assert events[0].id == "event-google-1"
    assert events[0].title == "Google Meet"


@pytest.mark.asyncio
async def test_cancel_event_calls_delete():
    client = GoogleCalendarClient(TOKEN)
    mock_service = MagicMock()

    with patch("shared.calendar.google_client.build", return_value=mock_service):
        with patch("shared.calendar.google_client.Credentials"):
            await client.cancel_event("event-google-1")

    mock_service.events.return_value.delete.assert_called_once_with(
        calendarId="primary", eventId="event-google-1"
    )
    mock_service.events.return_value.delete.return_value.execute.assert_called_once()
