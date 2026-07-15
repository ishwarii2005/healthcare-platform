"""
LLM integration (Groq - free tier, OpenAI-compatible chat completions).

Two responsibilities, matching the two USPs:
1. Pre-visit triage summary - urgency level + chief complaint + suggested questions,
   PLUS continuity: if the patient has prior visit summaries, they are folded into
   the prompt so the model can flag recurring/worsening patterns
   (e.g. "3rd visit for headaches in 6 weeks - possible chronic pattern").
2. Post-visit patient-friendly summary from the doctor's clinical notes + prescription.

Failure handling: every call goes through `_call_groq`, which retries once on
transient errors, and if it still fails, the caller falls back to a rule-based
heuristic so the appointment flow NEVER blocks on the LLM being down/rate-limited.
"""
import json
import logging
from typing import Optional

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.config import settings

logger = logging.getLogger("llm_service")

_client: Optional[Groq] = None


def _get_client() -> Optional[Groq]:
    global _client
    if not settings.GROQ_API_KEY:
        return None
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)
    return _client


@retry(
    stop=stop_after_attempt(max(1, settings.LLM_MAX_RETRIES + 1)),
    wait=wait_fixed(1.5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_groq(system_prompt: str, user_prompt: str) -> str:
    client = _get_client()
    if client is None:
        raise RuntimeError("GROQ_API_KEY not configured")
    resp = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=600,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


@retry(
    stop=stop_after_attempt(max(1, settings.LLM_MAX_RETRIES + 1)),
    wait=wait_fixed(1.5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_groq_messages(messages: list[dict]) -> str:
    """Like _call_groq, but takes a full message list (system + multi-turn history)
    instead of a single system/user pair - used by the conversational intake flow."""
    client = _get_client()
    if client is None:
        raise RuntimeError("GROQ_API_KEY not configured")
    resp = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=400,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content




TRIAGE_SYSTEM_PROMPT = (
    "You are a clinical intake assistant helping a doctor prepare for a patient visit. "
    "You do NOT diagnose. Analyse the patient's reported symptoms and any prior-visit "
    "context, and return ONLY a JSON object with exactly these keys: "
    '"urgency" (one of "Low", "Medium", "High"), "chief_complaint" (a short phrase), '
    '"suggested_questions" (a list of exactly 3 short questions the doctor should ask), '
    '"continuity_note" (a one-sentence note on whether this links to a pattern in the '
    'patient\'s prior visits, or "" if there is no prior history or no clear link). '
    "Mark urgency High for red-flag symptoms (chest pain, breathing difficulty, severe "
    "bleeding, stroke signs, high fever with stiff neck, suicidal ideation, severe "
    "abdominal pain). Mark Medium for symptoms that need timely but not emergency care. "
    "Mark Low for routine/minor complaints."
)


def build_triage_user_prompt(symptoms: str, duration_days: int | None, severity: int | None,
                              prior_visits_summary: str | None) -> str:
    parts = [f"Symptoms: {symptoms}"]
    if duration_days is not None:
        parts.append(f"Duration: {duration_days} day(s)")
    if severity is not None:
        parts.append(f"Patient self-rated severity: {severity}/10")
    if prior_visits_summary:
        parts.append(f"Prior visit history for this patient:\n{prior_visits_summary}")
    else:
        parts.append("Prior visit history: none on file.")
    return "\n".join(parts)


def _rule_based_triage_fallback(symptoms: str) -> dict:
    """Simple keyword heuristic used only if the LLM call fails entirely."""
    red_flags = ["chest pain", "breathless", "can't breathe", "cannot breathe", "severe bleeding",
                 "unconscious", "stroke", "suicidal", "seizure", "severe abdominal"]
    text = symptoms.lower()
    urgency = "High" if any(k in text for k in red_flags) else "Medium" if len(text) > 0 else "Low"
    return {
        "urgency": urgency,
        "chief_complaint": symptoms.strip()[:80] or "Not specified",
        "suggested_questions": [
            "When did the symptoms start and how have they changed?",
            "Have you taken any medication for this already?",
            "Do you have any relevant medical history or allergies?",
        ],
        "continuity_note": "",
    }


def generate_triage_summary(symptoms: str, duration_days: int | None, severity: int | None,
                             prior_visits_summary: str | None) -> dict:
    """Returns dict with urgency/chief_complaint/suggested_questions/continuity_note/llm_status."""
    user_prompt = build_triage_user_prompt(symptoms, duration_days, severity, prior_visits_summary)
    try:
        raw = _call_groq(TRIAGE_SYSTEM_PROMPT, user_prompt)
        data = json.loads(raw)
        data["urgency"] = data.get("urgency") if data.get("urgency") in ("Low", "Medium", "High") else "Medium"
        data.setdefault("suggested_questions", [])
        data["llm_status"] = "ok"
        data["llm_raw_response"] = raw
        return data
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this must never crash the request
        logger.warning("Triage LLM call failed, using fallback: %s", exc)
        fallback = _rule_based_triage_fallback(symptoms)
        fallback["llm_status"] = "fallback"
        fallback["llm_raw_response"] = None
        return fallback


# ---------- Post-visit summary ----------

POST_VISIT_SYSTEM_PROMPT = (
    "You are a medical communication assistant. Convert a doctor's clinical notes and "
    "prescription into a warm, plain-language summary a patient with no medical background "
    "can understand. Return ONLY a JSON object with one key: \"summary\" (a markdown string). "
    "The summary must include: a short plain-English explanation of the diagnosis, a clear "
    "medication schedule (what, how much, when, for how long), any lifestyle advice from the "
    "notes, and concrete follow-up steps (when to come back, and red-flag symptoms that mean "
    "they should seek care sooner). Do not invent any medical detail not present in the notes."
)


def build_post_visit_user_prompt(clinical_notes: str, diagnosis: str | None,
                                  prescription: list[dict], follow_up_days: int | None) -> str:
    parts = [f"Clinical notes: {clinical_notes}"]
    if diagnosis:
        parts.append(f"Diagnosis: {diagnosis}")
    if prescription:
        parts.append(f"Prescription (JSON): {json.dumps(prescription)}")
    if follow_up_days:
        parts.append(f"Follow-up in: {follow_up_days} day(s)")
    return "\n".join(parts)


def _rule_based_post_visit_fallback(diagnosis: str | None, prescription: list[dict],
                                     follow_up_days: int | None) -> str:
    lines = ["## Your Visit Summary"]
    if diagnosis:
        lines.append(f"**Diagnosis:** {diagnosis}")
    if prescription:
        lines.append("\n**Medication schedule:**")
        for med in prescription:
            lines.append(
                f"- {med.get('medication', 'Medication')} {med.get('dosage', '')} - "
                f"{med.get('frequency_per_day', '?')}x/day at {', '.join(med.get('times', []))} "
                f"for {med.get('duration_days', '?')} days. {med.get('notes', '')}"
            )
    if follow_up_days:
        lines.append(f"\n**Follow-up:** Please book a follow-up visit in about {follow_up_days} days.")
    lines.append("\n_This summary was auto-generated without AI assistance because our "
                  "summary service was temporarily unavailable. Please ask the clinic if "
                  "anything here is unclear._")
    return "\n".join(lines)


def generate_post_visit_summary(clinical_notes: str, diagnosis: str | None,
                                 prescription: list[dict], follow_up_days: int | None) -> dict:
    user_prompt = build_post_visit_user_prompt(clinical_notes, diagnosis, prescription, follow_up_days)
    try:
        raw = _call_groq(POST_VISIT_SYSTEM_PROMPT, user_prompt)
        data = json.loads(raw)
        summary = data.get("summary") or _rule_based_post_visit_fallback(diagnosis, prescription, follow_up_days)
        return {"summary": summary, "llm_status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Post-visit LLM call failed, using fallback: %s", exc)
        return {
            "summary": _rule_based_post_visit_fallback(diagnosis, prescription, follow_up_days),
            "llm_status": "fallback",
        }


# ---------- Conversational pre-booking intake ----------
#
# A short multi-turn chat that runs BEFORE the patient picks a doctor. Goal: ask
# a couple of focused follow-up questions, then recommend which specialization
# fits their case - closing the gap where patients currently have to guess which
# kind of doctor they need. The final "consolidated_summary" is handed to the
# frontend, which prefills the existing pre-visit symptom form with it once a
# slot is booked, so the patient never has to repeat themselves.

MAX_INTAKE_TURNS = 4  # user messages before we force a recommendation, LLM or fallback


def _intake_system_prompt(specializations: list[str]) -> str:
    spec_list = ", ".join(specializations) if specializations else "General Medicine"
    return (
        "You are a friendly clinic intake assistant. Have a short, focused conversation "
        "with a patient about why they want to see a doctor, then recommend which clinic "
        "specialization fits their case. You do NOT diagnose and do NOT recommend treatment.\n\n"
        f"Available specializations at this clinic: {spec_list}\n\n"
        "Rules:\n"
        "- Ask ONE short, clear follow-up question at a time - never multiple questions at once.\n"
        f"- Ask at most {MAX_INTAKE_TURNS - 1} follow-up questions total. Stop earlier if you "
        "already have enough information to make a confident recommendation.\n"
        "- Recommend ONLY a specialization from the list above. If nothing fits well, use "
        "\"General Medicine\" if it's in the list, otherwise the closest match from the list.\n"
        "- If the patient describes anything that could be a medical emergency (chest pain, "
        "difficulty breathing, severe bleeding, stroke signs, suicidal thoughts), stop asking "
        "questions immediately, set urgency_hint to High, and say in \"message\" that they "
        "should seek emergency care right away in addition to the specialization recommendation.\n\n"
        "Respond ONLY with a JSON object with exactly these keys:\n"
        '"status": "asking" or "recommendation"\n'
        '"message": your next question (if "asking"), or a short warm sentence introducing the '
        'recommendation (if "recommendation")\n'
        '"specialization": the recommended specialization if status is "recommendation", else null\n'
        '"reasoning": one plain-language sentence for the recommendation if status is '
        '"recommendation", else null\n'
        '"urgency_hint": "Low", "Medium", or "High" - your best-effort read so far, always included\n'
        '"consolidated_summary": a 1-3 sentence summary of the patient\'s symptoms in plain '
        "language, always included and updated each turn"
    )


def _rule_based_intake_fallback(turn_count: int, specializations: list[str], last_user_text: str) -> dict:
    """Used only if the LLM call fails outright. Degrades gracefully: keep asking a
    generic clarifying question until the turn cap, then hand back to manual search."""
    if turn_count < MAX_INTAKE_TURNS:
        return {
            "status": "asking",
            "message": "Could you tell me a bit more about your main symptom and how long you've had it?",
            "specialization": None,
            "reasoning": None,
            "urgency_hint": "Unknown",
            "consolidated_summary": last_user_text[:200],
            "llm_status": "fallback",
        }
    fallback_spec = "General Medicine" if "General Medicine" in specializations else (
        specializations[0] if specializations else None
    )
    return {
        "status": "recommendation",
        "message": "We couldn't process this automatically - here's a general recommendation, "
                    "or you can browse all doctors below.",
        "specialization": fallback_spec,
        "reasoning": "Default recommendation - the AI assistant was temporarily unavailable.",
        "urgency_hint": "Unknown",
        "consolidated_summary": last_user_text[:200],
        "llm_status": "fallback",
    }


def generate_intake_turn(history: list[dict], specializations: list[str]) -> dict:
    """
    history: list of {"role": "user"|"assistant", "content": str}, ending with the
    latest user message. Returns the dict described in the system prompt above,
    plus "llm_status".
    """
    turn_count = sum(1 for m in history if m.get("role") == "user")
    last_user_text = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

    messages = [{"role": "system", "content": _intake_system_prompt(specializations)}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    if turn_count >= MAX_INTAKE_TURNS:
        messages.append({
            "role": "system",
            "content": "This is the final turn. You MUST respond with status=\"recommendation\" now "
                       "- do not ask another question, decide based on what you have so far.",
        })

    try:
        raw = _call_groq_messages(messages)
        data = json.loads(raw)
        if data.get("status") not in ("asking", "recommendation"):
            data["status"] = "recommendation" if turn_count >= MAX_INTAKE_TURNS else "asking"

        # Never trust the LLM to actually stop - enforce the turn cap server-side too.
        if turn_count >= MAX_INTAKE_TURNS and data["status"] != "recommendation":
            data["status"] = "recommendation"
            data.setdefault("message", "Here's a recommendation based on what you've shared.")

        # Never trust the LLM to only pick from the real list - validate/correct it.
        spec = data.get("specialization")
        if data["status"] == "recommendation":
            if not spec or not any(spec.lower() == s.lower() for s in specializations):
                data["specialization"] = "General Medicine" if "General Medicine" in specializations else (
                    specializations[0] if specializations else None
                )

        data.setdefault("urgency_hint", "Unknown")
        data.setdefault("consolidated_summary", last_user_text[:200])
        data["llm_status"] = "ok"
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intake LLM call failed, using fallback: %s", exc)
        return _rule_based_intake_fallback(turn_count, specializations, last_user_text)
