# Calendar Integration Design

## Context

Secretarios virtuales need calendar awareness: reading upcoming events, creating/modifying/cancelling appointments via natural language, and proactively alerting the user before events. Two backends are required — Google Calendar (OAuth) and CalDAV (Nextcloud, iCloud, Fastmail, etc.).

## Architecture

New module `shared/calendar/` provides two backend clients and a unified interface. The secretary agent exposes four LLM tools for calendar operations. A background cron service checks upcoming events per secretary and sends Telegram alerts.

```
shared/calendar/
├── __init__.py
├── models.py          # CalendarEvent dataclass
├── caldav_client.py   # CalDAV backend (caldav lib)
├── google_client.py   # Google Calendar API backend
├── client.py          # Unified CalendarClient (factory + interface)
└── remind.py          # Reminder cron loop

secretary/handlers/
└── config_calendar.py # Multi-step config wizard (CalendarConfigFlow)

infrastructure/systemd/
└── calendar-remind.service
```

## Data Model

```python
@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime        # timezone-aware
    end: datetime          # timezone-aware
    description: str = ""
    location: str = ""
```

## Credential Storage

Same pattern as email — Fernet-encrypted JSON in `credentials` table:

| service_type | Value |
|---|---|
| `calendar_provider` | `"google"` or `"caldav"` |
| `calendar_google_token` | JSON: `{access_token, refresh_token, token_uri, client_id, client_secret, expiry}` |
| `calendar_caldav` | JSON: `{server, username, password}` |
| `calendar_reminder_minutes` | `"60"` (string, configurable per secretary) |

## Configuration Wizard (`/config_calendar`)

`CalendarConfigFlow` follows the same state-machine pattern as `EmailConfigFlow` in `secretary/handlers/config_email.py`.

**Steps for Google Calendar:**
1. Ask provider choice: Google Calendar / CalDAV
2. Send OAuth authorization URL (Google)
3. Wait for user to paste the authorization code
4. Exchange code for tokens, store as `calendar_google_token`
5. Ask reminder advance time in minutes
6. Confirm and save

**Steps for CalDAV:**
1. Ask provider choice
2. Ask CalDAV server URL (e.g. `https://nextcloud.example.com/remote.php/dav`)
3. Ask username
4. Ask password (bot replies with warning to delete message)
5. Test connection — if fails, show error and retry
6. Ask reminder advance time in minutes
7. Confirm and save

**Cancel:** `/cancelar` at any step resets the wizard.

## Unified CalendarClient

```python
class CalendarClient:
    async def list_events(self, days_ahead: int = 7) -> list[CalendarEvent]: ...
    async def create_event(self, title: str, start: datetime, end: datetime,
                           description: str = "", location: str = "") -> CalendarEvent: ...
    async def modify_event(self, event_id: str, **fields) -> CalendarEvent: ...
    async def cancel_event(self, event_id: str) -> None: ...

def make_calendar_client(provider: str, credentials: dict) -> CalendarClient:
    if provider == "google":
        return GoogleCalendarClient(credentials)
    return CalDAVClient(credentials)
```

## LLM Tool Definitions (4 tools)

Added to `shared/tools/definitions.py` and dispatched in `shared/tools/executor.py`. The `ToolExecutor` receives a `CalendarClient | None` and dispatches calendar tool calls.

| Tool | Parameters | Description |
|---|---|---|
| `calendar_list` | `days_ahead: int = 7` | List upcoming events |
| `calendar_create` | `title, start_iso, end_iso, description?, location?` | Create event |
| `calendar_modify` | `event_id, title?, start_iso?, end_iso?, description?, location?` | Modify event |
| `calendar_cancel` | `event_id, reason?` | Cancel/delete event |

`start_iso` / `end_iso` use ISO 8601 format. The LLM resolves relative dates ("el viernes a las 10") to absolute datetimes using current date from system prompt.

The current date/time and next 3 upcoming events are injected into the secretary's system prompt so the LLM can answer availability questions without calling `calendar_list`.

## Reminder Cron (`shared/calendar/remind.py`)

- Runs every 5 minutes (hardcoded, not configurable — simple enough)
- For each active non-orchestrator employee with `calendar_provider` credential:
  - Fetch events starting within `[now, now + reminder_minutes]`
  - For each event not yet alerted → publish to Redis channel `secretary.{employee_id}` (same pattern as orchestrator messages; the secretary bot process delivers it to Telegram)
  - Mark as alerted in Redis: key `calendar:alerted:{employee_id}:{event_id}`, TTL 25 hours
- If calendar fetch fails → log warning, skip employee, continue loop
- Exits gracefully if no employees have calendar configured

**Alert message format:**
```
📅 *Recordatorio*: {title}
🕐 En {minutes_until} minutos ({start_time})
📍 {location if location else ""}
```

**Entry point:** `python -m shared.calendar.remind`

## Agent Integration

In `secretary/agent.py`:
- `/config_calendar` → starts `CalendarConfigFlow`
- `/calendario` → calls `calendar_list(days_ahead=7)` and formats response
- `ToolExecutor` receives `calendar_client: CalendarClient | None` — if set, calendar tools available to LLM
- `SecretaryAgent.__init__` loads calendar credentials and creates client (same pattern as email/tools)

In `secretary/__main__.py`:
- After loading credentials, create `CalendarClient` if `calendar_provider` credential exists
- Pass to `SecretaryAgent` as `calendar_client=`

## New Dependencies

```toml
"caldav>=1.3,<2",
"google-auth-oauthlib>=1.2,<2",
"google-api-python-client>=2.0,<3",
```

## Systemd Service

`infrastructure/systemd/calendar-remind.service` — same pattern as `obsidian-sync.service`. Added to `deploy.sh` automatically.

## Testing

- Unit tests for `CalendarEvent`, `GoogleCalendarClient`, `CalDAVClient` with mocked HTTP
- Unit tests for `CalendarConfigFlow` state machine (all paths: Google, CalDAV, cancel)
- Unit tests for 4 tool dispatchers in `ToolExecutor`
- Unit tests for reminder loop: deduplication, skip on error, format of alert message
- Integration marker `pytest.mark.integration` for tests requiring real calendar credentials

## Privacy

Calendar event titles and descriptions are stored only transiently (in-memory during tool execution and reminder dispatch). They are never persisted to the `conversations` table as content — only the LLM's reply to the user is stored.
