import { useEffect, useState } from 'react'
import { login, signup } from '../../api'

const s = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(135deg, #f8f7f4 0%, #eef2ff 100%)',
    fontFamily: 'var(--font)',
    padding: '24px',
  },
  card: {
    width: '100%',
    maxWidth: '420px',
    background: '#ffffff',
    border: '1px solid var(--border)',
    borderRadius: '20px',
    boxShadow: '0 20px 60px rgba(15, 23, 42, 0.10)',
    padding: '28px',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginBottom: '22px',
  },
  logo: {
    width: '40px',
    height: '40px',
    borderRadius: '12px',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '20px',
  },
  title: {
    fontSize: '22px',
    fontWeight: 700,
    color: 'var(--text-primary)',
    margin: 0,
  },
  subtitle: {
    fontSize: '13px',
    color: 'var(--text-muted)',
    marginTop: '4px',
  },
  tabs: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px',
    padding: '4px',
    borderRadius: '12px',
    background: 'var(--hover-bg)',
    marginBottom: '18px',
  },
  tab: (active) => ({
    border: 'none',
    borderRadius: '9px',
    padding: '9px',
    background: active ? '#ffffff' : 'transparent',
    color: active ? 'var(--text-primary)' : 'var(--text-muted)',
    fontWeight: active ? 600 : 500,
    cursor: 'pointer',
    boxShadow: active ? '0 1px 6px rgba(15, 23, 42, 0.08)' : 'none',
  }),
  label: {
    display: 'block',
    fontSize: '12px',
    fontWeight: 600,
    color: 'var(--text-secondary)',
    marginBottom: '6px',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    padding: '11px 12px',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    fontSize: '14px',
    outline: 'none',
    marginBottom: '14px',
  },
  button: (disabled) => ({
    width: '100%',
    padding: '12px 14px',
    border: 'none',
    borderRadius: '10px',
    background: disabled ? '#c7d2fe' : '#6366f1',
    color: '#ffffff',
    fontSize: '14px',
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
  }),
  error: {
    marginBottom: '14px',
    padding: '10px 12px',
    borderRadius: '10px',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    color: '#b91c1c',
    fontSize: '13px',
  },
  note: {
    marginTop: '14px',
    fontSize: '12px',
    color: 'var(--text-muted)',
    lineHeight: 1.6,
  },
}

export default function AuthScreen({ onAuthenticated, initialError = null }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(initialError)



  useEffect(() => {
    setError(initialError)
  }, [initialError])



  async function handleSubmit(e) {
    e.preventDefault()
    if (loading) return

    setLoading(true)
    setError(null)
    try {
      const user = mode === 'signup'
        ? await signup(email.trim(), password, fullName.trim())
        : await login(email.trim(), password)
      onAuthenticated(user)
    } catch (err) {
      setError(err.message || 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.page}>
      <form style={s.card} onSubmit={handleSubmit}>
        <div style={s.brand}>
          <div style={s.logo}>⚗</div>
          <div>
            <h1 style={s.title}>Materia</h1>
            <div style={s.subtitle}>Sign in to keep sessions, files, and API keys private.</div>
          </div>
        </div>

        <div style={s.tabs}>
          <button type="button" style={s.tab(mode === 'login')} onClick={() => setMode('login')}>
            Sign in
          </button>
          <button type="button" style={s.tab(mode === 'signup')} onClick={() => setMode('signup')}>
            Create account
          </button>
        </div>

        {error && <div style={s.error}>{error}</div>}

        {mode === 'signup' && (
          <>
            <label style={s.label} htmlFor="fullName">Name</label>
            <input
              id="fullName"
              style={s.input}
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              placeholder="Materia User"
            />
          </>
        )}

        <label style={s.label} htmlFor="email">Email</label>
        <input
          id="email"
          style={s.input}
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@lab.edu"
          required
        />

        <label style={s.label} htmlFor="password">Password</label>
        <input
          id="password"
          style={s.input}
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder={mode === 'signup' ? 'At least 8 characters' : 'Your password'}
          minLength={mode === 'signup' ? 8 : 1}
          required
        />

        <button style={s.button(loading)} disabled={loading}>
          {loading ? 'Please wait…' : mode === 'signup' ? 'Create account' : 'Sign in'}
        </button>

        <div style={s.note}>
          Seeing <strong>401 Unauthorized</strong> means the backend is protected and the browser needs a login token. Create an account once, then use that account for local development.
        </div>
      </form>
    </div>
  )
}
