# City Care — Healthcare Appointment & Follow-up Platform

A clinic appointment platform with separate patient/doctor/admin portals, built
around two things generic booking forms don't do:

- **AI urgency-triage queue** — the pre-visit symptom form doesn't just get filed
  away, it drives an AI-generated urgency score (Low/Medium/High) that reorders the
  doctor's daily queue so the most urgent patients surface first, not just whoever
  booked earliest.
- **Continuity-of-care timeline** — every patient's last few visits (complaints,
  diagnoses, prescriptions) are fed back into the *next* pre-visit AI summary, so
  the system can flag "3rd visit for headaches in 6 weeks" instead of treating each
  visit as a blank slate.
- **Conversational pre-booking intake** — before picking a doctor, patients can chat
  with an AI assistant about why they're visiting. It asks up to 3 focused follow-up
  questions, then recommends a specialization (validated against the clinic's actual
  roster) and hands the consolidated summary forward to prefill the booking flow.

Everything else (leave-triggered rebooking suggestions, email outbox with retries,
Google Calendar sync) is built to support those two flows without ever blocking a
booking if a third-party service (LLM, SMTP, Calendar) is slow or down.

## Live deployment

| | |
|---|---|
| **App** | https://healthcare-platform-xi.vercel.app |
| **Backend API** | https://healthcare-platform-ra42.onrender.com |
| **API docs** | https://healthcare-platform-ra42.onrender.com/docs |

Frontend is on Vercel, backend + Postgres (Neon) on Render. Two things to know
before judging responsiveness:
- The backend is on Render's **free tier**, which spins down after 15 minutes of
  inactivity. The first request after idle time takes ~30-60 seconds to wake up -
  this is expected free-tier behavior, not a bug.
