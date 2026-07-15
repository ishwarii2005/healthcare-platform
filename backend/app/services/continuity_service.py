"""
USP: Continuity-of-care timeline.

Instead of treating every visit as a blank slate, we pull the patient's last few
CONFIRMED/COMPLETED appointments (chief complaint, diagnosis, prescriptions) and
feed a compact text summary into the pre-visit triage prompt. This lets the model
flag recurring or worsening patterns (e.g. a 3rd visit for the same headache in
six weeks) instead of just scoring the current form in isolation, and gives the
doctor a ready-made timeline instead of having to dig through past records.
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, SymptomForm, VisitNote


def get_patient_timeline(db: Session, patient_id: str, limit: int = 5) -> list[dict]:
    rows = (
        db.execute(
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED]),
            )
            .order_by(Appointment.slot_start.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    timeline = []
    for appt in rows:
        symptom = db.query(SymptomForm).filter(SymptomForm.appointment_id == appt.id).first()
        note = db.query(VisitNote).filter(VisitNote.appointment_id == appt.id).first()
        timeline.append({
            "date": appt.slot_start.strftime("%Y-%m-%d"),
            "chief_complaint": symptom.chief_complaint if symptom else None,
            "diagnosis": note.diagnosis if note else None,
            "prescription": json.loads(note.prescription_json) if (note and note.prescription_json) else [],
        })
    return timeline


def timeline_to_prompt_text(timeline: list[dict]) -> str | None:
    if not timeline:
        return None
    lines = []
    for entry in timeline:
        bits = [entry["date"]]
        if entry["chief_complaint"]:
            bits.append(f"complaint: {entry['chief_complaint']}")
        if entry["diagnosis"]:
            bits.append(f"diagnosis: {entry['diagnosis']}")
        if entry["prescription"]:
            meds = ", ".join(m.get("medication", "") for m in entry["prescription"])
            bits.append(f"prescribed: {meds}")
        lines.append(" | ".join(bits))
    return "\n".join(lines)
