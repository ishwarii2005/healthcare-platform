"""
When admin marks a doctor on leave for a date that already has bookings:
  1. Find every CONFIRMED/HELD appointment for that doctor on that date.
  2. Cancel each one (frees its SlotLock, deletes its calendar event) and email
     both sides with the reason.
  3. For each affected patient, compute up to 3 suggested alternative slots
     (same doctor, next available days) so the notification isn't a dead end -
     this is the "smart recovery" piece: patients get a ready-made rebooking
     path instead of having to hunt through the search UI themselves.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, DoctorProfile
from app.services import slot_service, notification_service, email_service
from app.utils.dates import to_utc_iso
import json


def handle_leave_conflicts(db: Session, doctor: DoctorProfile, leave_date, reason: str) -> list[dict]:
    day_start = datetime.combine(leave_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    affected = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.slot_start >= day_start,
            Appointment.slot_start < day_end,
            Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.HELD]),
        )
        .all()
    )

    working_hours = json.loads(doctor.working_hours_json or "{}")
    summary = []

    for appt in affected:
        alternatives = _suggest_alternative_slots(db, doctor, working_hours, after=day_end, count=3)
        alt_text = ", ".join(s.strftime("%a %d %b, %I:%M %p") for s in alternatives) or \
            "No slots found in the next 14 days - please contact the clinic."

        slot_service.cancel_appointment(db, appt, by_leave=True)
        notification_service.notify_cancellation(
            db, appt,
            reason=f"Dr. {doctor.user.full_name} is on leave on {leave_date}. {reason or ''}".strip(),
        )
        email_service.queue_email(
            db, appt.patient.email, "Suggested alternative appointment slots",
            f"""<div style="font-family:sans-serif;max-width:520px">
                  <h3>We've found some alternative times</h3>
                  <p>Since your original appointment was cancelled due to doctor leave, here are
                  the next available slots with Dr. {doctor.user.full_name}:</p>
                  <p><b>{alt_text}</b></p>
                  <p>Log in to the patient portal to rebook instantly.</p>
                </div>""",
            "leave_notice", appt.id,
        )
        summary.append({
            "appointment_id": appt.id,
            "patient_email": appt.patient.email,
            "original_slot": to_utc_iso(appt.slot_start),
            "suggested_alternatives": [to_utc_iso(s) for s in alternatives],
        })

    return summary


def _suggest_alternative_slots(db: Session, doctor: DoctorProfile, working_hours: dict,
                                after: datetime, count: int) -> list[datetime]:
    suggestions: list[datetime] = []
    day_cursor = after
    days_checked = 0
    while len(suggestions) < count and days_checked < 14:
        day_slots = slot_service.get_available_slots(db, doctor, day_cursor, working_hours)
        suggestions.extend(day_slots[: count - len(suggestions)])
        day_cursor += timedelta(days=1)
        days_checked += 1
    return suggestions[:count]
