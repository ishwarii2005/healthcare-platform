from sqlalchemy.orm import Session

from app.models import Appointment
from app.services import email_service, calendar_service


def notify_booking_confirmed(db: Session, appointment: Appointment) -> None:
    patient = appointment.patient
    doctor_user = appointment.doctor.user
    when = appointment.slot_start.strftime("%A, %d %b %Y at %I:%M %p")

    email_service.queue_email(
        db, patient.email, "Appointment Confirmed",
        email_service.booking_confirmation_html(patient.full_name, f"Dr. {doctor_user.full_name}", when, "patient"),
        "booking", appointment.id,
    )
    email_service.queue_email(
        db, doctor_user.email, "New Appointment Booked",
        email_service.booking_confirmation_html(doctor_user.full_name, patient.full_name, when, "doctor"),
        "booking", appointment.id,
    )

    event_id = calendar_service.create_event(
        db,
        summary=f"Appointment: {patient.full_name} with Dr. {doctor_user.full_name}",
        description=f"Booked via clinic platform. Appointment ID: {appointment.id}",
        start=appointment.slot_start,
        end=appointment.slot_end,
        attendee_emails=[patient.email, doctor_user.email],
    )
    if event_id:
        appointment.google_doctor_event_id = event_id
        appointment.google_patient_event_id = event_id
        db.commit()


def notify_cancellation(db: Session, appointment: Appointment, reason: str) -> None:
    patient = appointment.patient
    doctor_user = appointment.doctor.user
    when = appointment.slot_start.strftime("%A, %d %b %Y at %I:%M %p")

    email_service.queue_email(
        db, patient.email, "Appointment Cancelled",
        email_service.cancellation_html(patient.full_name, f"Dr. {doctor_user.full_name}", when, reason),
        "cancellation", appointment.id,
    )
    email_service.queue_email(
        db, doctor_user.email, "Appointment Cancelled",
        email_service.cancellation_html(doctor_user.full_name, patient.full_name, when, reason),
        "cancellation", appointment.id,
    )

    if appointment.google_doctor_event_id:
        calendar_service.delete_event(db, appointment.google_doctor_event_id)


def notify_reschedule(db: Session, appointment: Appointment) -> None:
    if appointment.google_doctor_event_id:
        calendar_service.update_event(
            db, appointment.google_doctor_event_id, appointment.slot_start, appointment.slot_end
        )
    when = appointment.slot_start.strftime("%A, %d %b %Y at %I:%M %p")
    email_service.queue_email(
        db, appointment.patient.email, "Appointment Rescheduled",
        email_service.reminder_html(appointment.patient.full_name, when, f"Dr. {appointment.doctor.user.full_name}"),
        "booking", appointment.id,
    )
