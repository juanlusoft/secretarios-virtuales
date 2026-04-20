from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv

from shared.calendar.client import make_calendar_client
from shared.calendar.models import CalendarEvent
from shared.crypto import CredentialStore

logger = logging.getLogger(__name__)

_ALERT_TTL_SECONDS = 25 * 3600
_CHECK_INTERVAL_SECONDS = 300  # 5 minutes


def build_alert_text(event: CalendarEvent) -> str:
    now = datetime.now(tz=timezone.utc)
    minutes_until = max(0, int((event.start - now).total_seconds() / 60))
    start_str = event.start.strftime("%H:%M")
    lines = [
        f"📅 *Recordatorio*: {event.title}",
        f"🕐 En {minutes_until} minutos ({start_str})",
    ]
    if event.location:
        lines.append(f"📍 {event.location}")
    return "\n".join(lines)


async def check_and_alert(
    employee_id: str,
    calendar,
    redis: aioredis.Redis,
    reminder_minutes: int,
) -> None:
    try:
        events = await calendar.list_events(days_ahead=1)
    except Exception as e:
        logger.warning("Calendar fetch failed for %s: %s", employee_id, e)
        return

    now = datetime.now(tz=timezone.utc)
    window_end = now + timedelta(minutes=reminder_minutes)

    for event in events:
        if not (now <= event.start <= window_end):
            continue
        redis_key = f"calendar:alerted:{employee_id}:{event.id}"
        already_alerted = await redis.exists(redis_key)
        if already_alerted:
            continue
        alert_text = build_alert_text(event)
        payload = json.dumps({"type": "admin_message", "content": alert_text})
        await redis.publish(f"secretary.{employee_id}", payload)
        await redis.setex(redis_key, _ALERT_TTL_SECONDS, "1")
        logger.info("Alert sent for event %s to employee %s", event.id, employee_id)


async def run_once(pool: asyncpg.Pool, redis: aioredis.Redis, store: CredentialStore) -> None:
    rows = await pool.fetch(
        "SELECT id::text FROM employees WHERE is_active AND NOT is_orchestrator"
    )
    for row in rows:
        emp_id = row["id"]
        try:
            enc_provider = await pool.fetchval(
                "SELECT encrypted FROM credentials WHERE employee_id=$1::uuid AND service_type='calendar_provider'",
                emp_id,
            )
            if enc_provider is None:
                continue
            provider = store.decrypt(enc_provider)
            if provider == "google":
                enc_creds = await pool.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1::uuid AND service_type='calendar_google_token'",
                    emp_id,
                )
            else:
                enc_creds = await pool.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1::uuid AND service_type='calendar_caldav'",
                    emp_id,
                )
            if enc_creds is None:
                continue
            creds = json.loads(store.decrypt(enc_creds))
            enc_reminder = await pool.fetchval(
                "SELECT encrypted FROM credentials WHERE employee_id=$1::uuid AND service_type='calendar_reminder_minutes'",
                emp_id,
            )
            reminder_minutes = int(store.decrypt(enc_reminder)) if enc_reminder else 60
            calendar = make_calendar_client(provider, creds)
            await check_and_alert(
                employee_id=emp_id,
                calendar=calendar,
                redis=redis,
                reminder_minutes=reminder_minutes,
            )
        except Exception as e:
            logger.warning("Error processing calendar for employee %s: %s", emp_id, e)


async def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    fernet_key = os.environ["FERNET_KEY"].encode()

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    redis = aioredis.from_url(redis_url, decode_responses=True)
    store = CredentialStore(fernet_key)

    logger.info("Calendar reminder service started (interval: %ds)", _CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await run_once(pool, redis, store)
        except Exception as e:
            logger.error("Reminder loop error: %s", e)
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
