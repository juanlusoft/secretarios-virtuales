from datetime import datetime, timezone
from shared.calendar.models import CalendarEvent


def test_calendar_event_fields():
    now = datetime.now(tz=timezone.utc)
    end = datetime.now(tz=timezone.utc)
    event = CalendarEvent(id="uid-1", title="Reunión", start=now, end=end)
    assert event.id == "uid-1"
    assert event.title == "Reunión"
    assert event.description == ""
    assert event.location == ""


def test_calendar_event_optional_fields():
    now = datetime.now(tz=timezone.utc)
    event = CalendarEvent(
        id="uid-2", title="Cita", start=now, end=now,
        description="Desc", location="Oficina"
    )
    assert event.description == "Desc"
    assert event.location == "Oficina"


def test_event_start_end_stored_correctly():
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    start = now + timedelta(minutes=45)
    end = start + timedelta(hours=1)
    event = CalendarEvent(id="x", title="Demo", start=start, end=end)
    assert event.start == start
    assert event.end == end
    assert (event.end - event.start).total_seconds() == 3600
