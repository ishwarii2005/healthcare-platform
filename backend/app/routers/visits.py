import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import User, Role, Appointment, AppointmentStatus, VisitNote, MedicationReminder
from app.schemas import VisitNoteRequest, VisitNoteOut
from app.services.llm_service import generate_post_visit_summary

router = APIRouter(prefix="/api/appointments", tags=["visits"])


@router.post("/{appointment_id}/visit-note", response_model=VisitNoteOut)
def submit_visit_note(appointment_id: str, payload: VisitNoteRequest,
                       user: User = Depends(require_role(Role.DOCTOR)), db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if not appt or appt.doctor.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")

    result = generate_post_visit_summary(
        payload.clinical_notes, payload.diagnosis, payload.prescription, payload.follow_up_days
    )

    note = VisitNote(
        appointment_id=appt.id,
        clinical_notes=payload.clinical_notes,
        diagnosis=payload.diagnosis,
        prescription_json=json.dumps(payload.prescription),
        follow_up_days=payload.follow_up_days,
        patient_summary=result["summary"],
        llm_status=result["llm_status"],
    )
    db.add(note)
    appt.status = AppointmentStatus.COMPLETED
    db.flush()

    # Schedule medication reminders from the structured prescription
    today = date.today()
    for med in payload.prescription:
        duration = med.get("duration_days") or 5
        for t in med.get("times", []):
            db.add(MedicationReminder(
                visit_note_id=note.id, patient_id=appt.patient_id,
                medication=med.get("medication", "Medication"), dosage=med.get("dosage", ""),
                time_of_day=t, start_date=today, end_date=today + timedelta(days=duration),
            ))

    db.commit()
    db.refresh(note)

    return VisitNoteOut(
        clinical_notes=note.clinical_notes, diagnosis=note.diagnosis,
        prescription=json.loads(note.prescription_json or "[]"),
        follow_up_days=note.follow_up_days, patient_summary=note.patient_summary,
        llm_status=note.llm_status,
    )


@router.get("/{appointment_id}/visit-note", response_model=VisitNoteOut)
def get_visit_note(appointment_id: str, user: User = Depends(require_role(Role.PATIENT, Role.DOCTOR, Role.ADMIN)),
                    db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if user.role == Role.PATIENT and appt.patient_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your appointment")
    if user.role == Role.DOCTOR and appt.doctor.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your appointment")
    if not appt.visit_note:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No visit note yet")

    note = appt.visit_note
    return VisitNoteOut(
        clinical_notes=note.clinical_notes, diagnosis=note.diagnosis,
        prescription=json.loads(note.prescription_json or "[]"),
        follow_up_days=note.follow_up_days, patient_summary=note.patient_summary,
        llm_status=note.llm_status,
    )


@router.get("/timeline/mine")
def my_timeline(user: User = Depends(require_role(Role.PATIENT)), db: Session = Depends(get_db)):
    from app.services.continuity_service import get_patient_timeline
    return get_patient_timeline(db, user.id, limit=10)
