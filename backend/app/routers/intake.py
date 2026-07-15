from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import User, Role, DoctorProfile
from app.schemas import IntakeChatRequest, IntakeChatResponse
from app.services.llm_service import generate_intake_turn

router = APIRouter(prefix="/api/intake", tags=["intake"])


@router.post("/chat", response_model=IntakeChatResponse)
def intake_chat(payload: IntakeChatRequest, user: User = Depends(require_role(Role.PATIENT)),
                 db: Session = Depends(get_db)):
    specializations = sorted({row[0] for row in db.query(DoctorProfile.specialization).distinct().all()})
    history = [m.model_dump() for m in payload.history]
    result = generate_intake_turn(history, specializations)
    return IntakeChatResponse(**result)
