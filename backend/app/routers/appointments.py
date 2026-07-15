import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_role, get_current_user
from app.database import get_db
from app.models import (
    User, Role, Appointment, AppointmentStatus, SymptomForm, DoctorProfile, Urgency
)
from app.schemas import (
    SlotHoldRequest, SlotHoldResponse, SymptomFormRequest, SymptomFormOut, AppointmentOut
)
from app.services import slot_service, notification_service, continuity_service
from app.services.llm_service import generate_triage_summary

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

_URGENCY_SORT_ORDER = {Urgency.HIGH: 0, Urgency.MEDIUM: 1, Urgency.LOW: 2, Urgency.UNKNOWN: 3}


def _to_out(appt: Appointment) -> AppointmentOut:
    symptom = appt.symptom_form
    return AppointmentOut(
        id=appt.id, patient_id=appt.patient_id, patient_name=appt.patient.full_name,
        doctor_id=appt.doctor_id, doctor_name=appt.doctor.user.full_name,
        specialization=appt.doctor.specialization,
        slot_start=appt.slot_start, slot_end=appt.slot_end, status=appt.status,
        urgency=symptom.urgency if symptom else None,
        chief_complaint=symptom.chief_complaint if symptom else None,
    )


@router.post("/hold", response_model=SlotHoldResponse)
def hold_slot(payload: SlotHoldRequest, user: User = Depends(require_role(Role.PATIENT)),
              db: Session = Depends(get_db)):
    appt = slot_service.hold_slot(db, user.id, payload.doctor_id, payload.slot_start)
    lock = appt.id  # appointment carries its own hold info via SlotLock, fetch expiry
    from app.models import SlotLock
    lock_row = db.query(SlotLock).filter(SlotLock.appointment_id == appt.id).first()
    return SlotHoldResponse(
        appointment_id=appt.id, slot_start=appt.slot_start, slot_end=appt.slot_end,
        hold_expires_at=lock_row.expires_at,
    )


@router.post("/{appointment_id}/symptoms", response_model=SymptomFormOut)
def submit_symptoms(appointment_id: str, payload: SymptomFormRequest,
                     user: User = Depends(require_role(Role.PATIENT)), db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if not appt or appt.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if appt.status != AppointmentStatus.HELD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Appointment is not awaiting symptoms")

    # USP: continuity-of-care - pull this patient's history into the triage prompt
    timeline = continuity_service.get_patient_timeline(db, user.id)
    prior_text = continuity_service.timeline_to_prompt_text(timeline)

    result = generate_triage_summary(
        payload.raw_symptoms, payload.duration_days, payload.severity_self_rated, prior_text
    )

    symptom = SymptomForm(
        appointment_id=appt.id,
        raw_symptoms=payload.raw_symptoms,
        duration_days=payload.duration_days,
        severity_self_rated=payload.severity_self_rated,
        urgency=Urgency(result["urgency"]),
        chief_complaint=result.get("chief_complaint"),
        suggested_questions_json=json.dumps(result.get("suggested_questions", [])),
        llm_status=result["llm_status"],
        llm_raw_response=result.get("llm_raw_response"),
    )
    db.add(symptom)

    appt = slot_service.confirm_slot(db, appt)
    notification_service.notify_booking_confirmed(db, appt)
    db.commit()
    db.refresh(symptom)

    return SymptomFormOut(
        urgency=symptom.urgency, chief_complaint=symptom.chief_complaint,
        suggested_questions=json.loads(symptom.suggested_questions_json or "[]"),
        llm_status=symptom.llm_status,
    )


@router.get("/mine", response_model=list[AppointmentOut])
def my_appointments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.PATIENT:
        rows = db.query(Appointment).filter(Appointment.patient_id == user.id).order_by(
            Appointment.slot_start.desc()
        ).all()
    elif user.role == Role.DOCTOR:
        doctor = db.query(DoctorProfile).filter(DoctorProfile.user_id == user.id).first()
        rows = db.query(Appointment).filter(Appointment.doctor_id == doctor.id).all() if doctor else []
    else:
        rows = db.query(Appointment).order_by(Appointment.slot_start.desc()).limit(200).all()
    return [_to_out(r) for r in rows]


@router.get("/queue/today", response_model=list[AppointmentOut])
def doctor_queue_today(user: User = Depends(require_role(Role.DOCTOR)), db: Session = Depends(get_db)):
    """
    USP: urgency-triage queue. Today's confirmed appointments for the logged-in doctor,
    sorted High -> Medium -> Low urgency (ties broken by original slot time), so the
    doctor's dashboard visually surfaces the most urgent patients first rather than
    strictly first-come-first-served.
    """
    from datetime import datetime, timedelta
    doctor = db.query(DoctorProfile).filter(DoctorProfile.user_id == user.id).first()
    if not doctor:
        return []
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    rows = db.query(Appointment).filter(
        Appointment.doctor_id == doctor.id,
        Appointment.status == AppointmentStatus.CONFIRMED,
        Appointment.slot_start >= today_start,
        Appointment.slot_start < today_end,
    ).all()

    rows.sort(key=lambda a: (
        _URGENCY_SORT_ORDER.get(a.symptom_form.urgency if a.symptom_form else Urgency.UNKNOWN, 3),
        a.slot_start,
    ))
    return [_to_out(r) for r in rows]


@router.post("/{appointment_id}/cancel")
def cancel(appointment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    is_owner_patient = user.role == Role.PATIENT and appt.patient_id == user.id
    is_owner_doctor = user.role == Role.DOCTOR and appt.doctor.user_id == user.id
    if not (is_owner_patient or is_owner_doctor or user.role == Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your appointment")

    appt = slot_service.cancel_appointment(db, appt)
    notification_service.notify_cancellation(db, appt, reason="Cancelled by " + user.role.value)
    return {"status": "cancelled"}
