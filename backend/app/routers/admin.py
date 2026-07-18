import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_role, hash_password
from app.database import get_db
from app.models import User, Role, DoctorProfile, DoctorLeave, EmailOutbox, EmailStatus
from app.schemas import DoctorCreateRequest, DoctorUpdateRequest, DoctorOut, LeaveCreateRequest
from app.services import leave_service, email_service

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_role(Role.ADMIN))])


def _to_doctor_out(doc: DoctorProfile) -> DoctorOut:
    return DoctorOut(
        id=doc.id, user_id=doc.user_id, full_name=doc.user.full_name, email=doc.user.email,
        specialization=doc.specialization, bio=doc.bio, slot_duration_minutes=doc.slot_duration_minutes,
        working_hours=json.loads(doc.working_hours_json or "{}"), is_active=doc.user.is_active,
    )


@router.post("/doctors", response_model=DoctorOut)
def create_doctor(payload: DoctorCreateRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    user = User(
        email=payload.email, password_hash=hash_password(payload.password),
        full_name=payload.full_name, phone=payload.phone, role=Role.DOCTOR,
    )
    db.add(user)
    db.flush()

    profile = DoctorProfile(
        user_id=user.id, specialization=payload.specialization, bio=payload.bio,
        slot_duration_minutes=payload.slot_duration_minutes,
        working_hours_json=json.dumps(payload.working_hours),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _to_doctor_out(profile)


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db)):
    return [_to_doctor_out(d) for d in db.query(DoctorProfile).all()]


@router.patch("/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(doctor_id: str, payload: DoctorUpdateRequest, db: Session = Depends(get_db)):
    doc = db.get(DoctorProfile, doctor_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    if payload.specialization is not None:
        doc.specialization = payload.specialization
    if payload.bio is not None:
        doc.bio = payload.bio
    if payload.slot_duration_minutes is not None:
        doc.slot_duration_minutes = payload.slot_duration_minutes
    if payload.working_hours is not None:
        doc.working_hours_json = json.dumps(payload.working_hours)
    db.commit()
    db.refresh(doc)
    return _to_doctor_out(doc)


@router.post("/doctors/{doctor_id}/deactivate", response_model=DoctorOut)
def deactivate_doctor(doctor_id: str, db: Session = Depends(get_db)):
    """
    Soft delete: disables the doctor's login and hides them from patient search,
    without touching existing appointments/visit history/prescriptions - a hard
    delete would either orphan or cascade-destroy that data. This does NOT cancel
    any appointments the doctor already has; use leave-management first for that.
    """
    doc = db.get(DoctorProfile, doctor_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    doc.user.is_active = False
    db.commit()
    db.refresh(doc)
    return _to_doctor_out(doc)


@router.post("/doctors/{doctor_id}/activate", response_model=DoctorOut)
def activate_doctor(doctor_id: str, db: Session = Depends(get_db)):
    doc = db.get(DoctorProfile, doctor_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    doc.user.is_active = True
    db.commit()
    db.refresh(doc)
    return _to_doctor_out(doc)


@router.post("/doctors/{doctor_id}/leave")
def add_leave(doctor_id: str, payload: LeaveCreateRequest, db: Session = Depends(get_db)):
    doc = db.get(DoctorProfile, doctor_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    if db.query(DoctorLeave).filter(
        DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == payload.leave_date
    ).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Leave already recorded for this date")

    leave = DoctorLeave(doctor_id=doctor_id, leave_date=payload.leave_date, reason=payload.reason)
    db.add(leave)
    db.commit()

    affected = leave_service.handle_leave_conflicts(db, doc, payload.leave_date, payload.reason or "")
    return {"leave_date": str(payload.leave_date), "affected_appointments": affected}


@router.get("/doctors/{doctor_id}/leave")
def list_leave(doctor_id: str, db: Session = Depends(get_db)):
    rows = db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id).all()
    return [{"leave_date": str(r.leave_date), "reason": r.reason} for r in rows]


@router.get("/emails/failed")
def failed_emails(db: Session = Depends(get_db)):
    """Visibility into notification reliability - failed/dead emails an admin may need to resend manually."""
    rows = db.query(EmailOutbox).filter(
        EmailOutbox.status.in_([EmailStatus.FAILED, EmailStatus.DEAD])
    ).order_by(EmailOutbox.updated_at.desc()).all()
    return [
        {"id": r.id, "to": r.to_email, "subject": r.subject, "category": r.category,
         "attempts": r.attempts, "status": r.status.value, "last_error": r.last_error}
        for r in rows
    ]


@router.post("/emails/{email_id}/retry")
def retry_email(email_id: str, db: Session = Depends(get_db)):
    row = db.get(EmailOutbox, email_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row.status = EmailStatus.PENDING
    db.commit()
    ok = email_service.attempt_send(db, row)
    return {"sent": ok}
