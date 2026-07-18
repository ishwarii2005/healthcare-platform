from datetime import datetime, date
from typing import Optional, Annotated

from pydantic import BaseModel, EmailStr, Field, PlainSerializer

from app.models import Role, AppointmentStatus, Urgency
from app.utils.dates import to_utc_iso

# Use this instead of a bare `datetime` on any field returned to the frontend.
# See app/utils/dates.py - it stamps naive UTC datetimes with an explicit UTC
# offset on the way out, so the browser never misreads them as local time.
UTCDateTime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str)]


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str
    phone: Optional[str] = None
    role: Role = Role.PATIENT  # admin restricts doctor creation to its own endpoint


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    user_id: str
    full_name: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    phone: Optional[str] = None
    role: Role

    class Config:
        from_attributes = True


# ---------- Doctor / Admin ----------
class DoctorCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str
    phone: Optional[str] = None
    specialization: str
    bio: Optional[str] = None
    slot_duration_minutes: int = 15
    working_hours: dict  # {"mon": ["09:00","17:00"], ...}


class DoctorUpdateRequest(BaseModel):
    specialization: Optional[str] = None
    bio: Optional[str] = None
    slot_duration_minutes: Optional[int] = None
    working_hours: Optional[dict] = None


class DoctorOut(BaseModel):
    id: str
    user_id: str
    full_name: str
    email: str
    specialization: str
    bio: Optional[str] = None
    slot_duration_minutes: int
    working_hours: dict
    is_active: bool = True


class LeaveCreateRequest(BaseModel):
    leave_date: date
    reason: Optional[str] = None


# ---------- Appointments ----------
class SlotHoldRequest(BaseModel):
    doctor_id: str
    slot_start: datetime


class SlotHoldResponse(BaseModel):
    appointment_id: str
    slot_start: UTCDateTime
    slot_end: UTCDateTime
    hold_expires_at: UTCDateTime


class SymptomFormRequest(BaseModel):
    raw_symptoms: str
    duration_days: Optional[int] = None
    severity_self_rated: Optional[int] = Field(default=None, ge=1, le=10)


class SymptomFormOut(BaseModel):
    urgency: Urgency
    chief_complaint: Optional[str]
    suggested_questions: list[str] = []
    llm_status: str


class AppointmentOut(BaseModel):
    id: str
    patient_id: str
    patient_name: Optional[str] = None
    doctor_id: str
    doctor_name: Optional[str] = None
    specialization: Optional[str] = None
    slot_start: UTCDateTime
    slot_end: UTCDateTime
    status: AppointmentStatus
    urgency: Optional[Urgency] = None
    chief_complaint: Optional[str] = None


class VisitNoteRequest(BaseModel):
    clinical_notes: str
    diagnosis: Optional[str] = None
    prescription: list[dict] = []
    # each: {"medication","dosage","frequency_per_day","times":["08:00"],"duration_days","notes"}
    follow_up_days: Optional[int] = None


class VisitNoteOut(BaseModel):
    clinical_notes: str
    diagnosis: Optional[str]
    prescription: list[dict]
    follow_up_days: Optional[int]
    patient_summary: Optional[str]
    llm_status: str


# ---------- Conversational pre-booking intake ----------
class IntakeMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class IntakeChatRequest(BaseModel):
    history: list[IntakeMessage]


class IntakeChatResponse(BaseModel):
    status: str  # "asking" | "recommendation"
    message: str
    specialization: Optional[str] = None
    reasoning: Optional[str] = None
    urgency_hint: Optional[str] = None
    consolidated_summary: Optional[str] = None
    llm_status: str
