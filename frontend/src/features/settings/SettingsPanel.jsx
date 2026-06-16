import { useEffect, useState } from 'react'
import { listKeys, saveApiKey, deleteKey } from '../../api/keys'

// The key slots Materia actually uses. LLM = at least one of Groq/Gemini.
const SERVICES = [
  {
    id: 'groq',
    name: 'Groq',
    tag: 'LLM · primary',
    url: 'https://console.groq.com/keys',
    hint: 'Free & fast — the default chat provider. Add this to start chatting.',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    tag: 'LLM · fallback',
    url: 'https://aistudio.google.com/apikey',
    hint: 'Free alternative chat provider (used if Groq is unavailable).',
  },
  {
    id: 'mp',
    name: 'Materials Project',
    tag: 'materials search',
    url: 'https://next-gen.materialsproject.org/api',
    hint: 'Required for searching materials by formula / properties.',
  },
]

export default function SettingsPanel({ onClose }) {
  const [status, setStatus] = useState({})   // { service: true/false }
  const [loading, setLoading] = useState(true)

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

  // close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div style={s.overlay} onMouseDown={onClose}>
      <div style={s.panel} onMouseDown={(e) => e.stopPropagation()}>
        <div style={s.header}>
          <div>
            <div style={s.title}>Settings — API Keys</div>
            <div style={s.subtitle}>
              Materia uses <strong>your own</strong> API keys. They're encrypted at rest and never shown again.
            </div>
          </div>
          <button style={s.closeBtn} onClick={onClose} title="Close">✕</button>
        </div>

        <div style={s.body}>
          {SERVICES.map((svc) => (
            <KeyRow
              key={svc.id}
              svc={svc}
              isSet={!!status[svc.id]}
              loading={loading}
              onChanged={refresh}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function KeyRow({ svc, isSet, loading, onChanged }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function handleSave() {
    if (!value.trim() || busy) return
    setBusy(true); setError(null)
    try {
      await saveApiKey(svc.id, value.trim())
      setValue('')
      await onChanged()
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
      await deleteKey(svc.id)
      await onChanged()
    } catch (err) {
      setError(err.message || 'Could not remove key')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={s.row}>
      <div style={s.rowHead}>
        <span style={s.svcName}>{svc.name}</span>
        <span style={s.tag}>{svc.tag}</span>
        <span style={isSet ? s.badgeOn : s.badgeOff}>
          {loading ? '…' : isSet ? '✓ set' : 'not set'}
        </span>
      </div>
      <div style={s.hint}>{svc.hint}</div>
      <a href={svc.url} target="_blank" rel="noreferrer" style={s.link}>↗ Get your free key</a>

      <div style={s.inputRow}>
        <input
          type="password"
          style={s.input}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          placeholder={isSet ? 'Paste a new key to replace…' : `Paste your ${svc.name} key…`}
        />
        <button style={s.saveBtn(!value.trim() || busy)} onClick={handleSave} disabled={!value.trim() || busy}>
          {busy ? '…' : isSet ? 'replace' : 'save'}
        </button>
        {isSet && (
          <button style={s.removeBtn} onClick={handleRemove} disabled={busy} title="Remove key">
            remove
          </button>
        )}
      </div>
      {error && <div style={s.error}>⚠ {error}</div>}
    </div>
  )
}

const s = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
  },
  panel: {
    width: '560px', maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto',
    background: '#0d1520', border: '1px solid #1a3050', borderRadius: '14px',
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: '12px', padding: '18px 20px', borderBottom: '1px solid #14253c',
  },
  title: { fontSize: '16px', fontWeight: 600, color: '#cfe3ff' },
  subtitle: { fontSize: '12px', color: '#5b7a9c', marginTop: '4px', lineHeight: 1.5, maxWidth: '420px' },
  closeBtn: {
    background: 'none', border: 'none', color: '#5b7a9c', cursor: 'pointer',
    fontSize: '16px', padding: '4px 8px', borderRadius: '6px',
  },
  body: { padding: '8px 20px 20px' },
  row: { padding: '16px 0', borderBottom: '1px solid #122035' },
  rowHead: { display: 'flex', alignItems: 'center', gap: '10px' },
  svcName: { fontSize: '14px', fontWeight: 500, color: '#a0c4ff' },
  tag: { fontSize: '11px', color: '#456', background: '#0a1018', padding: '2px 8px', borderRadius: '10px' },
  badgeOn: { marginLeft: 'auto', fontSize: '11px', color: '#4aaa6a' },
  badgeOff: { marginLeft: 'auto', fontSize: '11px', color: '#86603a' },
  hint: { fontSize: '12px', color: '#557', margin: '6px 0 4px', lineHeight: 1.5 },
  link: { color: '#5090c0', fontSize: '12px', display: 'inline-block', marginBottom: '10px' },
  inputRow: { display: 'flex', gap: '8px', alignItems: 'center' },
  input: {
    flex: 1, padding: '8px 12px', background: '#0a1018', border: '1px solid #1a3050',
    borderRadius: '8px', color: '#a0c4ff', fontSize: '13px', outline: 'none', fontFamily: 'monospace',
  },
  saveBtn: (disabled) => ({
    padding: '8px 16px', borderRadius: '8px',
    background: disabled ? '#0a1018' : '#1c3558',
    border: `1px solid ${disabled ? '#1a2a3a' : '#274878'}`,
    color: disabled ? '#2a4a6a' : '#a0c4ff',
    fontSize: '13px', cursor: disabled ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
  }),
  removeBtn: {
    padding: '8px 12px', borderRadius: '8px', background: 'none',
    border: '1px solid #5a2a2a', color: '#c06868', fontSize: '13px', cursor: 'pointer', whiteSpace: 'nowrap',
  },
  error: { fontSize: '12px', color: '#e07070', marginTop: '8px' },
}
