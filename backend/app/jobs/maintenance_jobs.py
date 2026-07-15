import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import EmailOutbox, EmailStatus, SlotLock, Appointment, AppointmentStatus
from app.services import email_service

logger = logging.getLogger("maintenance_jobs")


def run_email_retries():
    """Retries every FAILED email that hasn't hit EMAIL_MAX_ATTEMPTS yet (see email_service docstring)."""
    db = SessionLocal()
    try:
        pending = db.query(EmailOutbox).filter(EmailOutbox.status == EmailStatus.FAILED).all()
        for row in pending:
            email_service.attempt_send(db, row)
    except Exception:
        logger.exception("Email retry job failed")
    finally:
        db.close()


def run_hold_cleanup():
    """Releases expired slot holds so abandoned bookings don't permanently block a slot."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        expired = db.query(SlotLock).filter(
            SlotLock.expires_at.isnot(None), SlotLock.expires_at < now
        ).all()
        for lock in expired:
            appt = db.get(Appointment, lock.appointment_id)
            if appt and appt.status == AppointmentStatus.HELD:
                appt.status = AppointmentStatus.CANCELLED
            db.delete(lock)
        if expired:
            db.commit()
    except Exception:
        logger.exception("Hold cleanup job failed")
    finally:
        db.close()
