from __future__ import annotations

from datetime import datetime

from shared.calendar.caldav_client import CalDAVClient
from shared.calendar.google_client import GoogleCalendarClient
from shared.calendar.models import CalendarEvent


class CalendarClient:
    """Unified interface — wraps either CalDAVClient or GoogleCalendarClient."""

    def __init__(self, backend: CalDAVClient | GoogleCalendarClient) -> None:
        self._backend = backend

    async def list_events(self, days_ahead: int = 7) -> list[CalendarEvent]:
        return await self._backend.list_events(days_ahead=days_ahead)

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        return await self._backend.create_event(
            title=title, start=start, end=end,
            description=description, location=location,
        )

    async def modify_event(self, event_id: str, **fields) -> CalendarEvent:
        return await self._backend.modify_event(event_id, **fields)

    async def cancel_event(self, event_id: str) -> None:
        await self._backend.cancel_event(event_id)


def make_calendar_client(provider: str, credentials: dict) -> CalendarClient:
    if provider == "google":
        return CalendarClient(GoogleCalendarClient(credentials))
    return CalendarClient(CalDAVClient(credentials))
