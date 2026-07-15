import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.jobs.reminder_job import run_medication_reminders, run_appointment_reminders
from app.jobs.maintenance_jobs import run_email_retries, run_hold_cleanup
from app.routers import auth, admin, doctors, appointments, visits, calendar as calendar_router, intake

logging.basicConfig(level=logging.INFO)

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    scheduler.add_job(run_medication_reminders, "interval", minutes=settings.REMINDER_JOB_INTERVAL_MINUTES,
                       id="medication_reminders")
    scheduler.add_job(run_appointment_reminders, "interval", hours=1, id="appointment_reminders")
    scheduler.add_job(run_email_retries, "interval", minutes=settings.EMAIL_RETRY_INTERVAL_MINUTES,
                       id="email_retries")
    scheduler.add_job(run_hold_cleanup, "interval", minutes=1, id="hold_cleanup")
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="Clinic Appointment & Follow-up Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(visits.router)
app.include_router(calendar_router.router)
app.include_router(intake.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/admin/bootstrap")
def bootstrap_admin(email: str, password: str, full_name: str):
    """
    One-time convenience endpoint to create the very first admin account, since the
    normal /api/admin/* routes require an admin token to create anyone. Disable or
    remove this in production once your admin account exists (see README).
    """
    from app.database import SessionLocal
    from app.models import User, Role
    from app.auth import hash_password, create_access_token

    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == Role.ADMIN).first():
            return {"error": "An admin already exists. This endpoint is now disabled."}
        user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=Role.ADMIN)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": user.id, "role": user.role.value})
        return {"access_token": token, "user_id": user.id}
    finally:
        db.close()
