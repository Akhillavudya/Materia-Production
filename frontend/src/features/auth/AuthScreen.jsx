import { useEffect, useRef, useState } from 'react'
import { getAuthConfig, googleLogin, login, signup } from '../../api'
import Logo from '../../components/Logo'
import { loadGoogleIdentity } from './googleIdentity'
import './Auth.css'

// Real, verifiable product capabilities (no fake stats / testimonials)
const FEATS = [
  'Search materials across Materials Project, C2DB & OQMD',
  'Auto-generate VASP input files from a single sentence',
  'Run structure optimization & molecular dynamics as background jobs',
]

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  )
}

export default function AuthScreen({ onAuthenticated, initialError = null, onBack = null }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [signupMode, setSignupMode] = useState('open')
  const [googleClientId, setGoogleClientId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(initialError)
  const [info, setInfo] = useState(null)

  const googleBtnRef = useRef(null)
  // Keep the latest auth handler in a ref so the GIS callback (registered once)
  // always calls the current closure.
  const onAuthRef = useRef(onAuthenticated)
  useEffect(() => { onAuthRef.current = onAuthenticated }, [onAuthenticated])

  useEffect(() => { setError(initialError) }, [initialError])

  // Ask the backend how signup is gated and whether Google sign-in is configured.
  useEffect(() => {
    getAuthConfig()
      .then(c => {
        setSignupMode(c?.signup_mode || 'open')
        if (c?.google_enabled && c?.google_client_id) setGoogleClientId(c.google_client_id)
      })
      .catch(() => {})
  }, [])

  // When Google is configured, load GIS and render the official button.
  useEffect(() => {
    if (!googleClientId || !googleBtnRef.current) return
    let cancelled = false

    async function handleCredential(response) {
      if (!response?.credential) return
      setError(null); setInfo(null); setLoading(true)
      try {
        const user = await googleLogin(response.credential)
        onAuthRef.current?.(user)
      } catch (err) {
        setError(err.message || 'Could not sign in with Google')
      } finally {
        setLoading(false)
      }
    }

    loadGoogleIdentity()
      .then(google => {
        if (cancelled || !googleBtnRef.current) return
        google.accounts.id.initialize({
          client_id: googleClientId,
          callback: handleCredential,
        })
        googleBtnRef.current.innerHTML = ''
        google.accounts.id.renderButton(googleBtnRef.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          shape: 'pill',
          text: mode === 'signup' ? 'signup_with' : 'continue_with',
          logo_alignment: 'center',
          width: Math.min(Math.max(googleBtnRef.current.offsetWidth || 320, 200), 400),
        })
      })
      .catch(() => {
        if (!cancelled) setInfo('Google sign-in could not load. Please use your email below.')
      })

    return () => { cancelled = true }
  }, [googleClientId, mode])

  function switchMode(next) {
    setMode(next)
    setError(null)
    setInfo(null)
  }

  function handleGoogleDisabled() {
    // Shown only when GOOGLE_CLIENT_ID is not configured on the server.
    setError(null)
    setInfo('Google sign-in is not configured on this server. Continue with your email below.')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (loading) return
    setLoading(true)
    setError(null)
    setInfo(null)
    try {
      const user = mode === 'signup'
        ? await signup(email.trim(), password, fullName.trim(), inviteCode.trim())
        : await login(email.trim(), password)
      onAuthenticated(user)
    } catch (err) {
      setError(err.message || 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  const isSignup = mode === 'signup'

  return (
    <div className="auth">
      {/* ── left brand panel ── */}
      <aside className="auth-brand">
        <div className="auth-brand-top">
          <Logo size={34} color="#ffffff" />
        </div>

        <div className="auth-brand-mid">
          {isSignup ? (
            <h2>Start your materials<br />research <span className="soft">in minutes.</span></h2>
          ) : (
            <h2>The AI that speaks<br />materials science <span className="soft">fluently.</span></h2>
          )}
          <p className="auth-brand-sub">
            Materia turns expert-only computational materials workflows into a simple conversation —
            discover, simulate, and analyze, all from chat.
          </p>
          <ul className="auth-feats">
            {FEATS.map(f => (
              <li key={f}><span className="auth-check">✓</span>{f}</li>
            ))}
          </ul>
        </div>

        <div className="auth-brand-foot">Free to start · Powered by Gemini · No setup required</div>
      </aside>

      {/* ── right form panel ── */}
      <main className="auth-side">
        <form className="auth-card" onSubmit={handleSubmit}>
          {onBack && (
            <button type="button" className="auth-back" onClick={onBack}>← Back to home</button>
          )}

          <h1 className="auth-title">{isSignup ? 'Create your account' : 'Welcome back'}</h1>
          <p className="auth-lede">
            {isSignup
              ? 'Set up your Materia account to start running materials research.'
              : 'Sign in to your Materia account to continue your research.'}
          </p>

          {googleClientId ? (
            // Official Google Identity Services button (renders into this div).
            <div ref={googleBtnRef} className="auth-gbtn" />
          ) : (
            <button type="button" className="auth-oauth" onClick={handleGoogleDisabled}>
              <GoogleIcon />
              Continue with Google
            </button>
          )}

          <div className="auth-divider">OR</div>

          {error && <div className="auth-msg auth-msg-error">{error}</div>}
          {info && <div className="auth-msg auth-msg-info">{info}</div>}

          {isSignup && (
            <>
              <label className="auth-label" htmlFor="fullName">Name</label>
              <input
                id="fullName"
                className="auth-input"
                value={fullName}
                onChange={e => setFullName(e.target.value)}
                placeholder="Your name"
              />
            </>
          )}

          <label className="auth-label" htmlFor="email">Email</label>
          <input
            id="email"
            className="auth-input"
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@lab.edu"
            required
          />

          <label className="auth-label" htmlFor="password">Password</label>
          <input
            id="password"
            className="auth-input"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={isSignup ? 'At least 12 characters' : 'Your password'}
            minLength={isSignup ? 12 : 1}
            required
          />

          {isSignup && signupMode === 'invite' && (
            <>
              <label className="auth-label" htmlFor="inviteCode">Invite code</label>
              <input
                id="inviteCode"
                className="auth-input"
                value={inviteCode}
                onChange={e => setInviteCode(e.target.value)}
                placeholder="Code from your lab admin"
                required
              />
            </>
          )}

          <button className="auth-submit" disabled={loading}>
            {loading ? 'Please wait…' : isSignup ? 'Create account' : 'Sign in'}
          </button>

          <div className="auth-switch">
            {isSignup ? (
              <>Already have an account? <button type="button" onClick={() => switchMode('login')}>Sign in</button></>
            ) : signupMode === 'closed' ? (
              <span className="auth-switch-muted">Accounts are created by your lab admin.</span>
            ) : (
              <>New to Materia? <button type="button" onClick={() => switchMode('signup')}>
                {signupMode === 'invite' ? 'Register with an invite code' : 'Create one free'}
              </button></>
            )}
          </div>
        </form>
      </main>
    </div>
  )
}
