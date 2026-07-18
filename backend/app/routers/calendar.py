from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import User, Role, CalendarCredential
from app.services import calendar_service

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/oauth/start")
def oauth_start(user: User = Depends(require_role(Role.ADMIN))):
    if not calendar_service.is_configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google Calendar isn't configured yet on the backend. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in the backend's .env to real values from Google Cloud Console "
            "(see docs/GOOGLE_CALENDAR_SETUP.md), then restart the backend and try again.",
        )
    flow = calendar_service.build_oauth_flow()
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
def oauth_callback(code: str, db: Session = Depends(get_db)):
    flow = calendar_service.build_oauth_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    # In a real deployment you'd tie this back to the admin's session; for the POC
    # the callback simply persists the token as "the" clinic credential.
    admin = db.query(User).filter(User.role == Role.ADMIN).first()
    calendar_service.save_credentials(db, creds.refresh_token, admin.id if admin else None)
    return RedirectResponse(url="/admin/calendar-connected")


@router.get("/status")
def status_(user: User = Depends(require_role(Role.ADMIN)), db: Session = Depends(get_db)):
    connected = db.query(CalendarCredential).first() is not None
    return {"connected": connected, "configured": calendar_service.is_configured()}
