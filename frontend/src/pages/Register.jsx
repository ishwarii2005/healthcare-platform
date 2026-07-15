import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../api/client'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })) }

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await register({ ...form, role: 'patient' })
      navigate('/patient')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="card auth-card" onSubmit={onSubmit}>
        <div className="eyebrow">City Care Clinic</div>
        <h2>Create your account</h2>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="field">
          <label>Full name</label>
          <input required value={form.full_name} onChange={(e) => set('full_name', e.target.value)} />
        </div>
        <div className="field">
          <label>Email</label>
          <input type="email" required value={form.email} onChange={(e) => set('email', e.target.value)} />
        </div>
        <div className="field">
          <label>Phone</label>
          <input value={form.phone} onChange={(e) => set('phone', e.target.value)} />
        </div>
        <div className="field">
          <label>Password (min 6 characters)</label>
          <input type="password" required minLength={6} value={form.password} onChange={(e) => set('password', e.target.value)} />
        </div>
        <button className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
          {loading ? 'Creating…' : 'Create account'}
        </button>
        <p className="muted" style={{ marginTop: 14 }}>
          Already registered? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  )
}
