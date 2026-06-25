import { useEffect, useState } from 'react'
import { listKeys, saveApiKey, deleteKey } from '../../api/keys'

// Provider catalogue. `level` drives the Required / Recommended / Optional pill
// and the onboarding priority. Keep copy short — the goal is a first-time user
// gets their keys in without leaving this panel.
const PROVIDERS = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    level: 'required',
    purpose: 'Powers the AI chat — Materia can’t answer without an LLM key.',
    unlocks: 'AI chat, tool-calling, simulation planning.',
    url: 'https://aistudio.google.com/apikey',
    info: 'Free tier from Google AI Studio (Gemini 2.5 Flash). Materia’s default chat provider.',
    steps: ['Sign in at aistudio.google.com', 'Open “API keys”', 'Create key → copy it'],
  },
  {
    id: 'mp',
    name: 'Materials Project',
    level: 'recommended',
    purpose: 'Lets Materia look up real crystal structures by formula or property.',
    unlocks: 'Materials search, structure fetch by formula / mp-id.',
    url: 'https://next-gen.materialsproject.org/api',
    info: 'Free academic database of computed materials. Needed for search tools.',
    steps: ['Sign in at materialsproject.org', 'Open the API page', 'Copy your API key'],
  },
  {
    id: 'groq',
    name: 'Groq',
    level: 'optional',
    purpose: 'A backup chat model — used automatically if Gemini is rate-limited.',
    unlocks: 'Fallback AI chat when Gemini is unavailable.',
    url: 'https://console.groq.com/keys',
    info: 'Free, fast hosted LLM (Llama 3.3). Optional resilience, not required.',
    steps: ['Sign in at console.groq.com', 'Open “API Keys”', 'Create key → copy it'],
  },
]

const LEVEL = {
  required:    { label: 'Required',    bg: 'var(--status-fail-bg)', fg: 'var(--danger-fg)', bd: 'var(--status-fail-bd)' },
  recommended: { label: 'Recommended', bg: 'var(--accent-blue)', fg: 'var(--accent-blue-dark)', bd: 'var(--accent-blue-border)' },
  optional:    { label: 'Optional',    bg: 'var(--hover-bg)', fg: 'var(--text-muted)', bd: 'var(--border)' },
}

