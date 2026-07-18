import { useEffect, useState } from 'react'
import PortalShell from '../../components/PortalShell'
import UrgencyBadge from '../../components/UrgencyBadge'
import { api, apiErrorMessage } from '../../api/client'

const LINKS = [
  { key: 'queue', label: "Today's queue" },
  { key: 'all', label: 'All appointments' },
]

export default function DoctorDashboard() {
  const [tab, setTab] = useState('queue')
  return (
    <PortalShell tagline="Doctor portal" links={LINKS} active={tab} onNavigate={setTab}>
      {tab === 'queue' && <Queue />}
      {tab === 'all' && <AllAppointments />}
    </PortalShell>
  )
}

function Queue() {
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [active, setActive] = useState(null)

  useEffect(() => { load() }, [])
  async function load() {
    try {
      const r = await api.get('/api/appointments/queue/today')
      setRows(r.data)
    } catch (err) { setError(apiErrorMessage(err)) }
  }

  if (active) return <VisitNoteForm appt={active} onDone={() => { setActive(null); load() }} onBack={() => setActive(null)} />

  return (
    <div>
      <h2>Today's queue</h2>
      <p className="muted">Sorted by AI-assessed urgency (High → Medium → Low), not just check-in order.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        {rows.length === 0 && <div className="empty-state">No confirmed appointments for today yet.</div>}
        {rows.map((a) => (
          <div className="doctor-row" key={a.id}>
            <div>
              <strong>{a.patient_name}</strong>
              <div className="muted">{new Date(a.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {a.chief_complaint || 'No chief complaint on file'}</div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <UrgencyBadge level={a.urgency} />
              <button className="btn btn-primary btn-sm" onClick={() => setActive(a)}>Open visit</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AllAppointments() {
  const [rows, setRows] = useState([])
  const [active, setActive] = useState(null)

  useEffect(() => { load() }, [])
  async function load() {
    const r = await api.get('/api/appointments/mine')
    setRows(r.data)
  }

  if (active) return <VisitNoteForm appt={active} onDone={() => { setActive(null); load() }} onBack={() => setActive(null)} />

  return (
    <div>
      <h2>All appointments</h2>
      <div className="card">
        {rows.length === 0 && <div className="empty-state">No appointments yet.</div>}
        {rows.length > 0 && (
          <table>
            <thead><tr><th>Patient</th><th>When</th><th>Status</th><th>Urgency</th><th /></tr></thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td>{a.patient_name}</td>
                  <td>{new Date(a.slot_start).toLocaleString()}</td>
                  <td><span className="pill">{a.status}</span></td>
                  <td>{a.urgency ? <UrgencyBadge level={a.urgency} /> : '—'}</td>
                  <td>
                    {a.status === 'confirmed' && (
                      <button className="btn btn-primary btn-sm" onClick={() => setActive(a)}>Open visit</button>
                    )}
                    {a.status === 'completed' && <VisitNoteToggle id={a.id} />}
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

function VisitNoteToggle({ id }) {
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
      <button className="btn btn-secondary btn-sm" onClick={toggle}>{open ? 'Hide' : 'View note'}</button>
      {open && note && (
        <div style={{ marginTop: 8, maxWidth: 380, fontSize: 13 }}>
          <div><strong>Diagnosis:</strong> {note.diagnosis || '—'}</div>
          <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{note.clinical_notes}</div>
        </div>
      )}
    </>
  )
}

function VisitNoteForm({ appt, onDone, onBack }) {
  const [notes, setNotes] = useState('')
  const [diagnosis, setDiagnosis] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [meds, setMeds] = useState([{ medication: '', dosage: '', frequency_per_day: 1, times: '08:00', duration_days: 5, notes: '' }])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  function updateMed(i, key, value) {
    setMeds((m) => m.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)))
  }
  function addMed() {
    setMeds((m) => [...m, { medication: '', dosage: '', frequency_per_day: 1, times: '08:00', duration_days: 5, notes: '' }])
  }
  function removeMed(i) { setMeds((m) => m.filter((_, idx) => idx !== i)) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const prescription = meds.filter((m) => m.medication).map((m) => ({
        ...m, times: m.times.split(',').map((t) => t.trim()).filter(Boolean),
        frequency_per_day: Number(m.frequency_per_day), duration_days: Number(m.duration_days),
      }))
      const r = await api.post(`/api/appointments/${appt.id}/visit-note`, {
        clinical_notes: notes, diagnosis, prescription,
        follow_up_days: followUp ? Number(followUp) : null,
      })
      setResult(r.data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (result) {
    return (
      <div className="card">
        <div className="alert alert-success">Visit note saved. Medication reminders scheduled for the patient.</div>
        <h3>Patient-friendly summary generated</h3>
        <div style={{ whiteSpace: 'pre-wrap', background: 'var(--paper)', padding: 14, borderRadius: 'var(--radius)' }}>
          {result.patient_summary}
        </div>
        {result.llm_status === 'fallback' && (
          <div className="alert alert-info" style={{ marginTop: 10 }}>Generated using a rule-based fallback (AI summary service was unavailable).</div>
        )}
        <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={onDone}>Back to queue</button>
      </div>
    )
  }

  return (
    <div className="card">
      <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: 12 }}>← Back</button>
      <div className="card-header">
        <h3>Visit - {appt.patient_name}</h3>
        <UrgencyBadge level={appt.urgency} />
      </div>
      <p className="muted"><strong>Pre-visit chief complaint:</strong> {appt.chief_complaint || 'None on file'}</p>
      {error && <div className="alert alert-error">{error}</div>}
      <form onSubmit={submit}>
        <div className="field">
          <label>Clinical notes</label>
          <textarea required value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="field-row">
          <div className="field">
            <label>Diagnosis</label>
            <input value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} />
          </div>
          <div className="field">
            <label>Follow-up in (days)</label>
            <input type="number" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
          </div>
        </div>

        <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink-soft)' }}>Prescription</label>
        {meds.map((m, i) => (
          <div className="field-row" key={i} style={{ marginTop: 8, alignItems: 'flex-end' }}>
            <div className="field"><label>Medication</label><input value={m.medication} onChange={(e) => updateMed(i, 'medication', e.target.value)} /></div>
            <div className="field"><label>Dosage</label><input value={m.dosage} onChange={(e) => updateMed(i, 'dosage', e.target.value)} /></div>
            <div className="field" style={{ maxWidth: 90 }}><label>x/day</label><input type="number" value={m.frequency_per_day} onChange={(e) => updateMed(i, 'frequency_per_day', e.target.value)} /></div>
            <div className="field"><label>Times (comma sep)</label><input value={m.times} onChange={(e) => updateMed(i, 'times', e.target.value)} placeholder="08:00, 20:00" /></div>
            <div className="field" style={{ maxWidth: 90 }}><label>Days</label><input type="number" value={m.duration_days} onChange={(e) => updateMed(i, 'duration_days', e.target.value)} /></div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => removeMed(i)}>Remove</button>
          </div>
        ))}
        <button type="button" className="btn btn-secondary btn-sm" onClick={addMed} style={{ marginTop: 8, marginBottom: 16 }}>+ Add medication</button>

        <div><button className="btn btn-primary" disabled={loading}>{loading ? 'Generating summary…' : 'Save & generate patient summary'}</button></div>
      </form>
    </div>
  )
}