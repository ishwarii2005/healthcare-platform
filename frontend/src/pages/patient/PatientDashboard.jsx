import { useEffect, useState } from 'react'
import PortalShell from '../../components/PortalShell'
import UrgencyBadge from '../../components/UrgencyBadge'
import IntakeChat from './IntakeChat'
import { api, apiErrorMessage } from '../../api/client'

const LINKS = [
  { key: 'intake', label: 'Find the right doctor' },
  { key: 'book', label: 'Book an appointment' },
  { key: 'appointments', label: 'My appointments' },
  { key: 'timeline', label: 'Care timeline' },
]

export default function PatientDashboard() {
  const [tab, setTab] = useState('intake')
  const [prefill, setPrefill] = useState({ specialization: '', symptoms: '' })

  function handleRecommendation(specialization, symptoms) {
    setPrefill({ specialization: specialization || '', symptoms: symptoms || '' })
    setTab('book')
  }

  return (
    <PortalShell tagline="Patient portal" links={LINKS} active={tab} onNavigate={setTab}>
      {tab === 'intake' && <IntakeChat onRecommendation={handleRecommendation} />}
      {tab === 'book' && (
        <BookAppointment
          onBooked={() => setTab('appointments')}
          prefillSpecialization={prefill.specialization}
          prefillSymptoms={prefill.symptoms}
        />
      )}
      {tab === 'appointments' && <MyAppointments />}
      {tab === 'timeline' && <Timeline />}
    </PortalShell>
  )
}

