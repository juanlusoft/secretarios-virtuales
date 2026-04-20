import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from shared.calendar.remind import build_alert_text, check_and_alert


def make_event(minutes_from_now: int, title: str = "Reunión", location: str = "") -> object:
    from shared.calendar.models import CalendarEvent
    now = datetime.now(tz=timezone.utc)
    start = now + timedelta(minutes=minutes_from_now)
    return CalendarEvent(id=f"uid-{title}", title=title, start=start,
                         end=start + timedelta(hours=1), location=location)


def test_build_alert_text_no_location():
    event = make_event(45, "Demo")
    text = build_alert_text(event)
    assert "Demo" in text
    assert "📅" in text


def test_build_alert_text_with_location():
    event = make_event(30, "Cita", location="Oficina")
    text = build_alert_text(event)
    assert "Oficina" in text


@pytest.mark.asyncio
async def test_check_and_alert_publishes_new_event():
    emp_id = str(uuid4())
    event = make_event(45)
    calendar = MagicMock()
    calendar.list_events = AsyncMock(return_value=[event])
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)  # not yet alerted
    redis.setex = AsyncMock()
    redis.publish = AsyncMock()

    await check_and_alert(
        employee_id=emp_id,
        calendar=calendar,
        redis=redis,
        reminder_minutes=60,
    )

    redis.publish.assert_called_once()
    call_args = redis.publish.call_args[0]
    assert call_args[0] == f"secretary.{emp_id}"
    payload = json.loads(call_args[1])
    assert payload["type"] == "admin_message"
    assert "Reunión" in payload["content"]


@pytest.mark.asyncio
async def test_check_and_alert_skips_already_alerted():
    emp_id = str(uuid4())
    event = make_event(45)
    calendar = MagicMock()
    calendar.list_events = AsyncMock(return_value=[event])
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1)  # already alerted

    await check_and_alert(
        employee_id=emp_id,
        calendar=calendar,
        redis=redis,
        reminder_minutes=60,
    )

    redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_alert_skips_on_calendar_error():
    emp_id = str(uuid4())
    calendar = MagicMock()
    calendar.list_events = AsyncMock(side_effect=Exception("connection refused"))
    redis = AsyncMock()

    # Should not raise
    await check_and_alert(
        employee_id=emp_id,
        calendar=calendar,
        redis=redis,
        reminder_minutes=60,
    )

    redis.publish.assert_not_called()
