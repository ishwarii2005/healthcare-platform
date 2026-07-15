"""
Booking flow, in two steps:

  1. hold_slot()   -> creates Appointment(status=HELD) + a SlotLock row.
                      The SlotLock table has a UNIQUE(doctor_id, slot_start) constraint,
                      so if two patients hit "book" on the same slot at the same
                      millisecond, the database itself rejects the second INSERT with
                      an IntegrityError - there is no window for a race condition,
                      regardless of how many app server instances are running.
                      The hold expires after SLOT_HOLD_MINUTES; a background job
                      (jobs/hold_cleanup_job.py) sweeps expired holds so an abandoned
                      booking doesn't permanently block a slot.

  2. confirm_slot() -> called after the patient submits the symptom form. Clears the
                      lock's expiry (making it permanent), flips the appointment to
                      CONFIRMED, and is where emails + calendar events get created.

cancel_appointment() deletes the SlotLock row, immediately freeing the slot for
someone else, and is reused both for patient-initiated cancellation and for
leave-triggered cancellation (see leave_service.py).
"""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Appointment, AppointmentStatus, SlotLock, DoctorProfile


def hold_slot(db: Session, patient_id: str, doctor_id: str, slot_start: datetime) -> Appointment:
    doctor = db.get(DoctorProfile, doctor_id)
    if not doctor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")

    slot_end = slot_start + timedelta(minutes=doctor.slot_duration_minutes)

    # Sweep this doctor's expired holds first so a genuinely free slot isn't rejected.
    _release_expired_holds(db, doctor_id)

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_start=slot_start,
        slot_end=slot_end,
        status=AppointmentStatus.HELD,
    )
    db.add(appointment)
    db.flush()  # get appointment.id without committing yet

    lock = SlotLock(
        doctor_id=doctor_id,
        slot_start=slot_start,
        appointment_id=appointment.id,
        expires_at=datetime.utcnow() + timedelta(minutes=settings.SLOT_HOLD_MINUTES),
    )
    db.add(lock)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This slot was just taken by another patient. Please pick a different time.",
        )

    db.refresh(appointment)
    return appointment


def confirm_slot(db: Session, appointment: Appointment) -> Appointment:
    lock = db.query(SlotLock).filter(SlotLock.appointment_id == appointment.id).first()
    if lock:
        lock.expires_at = None  # permanent now
    appointment.status = AppointmentStatus.CONFIRMED
    db.commit()
    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, appointment: Appointment, by_leave: bool = False) -> Appointment:
    lock = db.query(SlotLock).filter(SlotLock.appointment_id == appointment.id).first()
    if lock:
        db.delete(lock)
    appointment.status = AppointmentStatus.CANCELLED_BY_LEAVE if by_leave else AppointmentStatus.CANCELLED
    db.commit()
    db.refresh(appointment)
    return appointment


def _release_expired_holds(db: Session, doctor_id: str) -> None:
    now = datetime.utcnow()
    expired_locks = (
        db.query(SlotLock)
        .filter(SlotLock.doctor_id == doctor_id, SlotLock.expires_at.isnot(None), SlotLock.expires_at < now)
        .all()
    )
    for lock in expired_locks:
        appt = db.get(Appointment, lock.appointment_id)
        if appt and appt.status == AppointmentStatus.HELD:
            appt.status = AppointmentStatus.CANCELLED
        db.delete(lock)
    if expired_locks:
        db.commit()


def get_available_slots(db: Session, doctor: DoctorProfile, day: datetime, working_hours: dict) -> list[datetime]:
    """Generate candidate slots for a given day from working hours, minus taken ones."""
    weekday_key = day.strftime("%a").lower()[:3]  # mon, tue, ...
    hours = working_hours.get(weekday_key)
    if not hours:
        return []
    start_h, start_m = map(int, hours[0].split(":"))
    end_h, end_m = map(int, hours[1].split(":"))
    cursor = day.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    day_end = day.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    _release_expired_holds(db, doctor.id)
    taken = {
        row.slot_start
        for row in db.query(SlotLock.slot_start).filter(SlotLock.doctor_id == doctor.id).all()
    }

    slots = []
    while cursor + timedelta(minutes=doctor.slot_duration_minutes) <= day_end:
        if cursor not in taken and cursor > datetime.utcnow():
            slots.append(cursor)
        cursor += timedelta(minutes=doctor.slot_duration_minutes)
    return slots
