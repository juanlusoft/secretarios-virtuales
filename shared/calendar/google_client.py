from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow

from shared.calendar.models import CalendarEvent

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def build_auth_url(client_id: str, client_secret: str) -> str:
    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=_SCOPES,
        redirect_uri=_REDIRECT_URI,
    )
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return url


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=_SCOPES,
        redirect_uri=_REDIRECT_URI,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def _make_credentials(token_data: dict) -> Credentials:
    expiry = None
    if token_data.get("expiry"):
        expiry = datetime.fromisoformat(token_data["expiry"])
    return Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=_SCOPES,
        expiry=expiry,
    )


def _parse_item(item: dict) -> CalendarEvent:
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})
    start_str = start_raw.get("dateTime") or start_raw.get("date", "")
    end_str = end_raw.get("dateTime") or end_raw.get("date", "")
    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return CalendarEvent(
        id=item["id"],
        title=item.get("summary", "(sin título)"),
        start=start,
        end=end,
        description=item.get("description", ""),
        location=item.get("location", ""),
    )


class GoogleCalendarClient:
    def __init__(self, token_data: dict) -> None:
        self._token_data = token_data

    def _get_service(self):
        creds = _make_credentials(self._token_data)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_data = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
            }
        return build("calendar", "v3", credentials=creds)

    async def list_events(self, days_ahead: int = 7) -> list[CalendarEvent]:
        def _sync() -> list[CalendarEvent]:
            service = self._get_service()
            now = datetime.now(tz=timezone.utc)
            end = now + timedelta(days=days_ahead)
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return [_parse_item(item) for item in result.get("items", [])]
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
            service = self._get_service()
            body: dict = {
                "summary": title,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            }
            if description:
                body["description"] = description
            if location:
                body["location"] = location
            created = service.events().insert(calendarId="primary", body=body).execute()
            return _parse_item(created)
        return await asyncio.to_thread(_sync)

    async def modify_event(self, event_id: str, **fields) -> CalendarEvent:
        def _sync() -> CalendarEvent:
            service = self._get_service()
            existing = service.events().get(calendarId="primary", eventId=event_id).execute()
            if "title" in fields:
                existing["summary"] = fields["title"]
            if "start_iso" in fields:
                existing["start"] = {"dateTime": fields["start_iso"]}
            if "end_iso" in fields:
                existing["end"] = {"dateTime": fields["end_iso"]}
            if "description" in fields:
                existing["description"] = fields["description"]
            if "location" in fields:
                existing["location"] = fields["location"]
            updated = (
                service.events()
                .update(calendarId="primary", eventId=event_id, body=existing)
                .execute()
            )
            return _parse_item(updated)
        return await asyncio.to_thread(_sync)

    async def cancel_event(self, event_id: str) -> None:
        def _sync() -> None:
            service = self._get_service()
            service.events().delete(calendarId="primary", eventId=event_id).execute()
        await asyncio.to_thread(_sync)
