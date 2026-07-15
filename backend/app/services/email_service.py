"""
Email is never sent "fire and forget". Every notification is first written to the
EmailOutbox table (status=pending), then an attempt is made immediately. If that
attempt fails (SMTP down, rate-limited, network blip), the row stays `pending`/`failed`
and a background job (jobs/email_retry_job.py) retries it with backoff until
EMAIL_MAX_ATTEMPTS is hit, at which point it's marked `dead` and visible to the admin.
This means a flaky SMTP provider can never silently swallow a booking confirmation.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailOutbox, EmailStatus

logger = logging.getLogger("email_service")


def queue_email(db: Session, to_email: str, subject: str, body_html: str, category: str,
                 related_appointment_id: str | None = None) -> EmailOutbox:
    row = EmailOutbox(
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        category=category,
        related_appointment_id=related_appointment_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    attempt_send(db, row)
    return row


def _send_smtp(to_email: str, subject: str, body_html: str) -> None:
    if settings.EMAIL_DRY_RUN or not settings.SMTP_HOST:
        logger.info("[EMAIL DRY-RUN] to=%s subject=%s", to_email, subject)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_USER, [to_email], msg.as_string())


def attempt_send(db: Session, row: EmailOutbox) -> bool:
    row.attempts += 1
    try:
        _send_smtp(row.to_email, row.subject, row.body_html)
        row.status = EmailStatus.SENT
        row.last_error = None
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        row.last_error = str(exc)[:500]
        row.status = EmailStatus.DEAD if row.attempts >= settings.EMAIL_MAX_ATTEMPTS else EmailStatus.FAILED
        db.commit()
        logger.error("Email send failed (attempt %s) to %s: %s", row.attempts, row.to_email, exc)
        return False


# ---------- Templates ----------

def booking_confirmation_html(name: str, other_party: str, when: str, role_label: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>Appointment Confirmed</h2>
      <p>Hi {name},</p>
      <p>Your appointment with <b>{other_party}</b> is confirmed for <b>{when}</b>.</p>
      <p>A calendar invite has been sent to this email address.</p>
      <p style="color:#666;font-size:13px">You are receiving this as the {role_label} on this booking.</p>
    </div>"""


def cancellation_html(name: str, other_party: str, when: str, reason: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>Appointment Cancelled</h2>
      <p>Hi {name},</p>
      <p>Your appointment with <b>{other_party}</b> scheduled for <b>{when}</b> has been cancelled.</p>
      <p><b>Reason:</b> {reason}</p>
      <p>Please book a new slot at your convenience.</p>
    </div>"""


def reminder_html(name: str, when: str, doctor_name: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>Appointment Reminder</h2>
      <p>Hi {name}, this is a reminder of your upcoming appointment with {doctor_name} at <b>{when}</b>.</p>
    </div>"""


def medication_reminder_html(name: str, medication: str, dosage: str, time_of_day: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>Medication Reminder</h2>
      <p>Hi {name}, it's time for your <b>{time_of_day}</b> dose of <b>{medication} {dosage}</b>.</p>
    </div>"""
