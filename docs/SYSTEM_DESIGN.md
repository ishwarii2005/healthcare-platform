# System Design Write-up

## Double-booking prevention

The naive approach — "check if a slot is free, then insert" — has a race window: two
patients can both pass the check before either commits. This system closes that
window at the database layer instead of the application layer, so it holds even
across multiple backend instances.

A `slot_locks` table has a `UNIQUE(doctor_id, slot_start)` constraint and one row per
*active* claim on a slot. Booking is two steps:

1. **Hold** — `POST /appointments/hold` creates an `Appointment(status=HELD)` and a
   `SlotLock` row in the same transaction. If a concurrent request already holds that
   exact slot, the second `INSERT` raises an `IntegrityError`, which the API turns
   into a `409 Conflict` — "this slot was just taken." There is no read-then-write
   gap for a race to slip through, because the database itself is the arbiter, not
   a Python-level check.
2. **Confirm** — after the patient submits the symptom form, `confirm_slot()` clears
   the lock's `expires_at` (making it permanent) and flips the appointment to
   `CONFIRMED`. This is also where emails and the calendar event are created.

## Slot hold mechanism

A raw hold-and-forget design would let an abandoned booking permanently block a
slot. Every hold therefore carries an `expires_at` (`SLOT_HOLD_MINUTES`, default 5).
A background job (`hold_cleanup_job`, runs every minute) sweeps expired locks:
if the appointment is still `HELD` when its lock expires, it's flipped to
`CANCELLED` and the lock row is deleted, freeing the slot again. The same sweep
also runs inline whenever a doctor's availability is queried, so a patient never
sees a slot as "taken" by a hold that has actually expired, even before the
minute-tick cleanup catches up.

## Doctor leave conflict handling

When admin records a `DoctorLeave` for a date, `leave_service.handle_leave_conflicts()`
runs synchronously in the same request: it queries every `CONFIRMED`/`HELD`
appointment for that doctor on that date, and for each one:

1. Cancels it via the same `cancel_appointment()` path used for patient-initiated
   cancellations (deletes the `SlotLock`, so the slot is genuinely freed, not just
   marked cancelled while still blocking rebooking).
2. Deletes the associated Google Calendar event and queues cancellation emails to
   both patient and doctor with the leave reason.
3. **Smart recovery (this is the product's differentiator):** computes up to three
   alternative open slots with the *same* doctor over the following two weeks
   (reusing the same availability logic patients see when searching) and emails
   them directly to the patient, so a leave-triggered cancellation ends with a
   ready-made rebooking path instead of a dead end. The admin's response also
   returns this list so they have visibility into who was affected and what was
   offered.

Leave conflicts are handled synchronously rather than queued, because the volume
per leave event is small (a doctor's appointments for one day) and the admin
benefits from seeing the affected-patient list immediately.

## Notification failure handling

Every outbound email, regardless of category, is written to an `email_outbox`
table first (`status=pending`) and only then does the code attempt to send it.
This "outbox" pattern means a send failure is a normal, visible state — `failed`,
with an `attempts` counter and `last_error` — rather than a lost side-effect. A
background job retries every `failed` row on a fixed interval (`EMAIL_RETRY_INTERVAL_MINUTES`)
until `EMAIL_MAX_ATTEMPTS` is hit, at which point the row becomes `dead` and
surfaces on the admin's "Notification health" page for a manual retry. This
converts "did the confirmation email actually go out?" from an invisible risk into
a queryable, actionable state.

Google Calendar follows the same philosophy but doesn't need its own outbox: it's
naturally idempotent per appointment (`google_doctor_event_id` is stored once
created, and update/delete simply target that ID), and a failure there — for
example the clinic never connected its calendar — is caught and logged without
raising, so it can never block a booking, symptom submission, or visit note. The
same "never block the core flow" principle governs the LLM integration: both the
pre-visit triage call and the post-visit summary call are wrapped in a single
retry-then-fallback path (`llm_service.py`) that produces a rule-based heuristic
result on failure rather than a 500. The `llm_status` field (`ok` / `fallback`) is
stored alongside the AI output so both the UI and the admin can tell which one
happened, but the patient- and doctor-facing flow is identical either way.

## Where the two USPs live in this design

The **urgency-triage queue** isn't a separate feature bolted on — it's the sort key
for the doctor's "Today's queue" view (`GET /appointments/queue/today`), sourced
directly from the `SymptomForm.urgency` field the pre-visit LLM call writes.
The **continuity-of-care timeline** feeds that same LLM call: `continuity_service.py`
pulls the patient's last five visits (chief complaint, diagnosis, prescriptions)
into the triage prompt, so the "three visits for headaches in six weeks" pattern
can be flagged in the very JSON that also produces the urgency label — one AI call,
two differentiators.