- To log in as admin, use the account created via the one-time bootstrap endpoint
  (see "First-run bootstrap" below) - there's no default admin/password shipped
  with the code for security reasons.

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python), SQLAlchemy, APScheduler for background jobs |
| Frontend | React (Vite), plain CSS design tokens, `react-router-dom` |
| Database | SQLite for local dev, Postgres (any free host — Render/Neon/Supabase) for deployment |
| LLM | [Groq](https://console.groq.com) free tier, `llama-3.1-8b-instant`, OpenAI-compatible |
| Email | Any SMTP provider (Gmail app password, Brevo free tier, Mailgun sandbox) |
| Calendar | Google Calendar API, OAuth 2.0, single clinic-account model |

> **Why not Ollama?** Ollama needs a persistent server with real RAM/CPU, which
> free serverless hosts (Vercel, Render's free web-service tier) can't provide.
> The code is written against an OpenAI-compatible chat-completions call
> (`app/services/llm_service.py`), so swapping back to a local Ollama server for
> offline development is a one-line change to `GROQ_API_KEY`/`GROQ_MODEL` plus
> pointing the `Groq` client's `base_url` at `http://localhost:11434/v1`.

## Project structure

```
backend/
  app/
    main.py              FastAPI app, CORS, scheduler wiring
    config.py             Settings from .env
    models.py              SQLAlchemy models (see schema below)
    schemas.py             Pydantic request/response models
    auth.py                 JWT + role-based dependencies
    routers/                auth, admin, doctors, appointments, visits, calendar
    services/
      llm_service.py         Groq calls + prompts + rule-based fallback
      email_service.py       Outbox pattern, SMTP send
      calendar_service.py    Google Calendar OAuth + event CRUD
      slot_service.py        Double-booking prevention (see system design doc)
      leave_service.py       Leave-conflict cancellation + rebooking suggestions
      continuity_service.py  Builds patient visit-history text for the LLM prompt
      notification_service.py Combines email + calendar for booking/cancel events
    jobs/                   APScheduler background jobs (reminders, retries, hold cleanup)
frontend/
  src/
    pages/{patient,doctor,admin}/   One dashboard per role
    components/                     UrgencyBadge, PortalShell, ProtectedRoute
    context/AuthContext.jsx         JWT storage + login/register
    api/client.js                   Axios instance with auth interceptor
docs/
  SYSTEM_DESIGN.md            The 800-word write-up (double-booking, leave, holds, notifications)
  GOOGLE_CALENDAR_SETUP.md    Click-by-click OAuth setup
```

## Local setup

**Requirements:** Python 3.11+, Node 18+.

```bash
# 1. Backend
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env - at minimum set GROQ_API_KEY (free at https://console.groq.com/keys)
# leave EMAIL_DRY_RUN=true and DATABASE_URL as-is to run fully locally with no other accounts
uvicorn app.main:app --reload
# -> http://localhost:8000, interactive API docs at http://localhost:8000/docs

# 2. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000
npm run dev
# -> http://localhost:5173
```

**Or with Docker Compose** (backend only, still needs `frontend` run separately):
```bash
cp backend/.env.example backend/.env   # edit as above
docker compose up --build
```

### First-run bootstrap

The very first admin account can't be created through the normal admin-only
endpoints (chicken-and-egg), so there's a one-time bootstrap endpoint:

```bash
curl -X POST "http://localhost:8000/api/admin/bootstrap?email=admin@clinic.com&password=changeme123&full_name=Admin" 
```

It self-disables once an admin exists (returns an error on a second call). Log in
with those credentials at `/login`, then use **Admin → Doctors** to create doctor
accounts (patients self-register from `/register`).

## API overview

Full interactive docs (request/response schemas, try-it-out) are auto-generated by
FastAPI at **`/docs`** once the backend is running. Summary:

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/auth/register` | Public | Patient self-registration |
| `POST /api/auth/login` | Public | Returns JWT (form-encoded `username`/`password`) |
| `POST /api/admin/doctors` | Admin | Create doctor profile + user account |
| `PATCH /api/admin/doctors/{id}` | Admin | Update specialization/hours/slot length/bio |
| `POST /api/admin/doctors/{id}/deactivate` / `/activate` | Admin | Soft delete - hides from patient search & blocks new bookings, keeps history |
| `POST /api/admin/doctors/{id}/leave` | Admin | Mark leave day → auto-cancels + notifies + suggests rebooking |
| `GET /api/admin/emails/failed` / `POST .../retry` | Admin | Notification reliability dashboard |
| `POST /api/intake/chat` | Patient | Multi-turn symptom chat → specialization recommendation |
| `GET /api/doctors` | Any | Search by `?specialization=` (active doctors only) |
| `GET /api/doctors/{id}/availability?day=YYYY-MM-DD` | Any | Open slots for a day |
| `POST /api/appointments/hold` | Patient | Step 1 of booking - reserves a slot |
| `POST /api/appointments/{id}/symptoms` | Patient | Step 2 - submits symptoms, runs AI triage, confirms booking |
| `GET /api/appointments/mine` | Any | Role-scoped appointment list |
| `GET /api/appointments/queue/today` | Doctor | Today's queue, sorted by urgency |
| `POST /api/appointments/{id}/cancel` | Owner/Admin | Cancels + frees the slot + notifies |
| `POST /api/appointments/{id}/visit-note` | Doctor | Clinical notes + prescription → AI patient summary + reminders scheduled |
| `GET /api/appointments/timeline/mine` | Patient | Visit history (the continuity-of-care data) |
| `GET /api/calendar/oauth/start` / `/callback` | Admin | One-time clinic Google Calendar connection |

## Database schema

Key tables (full definitions in `backend/app/models.py`):

- **users** — `id, email, password_hash, full_name, role[patient/doctor/admin]`
- **doctor_profiles** — `1:1` with a doctor user; `specialization, slot_duration_minutes, working_hours_json`
- **doctor_leaves** — `doctor_id, leave_date` (unique together), `reason`
- **slot_locks** — `UNIQUE(doctor_id, slot_start)`, the double-booking guard (see system design doc)
- **appointments** — `patient_id, doctor_id, slot_start/end, status, google_*_event_id`
- **symptom_forms** — pre-visit form + AI output: `urgency, chief_complaint, suggested_questions_json, llm_status`
- **visit_notes** — post-visit: `clinical_notes, diagnosis, prescription_json, patient_summary, llm_status`
- **medication_reminders** — one row per medication per time-of-day, scheduled from `prescription_json`
- **email_outbox** — every notification, with `status/attempts/last_error` for retry tracking
- **calendar_credentials** — single-row clinic Google refresh token

## LLM prompts

Both prompts live in `backend/app/services/llm_service.py` and request strict JSON
output (`response_format={"type": "json_object"}`).

**Pre-visit triage** (`TRIAGE_SYSTEM_PROMPT`) — asks for `urgency` (Low/Medium/High),
`chief_complaint`, three `suggested_questions`, and a `continuity_note`. The user
message includes the raw symptoms plus, when available, a compact text summary of
the patient's last five visits (built by `continuity_service.py`) — this is what
lets the model reason about recurring patterns instead of just the current form.

**Post-visit summary** (`POST_VISIT_SYSTEM_PROMPT`) — takes the doctor's clinical
notes, diagnosis, and structured prescription, and asks for a markdown `summary`
covering plain-English diagnosis, medication schedule, lifestyle advice, and
follow-up/red-flag guidance.

Both calls are wrapped in one retry + rule-based fallback (see `SYSTEM_DESIGN.md`),
and the resulting `llm_status` (`ok`/`fallback`) is stored and surfaced in the UI so
nothing is silently degraded.

## Deployment (all free tiers)

**Backend → Render**
1. Push this repo to GitHub, create a new **Web Service** on Render pointed at
   `backend/` with `render.yaml` as the blueprint (or set it up manually: Docker
   environment, `Dockerfile` in `backend/`).
2. Add the env vars from `backend/.env.example` in Render's dashboard. For
   `DATABASE_URL`, use **[Neon](https://neon.tech)** (free, permanent, no expiry)
   rather than Render's own free Postgres — Render's free databases are hard-deleted
   30 days after creation with no grace warning, which is fine for a demo but a bad
   surprise for anything you want to keep working. Also add your Groq key, SMTP
   credentials, and Google OAuth credentials.
3. Once deployed, run the bootstrap-admin curl command against your Render URL.

**Frontend → Vercel**
1. Import the repo on Vercel, set the root directory to `frontend/`.
2. Set `VITE_API_BASE_URL` to your Render backend URL.
3. Deploy — `vercel.json` already handles SPA routing.
4. Add the deployed Vercel URL to the backend's `CORS_ORIGINS` and Google's
   authorized redirect URIs (see `docs/GOOGLE_CALENDAR_SETUP.md`).

## Known POC simplifications

- Single clinic Google account instead of per-user OAuth (see calendar setup doc for the reasoning).
- No Alembic migrations wired up yet — `Base.metadata.create_all()` runs on startup. Fine for a POC; add Alembic before any real schema evolution.
- The admin-bootstrap endpoint is intentionally crude (self-disables after first use) — replace with a proper seed script for anything beyond a demo.