// ---------------- Book appointment ----------------
function BookAppointment({ onBooked, prefillSpecialization, prefillSymptoms }) {
  const [specializations, setSpecializations] = useState([])
  const [specialization, setSpecialization] = useState(prefillSpecialization || '')
  const [doctors, setDoctors] = useState([])
  const [selectedDoctor, setSelectedDoctor] = useState(null)
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [slots, setSlots] = useState([])
  const [onLeave, setOnLeave] = useState(false)
  const [selectedSlot, setSelectedSlot] = useState(null)
  const [holdInfo, setHoldInfo] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get('/api/doctors/specializations').then((r) => setSpecializations(r.data)).catch(() => {})
    searchDoctors(prefillSpecialization || '')
  }, [])

  async function searchDoctors(spec = specialization) {
    const r = await api.get('/api/doctors', { params: spec ? { specialization: spec } : {} })
    setDoctors(r.data)
  }

  async function loadAvailability(doctor, forDay) {
    setSelectedDoctor(doctor)
    setSelectedSlot(null)
    setHoldInfo(null)
    setError('')
    const r = await api.get(`/api/doctors/${doctor.id}/availability`, { params: { day: forDay } })
    setSlots(r.data.slots)
    setOnLeave(r.data.on_leave)
  }

  async function holdSlot(slot) {
    setError('')
    setLoading(true)
    try {
      const r = await api.post('/api/appointments/hold', { doctor_id: selectedDoctor.id, slot_start: slot })
      setSelectedSlot(slot)
      setHoldInfo(r.data)
    } catch (err) {
      setError(apiErrorMessage(err))
      if (selectedDoctor) loadAvailability(selectedDoctor, day)
    } finally {
      setLoading(false)
    }
  }

  if (holdInfo) {
    return (
      <SymptomForm
        holdInfo={holdInfo}
        doctor={selectedDoctor}
        onDone={onBooked}
        onExpire={() => setHoldInfo(null)}
        prefillSymptoms={prefillSymptoms}
      />
    )
  }

  return (
    <div>
      <h2>Book an appointment</h2>
      <p className="muted">Search by specialization, pick a doctor, then choose an open slot.</p>
      {prefillSpecialization && (
        <div className="alert alert-info">
          Showing <strong>{prefillSpecialization}</strong> doctors based on your chat - change the filter below to see others.
        </div>
      )}

      <div className="card">
        <div className="field-row">
          <div className="field">
            <label>Specialization</label>
            <select value={specialization} onChange={(e) => { setSpecialization(e.target.value); searchDoctors(e.target.value) }}>
              <option value="">All specializations</option>
              {specializations.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        {doctors.length === 0 && <div className="empty-state">No doctors found for this specialization.</div>}
        {doctors.map((doc) => (
          <div className="doctor-row" key={doc.id}>
            <div>
              <strong>Dr. {doc.full_name}</strong>
              <div className="muted">{doc.specialization} · {doc.slot_duration_minutes}-min slots</div>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={() => loadAvailability(doc, day)}>
              {selectedDoctor?.id === doc.id ? 'Selected' : 'View availability'}
            </button>
          </div>
        ))}
      </div>

      {selectedDoctor && (
        <div className="card">
          <div className="card-header">
            <h3>Availability - Dr. {selectedDoctor.full_name}</h3>
          </div>
          <div className="field" style={{ maxWidth: 220 }}>
            <label>Date</label>
            <input type="date" value={day} min={new Date().toISOString().slice(0, 10)}
              onChange={(e) => { setDay(e.target.value); loadAvailability(selectedDoctor, e.target.value) }} />
          </div>
          {error && <div className="alert alert-error">{error}</div>}
          {onLeave && <div className="alert alert-info">The doctor is on leave this day. Please pick another date.</div>}
          {!onLeave && slots.length === 0 && <div className="empty-state">No open slots on this day.</div>}
          {!onLeave && slots.length > 0 && (
            <div className="slot-grid">
              {slots.map((s) => (
                <button key={s} className={`slot-btn ${selectedSlot === s ? 'selected' : ''}`}
                  disabled={loading} onClick={() => holdSlot(s)}>
                  {new Date(s).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SymptomForm({ holdInfo, doctor, onDone, onExpire, prefillSymptoms }) {
  const [symptoms, setSymptoms] = useState(prefillSymptoms || '')
  const [duration, setDuration] = useState('')
  const [severity, setSeverity] = useState(5)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const [secondsLeft, setSecondsLeft] = useState(
    Math.max(0, Math.floor((new Date(holdInfo.hold_expires_at) - new Date()) / 1000))
  )
  useEffect(() => {
    const t = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [])

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const r = await api.post(`/api/appointments/${holdInfo.appointment_id}/symptoms`, {
        raw_symptoms: symptoms,
        duration_days: duration ? Number(duration) : null,
        severity_self_rated: Number(severity),
      })
      setResult(r.data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (secondsLeft <= 0 && !result) {
    return (
      <div className="card">
        <div className="alert alert-error">Your hold on this slot expired. Please pick a new time.</div>
        <button className="btn btn-secondary" onClick={onExpire}>Back to availability</button>
      </div>
    )
  }

  if (result) {
    return (
      <div className="card">
        <div className="alert alert-success">Appointment confirmed with Dr. {doctor.full_name}.</div>
        <div className="card-header"><h3>Pre-visit AI summary shared with your doctor</h3><UrgencyBadge level={result.urgency} /></div>
        <p><strong>Chief complaint:</strong> {result.chief_complaint}</p>
        <p><strong>Questions your doctor may ask:</strong></p>
        <ul>{result.suggested_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        {result.llm_status === 'fallback' && (
          <div className="alert alert-info">Generated using a rule-based fallback (AI summary service was unavailable) - your appointment is still fully confirmed.</div>
        )}
        <button className="btn btn-primary" onClick={onDone}>Go to my appointments</button>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>Tell us why you're visiting</h3>
        <span className="pill">Hold expires in {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, '0')}</span>
      </div>
      <p className="muted">
        Slot held with Dr. {doctor.full_name} at {new Date(holdInfo.slot_start).toLocaleString()}.
        This form lets our AI prepare a pre-visit summary for your doctor - it does not diagnose you.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <form onSubmit={submit}>
        <div className="field">
          <label>Describe your symptoms</label>
          <textarea required value={symptoms} onChange={(e) => setSymptoms(e.target.value)}
            placeholder="e.g. Dull headache on the right side for 3 days, worse in the evening" />
          {prefillSymptoms && (
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              Carried over from your chat - feel free to edit it before submitting.
            </div>
          )}
        </div>
        <div className="field-row">
          <div className="field">
            <label>How many days have you had this?</label>
            <input type="number" min="0" value={duration} onChange={(e) => setDuration(e.target.value)} />
          </div>
          <div className="field">
            <label>Self-rated severity (1-10)</label>
            <input type="number" min="1" max="10" value={severity} onChange={(e) => setSeverity(e.target.value)} />
          </div>
        </div>
        <button className="btn btn-primary" disabled={loading}>{loading ? 'Analyzing…' : 'Submit & confirm appointment'}</button>
      </form>
    </div>
  )
}

// ---------------- My appointments ----------------
function MyAppointments() {
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')

  useEffect(() => { load() }, [])
  async function load() {
    try {
      const r = await api.get('/api/appointments/mine')
      setRows(r.data)
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  async function cancel(id) {
    if (!confirm('Cancel this appointment?')) return
    await api.post(`/api/appointments/${id}/cancel`)
    load()
  }

  return (
    <div>
      <h2>My appointments</h2>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        {rows.length === 0 && <div className="empty-state">No appointments yet - book one to get started.</div>}
        {rows.length > 0 && (
          <table>
            <thead><tr><th>Doctor</th><th>When</th><th>Status</th><th>Urgency</th><th /></tr></thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td>Dr. {a.doctor_name}<div className="muted">{a.specialization}</div></td>
                  <td>{new Date(a.slot_start).toLocaleString()}</td>
                  <td><span className="pill">{a.status}</span></td>
                  <td>{a.urgency ? <UrgencyBadge level={a.urgency} /> : '—'}</td>
                  <td>
                    {(a.status === 'confirmed' || a.status === 'held') && (
                      <button className="btn btn-danger btn-sm" onClick={() => cancel(a.id)}>Cancel</button>
                    )}
                    {a.status === 'completed' && <VisitSummaryLink id={a.id} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function VisitSummaryLink({ id }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState(null)
  async function toggle() {
    if (!open && !note) {
      const r = await api.get(`/api/appointments/${id}/visit-note`)
      setNote(r.data)
    }
    setOpen(!open)
  }
  return (
    <>
      <button className="btn btn-secondary btn-sm" onClick={toggle}>{open ? 'Hide summary' : 'View summary'}</button>
      {open && note && (
        <div style={{ marginTop: 8, maxWidth: 380, whiteSpace: 'pre-wrap', fontSize: 13 }}>{note.patient_summary}</div>
      )}
    </>
  )
}

// ---------------- Timeline ----------------
function Timeline() {
  const [rows, setRows] = useState([])
  useEffect(() => {
    api.get('/api/appointments/timeline/mine').then((r) => setRows(r.data)).catch(() => {})
  }, [])

  return (
    <div>
      <h2>Care timeline</h2>
      <p className="muted">Your visit history - this is what our AI uses to spot recurring patterns before your next visit.</p>
      <div className="card">
        {rows.length === 0 && <div className="empty-state">No completed visits yet.</div>}
        {rows.map((r, i) => (
          <div className="timeline-item" key={i}>
            <div className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.date}</div>
            {r.chief_complaint && <div><strong>{r.chief_complaint}</strong></div>}
            {r.diagnosis && <div>Diagnosis: {r.diagnosis}</div>}
            {r.prescription?.length > 0 && (
              <div className="muted">Prescribed: {r.prescription.map((p) => p.medication).join(', ')}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