export default function SettingsPanel({ onClose }) {
  const [status, setStatus] = useState({})
  const [loading, setLoading] = useState(true)
  const [showHow, setShowHow] = useState(false)

  async function refresh() {
    try {
      const rows = await listKeys()
      const map = {}
      for (const r of rows) map[r.service] = r.exists
      setStatus(map)
    } catch {
      /* leave status as-is; rows just show "not set" */
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div style={s.overlay} onMouseDown={onClose}>
      <div style={s.panel} onMouseDown={(e) => e.stopPropagation()}>
        {/* ── header ── */}
        <div style={s.header}>
          <div>
            <div style={s.title}>API Keys</div>
            <div style={s.subtitle}>
              Materia runs on <strong>your own</strong> keys — they’re encrypted at rest and never shown again.
            </div>
          </div>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)"
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--hover-bg)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'none'}>✕</button>
        </div>

        <div style={s.body}>
          {/* ── onboarding card ── */}
          <div style={s.onboard}>
            <div style={s.onboardTitle}>👋 New to Materia?</div>
            <ol style={s.onboardList}>
              <li>Add a <strong>Gemini</strong> key for AI chat.</li>
              <li>Add a <strong>Materials Project</strong> key for materials search.</li>
              <li>Optionally add a <strong>Groq</strong> key as a backup model.</li>
            </ol>
          </div>

          {/* ── how-to (collapsible) ── */}
          <div style={s.howCard}>
            <button style={s.howToggle} onClick={() => setShowHow((v) => !v)}>
              <span>How to get an API key</span>
              <span style={{ color: 'var(--text-muted)' }}>{showHow ? '▾' : '▸'}</span>
            </button>
            {showHow && (
              <ol style={s.howList}>
                <li>Create a free account with the provider (link below each card).</li>
                <li>Open the provider’s dashboard / API page.</li>
                <li>Generate a new API key.</li>
                <li>Copy the key.</li>
                <li>Paste it into the field below.</li>
                <li>Click <strong>Save</strong> (or <strong>Replace</strong>).</li>
              </ol>
            )}
          </div>

          {/* ── provider cards ── */}
          {PROVIDERS.map((p) => (
            <ProviderCard
              key={p.id}
              p={p}
              isSet={!!status[p.id]}
              loading={loading}
              onChanged={refresh}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function ProviderCard({ p, isSet, loading, onChanged }) {
  const [value, setValue] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)
  const lvl = LEVEL[p.level]

  async function handleSave() {
    if (!value.trim() || busy) return
    setBusy(true); setError(null); setSaved(false)
    try {
      await saveApiKey(p.id, value.trim())
      setValue(''); setSaved(true)
      await onChanged()
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err.message || 'Could not save key')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove() {
    if (busy) return
    setBusy(true); setError(null)
    try {
      await deleteKey(p.id)
      await onChanged()
    } catch (err) {
      setError(err.message || 'Could not remove key')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={s.card}>
      {/* title row */}
      <div style={s.cardHead}>
        <span style={s.svcName}>{p.name}</span>
        <span style={s.info} title={p.info}>ⓘ</span>
        <span style={{ ...s.levelPill, background: lvl.bg, color: lvl.fg, borderColor: lvl.bd }}>
          {lvl.label}
        </span>
        <span style={isSet ? s.badgeOn : s.badgeOff} title={isSet ? 'A key is saved' : 'No key yet'}>
          {loading ? '…' : isSet ? '✓ Connected' : '○ Not set'}
        </span>
      </div>

      <div style={s.purpose}>{p.purpose}</div>

      {/* empty-state vs unlocks */}
      {!isSet ? (
        <div style={s.emptyHint}>
          <strong>Why add this?</strong> Unlocks {p.unlocks}
        </div>
      ) : (
        <div style={s.setHint}>Active — unlocks {p.unlocks}</div>
      )}

      {/* get-key + mini steps */}
      <div style={s.getRow}>
        <a href={p.url} target="_blank" rel="noreferrer" style={s.getBtn}
          onMouseEnter={(e) => e.currentTarget.style.background = 'var(--accent-blue-border)'}
          onMouseLeave={(e) => e.currentTarget.style.background = 'var(--accent-blue)'}>
          ↗ Get API Key
        </a>
        <span style={s.miniSteps}>{p.steps.join('  →  ')}</span>
      </div>

      {/* input + actions */}
      <div style={s.inputRow}>
        <div style={s.inputWrap}>
          <input
            type={show ? 'text' : 'password'}
            style={s.input}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            placeholder={isSet ? 'Paste a new key to replace…' : `Paste your ${p.name} key here…`}
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            style={s.eyeBtn}
            onClick={() => setShow((v) => !v)}
            title={show ? 'Hide key' : 'Show key'}
            tabIndex={-1}
          >
            {show ? '🙈' : '👁'}
          </button>
        </div>
        <button style={s.saveBtn(!value.trim() || busy)} onClick={handleSave} disabled={!value.trim() || busy}>
          {busy ? '…' : isSet ? 'Replace' : 'Save'}
        </button>
        {isSet && (
          <button style={s.removeBtn} onClick={handleRemove} disabled={busy} title="Remove this key">
            Remove
          </button>
        )}
      </div>

      {saved && <div style={s.okMsg}>✓ Key saved securely.</div>}
      {error && <div style={s.errMsg}>⚠ {error}</div>}
    </div>
  )
}

const s = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(26,26,26,0.38)',
    backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, padding: '16px',
  },
  panel: {
    width: '620px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto',
    background: 'var(--bg-chat)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', boxShadow: '0 24px 70px rgba(0,0,0,0.22)',
    fontFamily: 'var(--font)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: '12px', padding: '20px 22px 16px', borderBottom: '1px solid var(--border-light)',
    position: 'sticky', top: 0, background: 'var(--bg-chat)', zIndex: 2,
    borderTopLeftRadius: 'var(--radius-lg)', borderTopRightRadius: 'var(--radius-lg)',
  },
  title: { fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' },
  subtitle: { fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '5px', lineHeight: 1.5, maxWidth: '440px' },
  closeBtn: {
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    fontSize: '15px', padding: '6px 9px', borderRadius: 'var(--radius-sm)', lineHeight: 1,
    transition: 'background 0.12s',
  },
  body: { padding: '16px 22px 24px', display: 'flex', flexDirection: 'column', gap: '14px' },

  onboard: {
    background: 'var(--accent-blue)', border: '1px solid var(--accent-blue-border)',
    borderRadius: 'var(--radius-md)', padding: '13px 16px',
  },
  onboardTitle: { fontSize: '13px', fontWeight: 600, color: 'var(--accent-blue-dark)', marginBottom: '6px' },
  onboardList: { margin: 0, paddingLeft: '18px', fontSize: '12.5px', color: 'var(--accent-blue-dark)', lineHeight: 1.7 },

  howCard: { border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', background: 'var(--bg-sidebar)' },
  howToggle: {
    width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    background: 'none', border: 'none', cursor: 'pointer', padding: '11px 14px',
    fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font)',
  },
  howList: { margin: 0, padding: '0 18px 14px 34px', fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.7 },

  card: {
    border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
    padding: '15px 16px', background: 'var(--bg-chat)',
  },
  cardHead: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' },
  svcName: { fontSize: '14.5px', fontWeight: 600, color: 'var(--text-primary)' },
  info: { fontSize: '12px', color: 'var(--text-muted)', cursor: 'help' },
  levelPill: {
    fontSize: '10.5px', fontWeight: 600, padding: '2px 9px', borderRadius: '20px',
    border: '1px solid', letterSpacing: '0.02em',
  },
  badgeOn: { marginLeft: 'auto', fontSize: '11.5px', fontWeight: 600, color: 'var(--status-ok-fg)' },
  badgeOff: { marginLeft: 'auto', fontSize: '11.5px', color: 'var(--text-muted)' },

  purpose: { fontSize: '12.5px', color: 'var(--text-secondary)', margin: '8px 0 6px', lineHeight: 1.5 },
  emptyHint: {
    fontSize: '12px', color: 'var(--status-queued-fg)', background: 'var(--status-queued-bg)', border: '1px solid var(--status-queued-bd)',
    borderRadius: 'var(--radius-sm)', padding: '8px 11px', marginBottom: '10px', lineHeight: 1.5,
  },
  setHint: { fontSize: '12px', color: 'var(--status-ok-fg)', marginBottom: '10px' },

  getRow: { display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' },
  getBtn: {
    display: 'inline-flex', alignItems: 'center', gap: '5px', textDecoration: 'none',
    background: 'var(--accent-blue)', color: 'var(--accent-blue-dark)', fontWeight: 600,
    fontSize: '12px', padding: '6px 12px', borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--accent-blue-border)', whiteSpace: 'nowrap', transition: 'background 0.12s',
  },
  miniSteps: { fontSize: '11px', color: 'var(--text-muted)' },

  inputRow: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' },
  inputWrap: { position: 'relative', flex: 1, minWidth: '180px' },
  input: {
    width: '100%', padding: '9px 38px 9px 12px', background: 'var(--bg-page)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    color: 'var(--text-primary)', fontSize: '13px', outline: 'none',
    fontFamily: 'ui-monospace, monospace', boxSizing: 'border-box',
  },
  eyeBtn: {
    position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)',
    background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', padding: '4px', lineHeight: 1,
  },
  saveBtn: (disabled) => ({
    padding: '9px 18px', borderRadius: 'var(--radius-sm)',
    background: disabled ? 'var(--bg-sidebar)' : 'var(--accent-solid)',
    border: `1px solid ${disabled ? 'var(--border)' : 'var(--accent-solid)'}`,
    color: disabled ? 'var(--text-muted)' : 'var(--accent-solid-fg)',
    fontSize: '13px', fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
    whiteSpace: 'nowrap', fontFamily: 'var(--font)', transition: 'all 0.12s',
  }),
  removeBtn: {
    padding: '9px 14px', borderRadius: 'var(--radius-sm)', background: 'none',
    border: '1px solid var(--status-fail-bd)', color: 'var(--danger-fg)', fontSize: '13px', cursor: 'pointer',
    whiteSpace: 'nowrap', fontFamily: 'var(--font)',
  },
  okMsg: { fontSize: '12px', color: 'var(--status-ok-fg)', marginTop: '9px' },
  errMsg: { fontSize: '12px', color: 'var(--danger-fg)', marginTop: '9px' },
}
