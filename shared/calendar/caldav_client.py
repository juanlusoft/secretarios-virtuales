from __future__ import annotations

import asyncio
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import caldav
from icalendar import Calendar, Event  # bundled with caldav

from shared.calendar.models import CalendarEvent


class CalDAVClient:
    def __init__(self, credentials: dict) -> None:
        self._server = credentials["server"]
        self._username = credentials["username"]
        self._password = credentials["password"]

    def _get_calendar(self) -> caldav.Calendar | None:
        client = caldav.DAVClient(
            url=self._server,
            username=self._username,
            password=self._password,
        )
        principal = client.principal()
        calendars = principal.calendars()
        return calendars[0] if calendars else None

    def _parse_event(self, raw: caldav.Event) -> CalendarEvent:
        vevent = raw.vobject_instance.vevent
        uid = vevent.uid.value
        title = vevent.summary.value if hasattr(vevent, "summary") else "(sin título)"
        start = vevent.dtstart.value
        end = vevent.dtend.value if hasattr(vevent, "dtend") else start
        desc = vevent.description.value if hasattr(vevent, "description") else ""
        loc = vevent.location.value if hasattr(vevent, "location") else ""
        if not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
        if not isinstance(end, datetime):
            end = datetime.combine(end, datetime.min.time()).replace(tzinfo=timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return CalendarEvent(id=uid, title=title, start=start, end=end,
                             description=desc, location=loc)

    async def list_events(self, days_ahead: int = 7) -> list[CalendarEvent]:
        def _sync() -> list[CalendarEvent]:
            cal = self._get_calendar()
            if cal is None:
                return []
            now = datetime.now(tz=timezone.utc)
            end = now + timedelta(days=days_ahead)
            raw_events = cal.date_search(start=now, end=end, expand=True)
            return [self._parse_event(e) for e in raw_events]
        return await asyncio.to_thread(_sync)

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        def _sync() -> CalendarEvent:
            cal = self._get_calendar()
            if cal is None:
                raise RuntimeError("No CalDAV calendar found")
            uid = str(uuidlib.uuid4())
            c = Calendar()
            c.add("prodid", "-//SV Calendar//EN")
            c.add("version", "2.0")
            e = Event()
            e.add("uid", uid)
            e.add("summary", title)
            e.add("dtstart", start)
            e.add("dtend", end)
            if description:
                e.add("description", description)
            if location:
                e.add("location", location)
            c.add_component(e)
            cal.add_event(c.to_ical().decode())
            return CalendarEvent(id=uid, title=title, start=start, end=end,
                                 description=description, location=location)
        return await asyncio.to_thread(_sync)

    async def modify_event(self, event_id: str, **fields) -> CalendarEvent:
        def _sync() -> CalendarEvent:
            cal = self._get_calendar()
            if cal is None:
                raise RuntimeError("No CalDAV calendar found")
            for raw in cal.search(todo=False, event=True):
                vevent = raw.vobject_instance.vevent
                if vevent.uid.value == event_id:
                    if "title" in fields:
                        vevent.summary.value = fields["title"]
                    if "start_iso" in fields:
                        vevent.dtstart.value = datetime.fromisoformat(fields["start_iso"])
                    if "end_iso" in fields:
                        vevent.dtend.value = datetime.fromisoformat(fields["end_iso"])
                    if "description" in fields:
                        if hasattr(vevent, "description"):
                            vevent.description.value = fields["description"]
                    if "location" in fields:
                        if hasattr(vevent, "location"):
                            vevent.location.value = fields["location"]
                    raw.save()
                    return self._parse_event(raw)
            raise ValueError(f"Event {event_id} not found")
        return await asyncio.to_thread(_sync)

    async def cancel_event(self, event_id: str) -> None:
        def _sync() -> None:
            cal = self._get_calendar()
            if cal is None:
                raise RuntimeError("No CalDAV calendar found")
            for raw in cal.search(todo=False, event=True):
                if raw.vobject_instance.vevent.uid.value == event_id:
                    raw.delete()
                    return
            raise ValueError(f"Event {event_id} not found")
        await asyncio.to_thread(_sync)
