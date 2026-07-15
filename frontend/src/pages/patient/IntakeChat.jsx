import { useEffect, useRef, useState } from 'react'
import UrgencyBadge from '../../components/UrgencyBadge'
import { api, apiErrorMessage } from '../../api/client'

export default function IntakeChat({ onRecommendation }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: "Hi! What's bringing you in today? Describe it in your own words." },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [recommendation, setRecommendation] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, recommendation])

  async function send(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading) return
    setError('')
    const nextMessages = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)
    try {
      // Only user/assistant turns matter to the backend - it re-derives everything else.
      const history = nextMessages.filter((m) => m.role === 'user' || m.role === 'assistant')
      const r = await api.post('/api/intake/chat', { history })
      const data = r.data
      setMessages((m) => [...m, { role: 'assistant', content: data.message }])
      if (data.status === 'recommendation') {
        setRecommendation(data)
      }
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setMessages([{ role: 'assistant', content: "Hi! What's bringing you in today? Describe it in your own words." }])
    setRecommendation(null)
    setInput('')
    setError('')
  }

  return (
    <div>
      <h2>Find the right doctor</h2>
      <p className="muted">Tell us what's going on - a couple of quick questions, then we'll point you to the right specialist.</p>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: 420 }}>
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: 4 }}>
          {messages.map((m, i) => <ChatBubble key={i} role={m.role} content={m.content} />)}
          {loading && <ChatBubble role="assistant" content="…" muted />}
          <div ref={bottomRef} />
        </div>

        {error && <div className="alert alert-error" style={{ marginTop: 10 }}>{error}</div>}

        {!recommendation && (
          <form onSubmit={send} style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <input
              autoFocus
              placeholder="Type your answer…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              style={{ flex: 1, padding: '9px 11px', border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}
            />
            <button className="btn btn-primary" disabled={loading || !input.trim()}>Send</button>
          </form>
        )}
      </div>

      {recommendation && (
        <div className="card">
          <div className="card-header">
            <h3>Recommended: {recommendation.specialization || 'General Medicine'}</h3>
            {recommendation.urgency_hint && <UrgencyBadge level={recommendation.urgency_hint} />}
          </div>
          {recommendation.reasoning && <p className="muted">{recommendation.reasoning}</p>}
          {recommendation.llm_status === 'fallback' && (
            <div className="alert alert-info">
              Generated using a rule-based fallback (AI service was unavailable) - you can still browse all doctors below.
            </div>
          )}
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              className="btn btn-primary"
              onClick={() => onRecommendation(recommendation.specialization, recommendation.consolidated_summary)}
            >
              View {recommendation.specialization || ''} doctors
            </button>
            <button className="btn btn-secondary" onClick={reset}>Start over</button>
          </div>
        </div>
      )}
    </div>
  )
}

function ChatBubble({ role, content, muted }) {
  const isUser = role === 'user'
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
      <div style={{
        maxWidth: '78%',
        padding: '9px 13px',
        borderRadius: 12,
        borderBottomRightRadius: isUser ? 3 : 12,
        borderBottomLeftRadius: isUser ? 12 : 3,
        background: isUser ? 'var(--teal)' : 'var(--paper)',
        color: isUser ? '#fff' : 'var(--ink)',
        border: isUser ? 'none' : '1px solid var(--line-soft)',
        opacity: muted ? 0.6 : 1,
        fontSize: 14,
        lineHeight: 1.45,
      }}>
        {content}
      </div>
    </div>
  )
}
