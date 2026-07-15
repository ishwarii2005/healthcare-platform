import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum, UniqueConstraint, Date
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class AppointmentStatus(str, enum.Enum):
    HELD = "held"                  # temporary hold while patient fills symptom form
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    CANCELLED_BY_LEAVE = "cancelled_by_leave"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class Urgency(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    UNKNOWN = "Unknown"


class EmailStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    doctor_profile: Mapped["DoctorProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class DoctorProfile(Base):
    """Created/managed by admin. 1:1 with a User(role=doctor)."""
    __tablename__ = "doctor_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), unique=True, nullable=False)
    specialization: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bio: Mapped[str] = mapped_column(Text, nullable=True)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    # working_hours JSON, e.g. {"mon": ["09:00","17:00"], "tue": ["09:00","17:00"], ...}
    working_hours_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="doctor_profile")
    leaves: Mapped[list["DoctorLeave"]] = relationship(back_populates="doctor", cascade="all, delete-orphan")


class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    doctor_id: Mapped[str] = mapped_column(String, ForeignKey("doctor_profiles.id"), nullable=False)
    leave_date: Mapped[Date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    doctor: Mapped["DoctorProfile"] = relationship(back_populates="leaves")

    __table_args__ = (UniqueConstraint("doctor_id", "leave_date", name="uq_doctor_leave_date"),)


class SlotLock(Base):
    """
    The single source of truth for double-booking prevention.
    Exactly one active row can exist per (doctor_id, slot_start) thanks to the
    unique constraint below - the DB itself rejects a concurrent second booking
    attempt, regardless of app-server race conditions. Row is deleted when the
    hold expires or the appointment is cancelled, freeing the slot again.
    """
    __tablename__ = "slot_locks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    doctor_id: Mapped[str] = mapped_column(String, ForeignKey("doctor_profiles.id"), nullable=False)
    slot_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String, ForeignKey("appointments.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # null once CONFIRMED

    __table_args__ = (UniqueConstraint("doctor_id", "slot_start", name="uq_doctor_slot"),)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String, ForeignKey("doctor_profiles.id"), nullable=False)
    slot_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    slot_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(Enum(AppointmentStatus), default=AppointmentStatus.HELD)

    google_doctor_event_id: Mapped[str] = mapped_column(String, nullable=True)
    google_patient_event_id: Mapped[str] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient: Mapped["User"] = relationship(foreign_keys=[patient_id])
    doctor: Mapped["DoctorProfile"] = relationship()
    symptom_form: Mapped["SymptomForm"] = relationship(back_populates="appointment", uselist=False,
                                                         cascade="all, delete-orphan")
    visit_note: Mapped["VisitNote"] = relationship(back_populates="appointment", uselist=False,
                                                     cascade="all, delete-orphan")


class SymptomForm(Base):
    """Pre-visit symptom form + AI triage summary (USP: urgency-triage queue)."""
    __tablename__ = "symptom_forms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    appointment_id: Mapped[str] = mapped_column(String, ForeignKey("appointments.id"), unique=True, nullable=False)
    raw_symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=True)
    severity_self_rated: Mapped[int] = mapped_column(Integer, nullable=True)  # 1-10 patient self rating

    # AI output
    urgency: Mapped[Urgency] = mapped_column(Enum(Urgency), default=Urgency.UNKNOWN)
    chief_complaint: Mapped[str] = mapped_column(String, nullable=True)
    suggested_questions_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON list[str]
    llm_status: Mapped[str] = mapped_column(String, default="pending")  # pending|ok|fallback|failed
    llm_raw_response: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    appointment: Mapped["Appointment"] = relationship(back_populates="symptom_form")


class VisitNote(Base):
    """Doctor's post-visit clinical notes + AI patient-friendly summary."""
    __tablename__ = "visit_notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    appointment_id: Mapped[str] = mapped_column(String, ForeignKey("appointments.id"), unique=True, nullable=False)
    clinical_notes: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(String, nullable=True)
    prescription_json: Mapped[str] = mapped_column(Text, nullable=True)
    # [{"medication": "Amoxicillin", "dosage": "500mg", "frequency_per_day": 3,
    #   "times": ["08:00","14:00","20:00"], "duration_days": 5, "notes": "after food"}]
    follow_up_days: Mapped[int] = mapped_column(Integer, nullable=True)

    # AI output
    patient_summary: Mapped[str] = mapped_column(Text, nullable=True)
    llm_status: Mapped[str] = mapped_column(String, default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    appointment: Mapped["Appointment"] = relationship(back_populates="visit_note")


class MedicationReminder(Base):
    __tablename__ = "medication_reminders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    visit_note_id: Mapped[str] = mapped_column(String, ForeignKey("visit_notes.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    medication: Mapped[str] = mapped_column(String, nullable=False)
    dosage: Mapped[str] = mapped_column(String, nullable=True)
    time_of_day: Mapped[str] = mapped_column(String, nullable=False)  # "08:00"
    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Date] = mapped_column(Date, nullable=False)
    last_sent_date: Mapped[Date] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CalendarCredential(Base):
    """
    Single-row table holding the clinic's Google OAuth refresh token, obtained once
    by the admin via the /api/calendar/oauth/* flow. All appointment events are
    created on this one clinic calendar with doctor + patient added as attendees,
    so individual patients/doctors never need to do their own Google OAuth.
    """
    __tablename__ = "calendar_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    connected_by_admin_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailOutbox(Base):
    """Every outbound email goes through here so retries/failures are tracked, not silently dropped."""
    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    to_email: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # booking|reminder|cancellation|leave_notice
    status: Mapped[EmailStatus] = mapped_column(Enum(EmailStatus), default=EmailStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    related_appointment_id: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
