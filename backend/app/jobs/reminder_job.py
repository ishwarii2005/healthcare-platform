"""
Runs every REMINDER_JOB_INTERVAL_MINUTES. For each active MedicationReminder whose
time_of_day matches the current hour:minute window and hasn't already been sent
today, queues a reminder email. Also sends appointment reminders ~24h ahead.
"""
import logging
from datetime import datetime, date, timedelta

from app.database import SessionLocal
from app.models import MedicationReminder, Appointment, AppointmentStatus
from app.services import email_service

logger = logging.getLogger("reminder_job")


def run_medication_reminders():
    db = SessionLocal()
    try:
        now = datetime.now()
        today = date.today()
        current_hm = now.strftime("%H:%M")

        due = db.query(MedicationReminder).filter(
            MedicationReminder.active == True,  # noqa: E712
            MedicationReminder.start_date <= today,
            MedicationReminder.end_date >= today,
            MedicationReminder.time_of_day == current_hm,
        ).all()

        for reminder in due:
            if reminder.last_sent_date == today:
                continue
            patient = reminder.patient  # lazy load ok within session
            email_service.queue_email(
                db, patient.email, "Medication Reminder",
                email_service.medication_reminder_html(
                    patient.full_name, reminder.medication, reminder.dosage or "", reminder.time_of_day
                ),
                "reminder",
            )
            reminder.last_sent_date = today
        db.commit()
    except Exception:
        logger.exception("Medication reminder job failed")
    finally:
        db.close()


def run_appointment_reminders():
    db = SessionLocal()
    try:
        window_start = datetime.utcnow() + timedelta(hours=23)
        window_end = datetime.utcnow() + timedelta(hours=25)
        upcoming = db.query(Appointment).filter(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.slot_start >= window_start,
            Appointment.slot_start < window_end,
        ).all()
        for appt in upcoming:
            when = appt.slot_start.strftime("%A, %d %b %Y at %I:%M %p")
            email_service.queue_email(
                db, appt.patient.email, "Appointment Reminder - Tomorrow",
                email_service.reminder_html(appt.patient.full_name, when, f"Dr. {appt.doctor.user.full_name}"),
                "reminder", appt.id,
            )
        db.commit()
    except Exception:
        logger.exception("Appointment reminder job failed")
    finally:
        db.close()
