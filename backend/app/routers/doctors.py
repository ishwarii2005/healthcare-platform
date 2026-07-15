import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DoctorProfile
from app.schemas import DoctorOut
from app.services.slot_service import get_available_slots

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


def _to_doctor_out(doc: DoctorProfile) -> DoctorOut:
    return DoctorOut(
        id=doc.id, user_id=doc.user_id, full_name=doc.user.full_name, email=doc.user.email,
        specialization=doc.specialization, bio=doc.bio, slot_duration_minutes=doc.slot_duration_minutes,
        working_hours=json.loads(doc.working_hours_json or "{}"),
    )


@router.get("", response_model=list[DoctorOut])
def search_doctors(specialization: str | None = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(DoctorProfile)
    if specialization:
        q = q.filter(DoctorProfile.specialization.ilike(f"%{specialization}%"))
    return [_to_doctor_out(d) for d in q.all()]


@router.get("/specializations")
def list_specializations(db: Session = Depends(get_db)):
    rows = db.query(DoctorProfile.specialization).distinct().all()
    return sorted({r[0] for r in rows})


@router.get("/{doctor_id}/availability")
def availability(doctor_id: str, day: str = Query(..., description="YYYY-MM-DD"), db: Session = Depends(get_db)):
    doctor = db.get(DoctorProfile, doctor_id)
    if not doctor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found")
    try:
        day_dt = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "day must be YYYY-MM-DD")

    from app.models import DoctorLeave
    if db.query(DoctorLeave).filter(
        DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == day_dt.date()
    ).first():
        return {"day": day, "on_leave": True, "slots": []}

    working_hours = json.loads(doctor.working_hours_json or "{}")
    slots = get_available_slots(db, doctor, day_dt, working_hours)
    from app.utils.dates import to_utc_iso
    return {"day": day, "on_leave": False, "slots": [to_utc_iso(s) for s in slots]}
