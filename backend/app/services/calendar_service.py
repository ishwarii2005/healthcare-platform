"""
Google Calendar integration.

Design choice (explained in docs/SYSTEM_DESIGN.md): rather than requiring every
patient and every doctor to individually complete Google OAuth, the ADMIN connects
one clinic Google account, once. Every appointment becomes a single calendar event
on that clinic calendar with the doctor and patient added as `attendees`, so both
get a normal Google Calendar invite (with email notification + their own "yes/maybe/no"
RSVP) in their own calendars without ever touching OAuth themselves.

If the clinic calendar is not yet connected, or the API call fails, booking still
succeeds - the appointment simply has no google_event_id and a warning is logged.
Calendar failures must never block booking, exactly like LLM failures.
"""
import logging
from datetime import datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CalendarCredential

logger = logging.getLogger("calendar_service")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def build_oauth_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def save_credentials(db: Session, refresh_token: str, admin_id: str) -> None:
    existing = db.query(CalendarCredential).first()
    if existing:
        existing.refresh_token = refresh_token
        existing.connected_by_admin_id = admin_id
    else:
        db.add(CalendarCredential(refresh_token=refresh_token, connected_by_admin_id=admin_id))
    db.commit()


def _get_service(db: Session):
    cred_row = db.query(CalendarCredential).first()
    if not cred_row:
        return None
    creds = Credentials(
        token=None,
        refresh_token=cred_row.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(db: Session, summary: str, description: str, start: datetime, end: datetime,
                  attendee_emails: list[str]) -> str | None:
    try:
        service = _get_service(db)
        if service is None:
            logger.info("Calendar not connected - skipping event creation")
            return None
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            "attendees": [{"email": e} for e in attendee_emails],
            "reminders": {"useDefault": True},
        }
        created = service.events().insert(
            calendarId=settings.CLINIC_CALENDAR_ID, body=event, sendUpdates="all"
        ).execute()
        return created.get("id")
    except Exception as exc:  # noqa: BLE001
        logger.error("Calendar event creation failed: %s", exc)
        return None


def update_event(db: Session, event_id: str, start: datetime, end: datetime) -> bool:
    try:
        service = _get_service(db)
        if service is None or not event_id:
            return False
        event = service.events().get(calendarId=settings.CLINIC_CALENDAR_ID, eventId=event_id).execute()
        event["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
        event["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
        service.events().update(
            calendarId=settings.CLINIC_CALENDAR_ID, eventId=event_id, body=event, sendUpdates="all"
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Calendar event update failed: %s", exc)
        return False


def delete_event(db: Session, event_id: str) -> bool:
    try:
        service = _get_service(db)
        if service is None or not event_id:
            return False
        service.events().delete(
            calendarId=settings.CLINIC_CALENDAR_ID, eventId=event_id, sendUpdates="all"
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Calendar event deletion failed: %s", exc)
        return False
