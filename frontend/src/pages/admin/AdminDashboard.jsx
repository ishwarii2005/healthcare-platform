import { useEffect, useState } from 'react'
import PortalShell from '../../components/PortalShell'
import { api, apiErrorMessage } from '../../api/client'

const LINKS = [
  { key: 'doctors', label: 'Doctors' },
  { key: 'leave', label: 'Leave management' },
  { key: 'emails', label: 'Notification health' },
  { key: 'calendar', label: 'Google Calendar' },
]

const DAYS = [
  ['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun'],
]

export default function AdminDashboard() {
  const [tab, setTab] = useState('doctors')
  return (
    <PortalShell tagline="Admin portal" links={LINKS} active={tab} onNavigate={setTab}>
      {tab === 'doctors' && <Doctors />}
      {tab === 'leave' && <Leave />}
      {tab === 'emails' && <Emails />}
      {tab === 'calendar' && <CalendarConnect />}
    </PortalShell>
  )
}

function emptyWorkingHours() {
  const wh = {}
  DAYS.forEach(([k]) => { wh[k] = ['09:00', '17:00'] })
  return wh
}

function Doctors() {
  const [doctors, setDoctors] = useState([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    full_name: '', email: '', password: '', phone: '', specialization: '',
    bio: '', slot_duration_minutes: 15, working_hours: emptyWorkingHours(),
    active_days: DAYS.map(([k]) => k),
  })

  useEffect(() => { load() }, [])
  async function load() {
    const r = await api.get('/api/admin/doctors')
    setDoctors(r.data)
  }

  function toggleDay(k) {
    setForm((f) => ({
      ...f,
      active_days: f.active_days.includes(k) ? f.active_days.filter((d) => d !== k) : [...f.active_days, k],
    }))
  }
  function setHours(k, idx, val) {
    setForm((f) => ({ ...f, working_hours: { ...f.working_hours, [k]: idx === 0 ? [val, f.working_hours[k][1]] : [f.working_hours[k][0], val] } }))
  }

  async function submit(e) {
    e.preventDefault()
    setError(''); setSuccess('')
    try {
      const working_hours = {}
      form.active_days.forEach((k) => { working_hours[k] = form.working_hours[k] })
      await api.post('/api/admin/doctors', {
        email: form.email, password: form.password, full_name: form.full_name, phone: form.phone,
        specialization: form.specialization, bio: form.bio,
        slot_duration_minutes: Number(form.slot_duration_minutes), working_hours,
      })
      setSuccess(`Dr. ${form.full_name} added.`)
      setShowForm(false)
      setForm({ full_name: '', email: '', password: '', phone: '', specialization: '', bio: '', slot_duration_minutes: 15, working_hours: emptyWorkingHours(), active_days: DAYS.map(([k]) => k) })
      load()
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  return (
    <div>
      <div className="card-header"><h2>Doctors</h2><button className="btn btn-primary btn-sm" onClick={() => setShowForm(!showForm)}>{showForm ? 'Cancel' : '+ Add doctor'}</button></div>
      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      {showForm && (
        <form className="card" onSubmit={submit}>
          <h3>New doctor profile</h3>
          <div className="field-row">
            <div className="field"><label>Full name</label><input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
            <div className="field"><label>Specialization</label><input required value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })} /></div>
          </div>
          <div className="field-row">
            <div className="field"><label>Email</label><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div className="field"><label>Temporary password</label><input required minLength={6} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          </div>
          <div className="field-row">
            <div className="field"><label>Phone</label><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
            <div className="field" style={{ maxWidth: 160 }}><label>Slot length (min)</label><input type="number" value={form.slot_duration_minutes} onChange={(e) => setForm({ ...form, slot_duration_minutes: e.target.value })} /></div>
          </div>
          <div className="field"><label>Bio</label><textarea value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} /></div>

          <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--ink-soft)' }}>Working days & hours</label>
          {DAYS.map(([k, label]) => (
            <div className="field-row" key={k} style={{ alignItems: 'center', marginTop: 6 }}>
              <label style={{ width: 90 }}>
                <input type="checkbox" checked={form.active_days.includes(k)} onChange={() => toggleDay(k)} /> {label}
              </label>
              <div className="field"><input type="time" disabled={!form.active_days.includes(k)} value={form.working_hours[k][0]} onChange={(e) => setHours(k, 0, e.target.value)} /></div>
              <div className="field"><input type="time" disabled={!form.active_days.includes(k)} value={form.working_hours[k][1]} onChange={(e) => setHours(k, 1, e.target.value)} /></div>
            </div>
          ))}
          <button className="btn btn-primary" style={{ marginTop: 14 }}>Create doctor profile</button>
        </form>
      )}

      <div className="card">
        {doctors.length === 0 && <div className="empty-state">No doctors added yet.</div>}
        {doctors.map((d) => (
          <div className="doctor-row" key={d.id}>
            <div>
              <strong>Dr. {d.full_name}</strong>
              <div className="muted">{d.specialization} · {d.email} · {d.slot_duration_minutes}-min slots</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Leave() {
  const [doctors, setDoctors] = useState([])
  const [doctorId, setDoctorId] = useState('')
  const [date, setDate] = useState('')
  const [reason, setReason] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { api.get('/api/admin/doctors').then((r) => setDoctors(r.data)) }, [])

  async function submit(e) {
    e.preventDefault()
    setError(''); setResult(null)
    try {
      const r = await api.post(`/api/admin/doctors/${doctorId}/leave`, { leave_date: date, reason })
      setResult(r.data)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  return (
    <div>
      <h2>Leave management</h2>
      <p className="muted">Marking a doctor on leave automatically cancels any existing bookings that day, emails both sides, and suggests the patient up to 3 alternative slots.</p>
      <form className="card" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="field">
          <label>Doctor</label>
          <select required value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
            <option value="">Select a doctor</option>
            {doctors.map((d) => <option key={d.id} value={d.id}>Dr. {d.full_name} - {d.specialization}</option>)}
          </select>
        </div>
        <div className="field-row">
          <div className="field"><label>Leave date</label><input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="field"><label>Reason (optional)</label><input value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        </div>
        <button className="btn btn-primary">Mark leave & notify affected patients</button>
      </form>

      {result && (
        <div className="card">
          <h3>Result</h3>
          {result.affected_appointments.length === 0 && <div className="alert alert-success">No existing bookings were affected.</div>}
          {result.affected_appointments.length > 0 && (
            <table>
              <thead><tr><th>Patient</th><th>Original slot</th><th>Suggested alternatives</th></tr></thead>
              <tbody>
                {result.affected_appointments.map((a) => (
                  <tr key={a.appointment_id}>
                    <td>{a.patient_email}</td>
                    <td>{new Date(a.original_slot).toLocaleString()}</td>
                    <td>{a.suggested_alternatives.map((s) => new Date(s).toLocaleString()).join(', ') || 'None found in next 14 days'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function Emails() {
  const [rows, setRows] = useState([])
  useEffect(() => { load() }, [])
  async function load() { const r = await api.get('/api/admin/emails/failed'); setRows(r.data) }
  async function retry(id) { await api.post(`/api/admin/emails/${id}/retry`); load() }

  return (
    <div>
      <h2>Notification health</h2>
      <p className="muted">Failed or exhausted email deliveries. Background jobs retry automatically; you can also force a retry here.</p>
      <div className="card">
        {rows.length === 0 && <div className="empty-state">No failed notifications - everything is delivering fine.</div>}
        {rows.length > 0 && (
          <table>
            <thead><tr><th>To</th><th>Subject</th><th>Category</th><th>Attempts</th><th>Status</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.to}</td><td>{r.subject}</td><td>{r.category}</td><td>{r.attempts}</td>
                  <td><span className="pill">{r.status}</span></td>
                  <td><button className="btn btn-secondary btn-sm" onClick={() => retry(r.id)}>Retry now</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function CalendarConnect() {
  const [status, setStatus] = useState(null)
  useEffect(() => { api.get('/api/calendar/status').then((r) => setStatus(r.data)) }, [])

  async function connect() {
    const r = await api.get('/api/calendar/oauth/start')
    window.location.href = r.data.authorization_url
  }

  return (
    <div>
      <h2>Google Calendar</h2>
      <p className="muted">Connect the clinic's Google account once. Every booking then creates one calendar event with the doctor and patient added as attendees, so both get an invite in their own calendar - no per-user OAuth needed.</p>
      <div className="card">
        {status?.connected ? (
          <div className="alert alert-success">Clinic calendar is connected.</div>
        ) : (
          <>
            <div className="alert alert-info">Not connected yet - appointments will still book normally, just without calendar invites.</div>
            <button className="btn btn-primary" onClick={connect}>Connect Google Calendar</button>
          </>
        )}
      </div>
    </div>
  )
}
