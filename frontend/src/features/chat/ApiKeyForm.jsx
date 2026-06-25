import { useState } from 'react'
import { saveApiKey } from '../../api'

const SERVICE_INFO = {
  gemini: {
    name: 'Google Gemini',
    url: 'https://aistudio.google.com/apikey',
    placeholder: 'Paste your Gemini API key here…',
    hint: 'Free — the default chat provider. Create a key at aistudio.google.com → API keys.',
  },
  groq: {
    name: 'Groq',
    url: 'https://console.groq.com/keys',
    placeholder: 'Paste your Groq API key here…',
    hint: 'Free & fast — optional backup chat provider. Create a key at console.groq.com.',
  },
  mp: {
    name: 'Materials Project',
    url: 'https://next-gen.materialsproject.org/api',
    placeholder: 'Paste your MP API key here…',
    hint: 'Free account required. Get your key at materialsproject.org → API.',
  },
}

const s = {
  card: {
    marginTop: '10px',
    background: '#0d1520',
    border: '1px solid #1a3050',
    borderRadius: '12px',
    padding: '16px',
    maxWidth: '82%',
  },
  title: {
    fontSize: '13px',
    fontWeight: '500',
    color: '#a0c4ff',
    marginBottom: '4px',
  },
  hint: {
    fontSize: '12px',
    color: '#406080',
    marginBottom: '12px',
    lineHeight: '1.5',
  },
  link: {
    color: '#5090c0',
    fontSize: '12px',
    display: 'inline-block',
    marginBottom: '12px',
  },
  inputRow: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    padding: '8px 12px',
    background: '#0a1018',
    border: '1px solid #1a3050',
    borderRadius: '8px',
    color: '#a0c4ff',
    fontSize: '13px',
    outline: 'none',
    fontFamily: 'monospace',
    letterSpacing: '0.02em',
  },
  saveBtn: (disabled) => ({
    padding: '8px 16px',
    borderRadius: '8px',
    background: disabled ? '#0a1018' : '#1c3558',
    border: `1px solid ${disabled ? '#1a2a3a' : '#274878'}`,
    color: disabled ? '#2a4a6a' : '#a0c4ff',
    fontSize: '13px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    whiteSpace: 'nowrap',
    transition: 'all 0.15s',
  }),
  successMsg: {
    fontSize: '12px',
    color: '#4aaa6a',
    marginTop: '8px',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  errorMsg: {
    fontSize: '12px',
    color: '#e07070',
    marginTop: '8px',
  },
}

export default function ApiKeyForm({ service, onKeySaved }) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const info = SERVICE_INFO[service] || {
    name: service,
    url: '',
    placeholder: 'Paste API key…',
    hint: '',
  }

  async function handleSave() {
    if (!value.trim() || saving) return

    setSaving(true)
    setError(null)

    try {
      await saveApiKey(service, value.trim())
      setSaved(true)

      setTimeout(() => {
        if (onKeySaved) {
          onKeySaved(service, value.trim())
        }
      }, 800)
    } catch (err) {
      setError(err.message || 'Could not save API key')
    } finally {
      setSaving(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      handleSave()
    }
  }

  return (
    <div style={s.card}>
      <div style={s.title}>
        🔑 {info.name} API key required
      </div>

      <div style={s.hint}>
        {info.hint}
      </div>

      {info.url && (
        <a
          href={info.url}
          target="_blank"
          rel="noreferrer"
          style={s.link}
        >
          ↗ Get your free API key
        </a>
      )}

      {!saved ? (
        <>
          <div style={s.inputRow}>
            <input
              type="password"
              style={s.input}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={info.placeholder}
              autoFocus
            />

            <button
              style={s.saveBtn(!value.trim() || saving)}
              onClick={handleSave}
              disabled={!value.trim() || saving}
            >
              {saving ? 'saving…' : 'save & continue'}
            </button>
          </div>

          {error && (
            <div style={s.errorMsg}>
              ⚠ {error}
            </div>
          )}
        </>
      ) : (
        <div style={s.successMsg}>
          <span>✓</span>
          <span>Key saved — retrying your request…</span>
        </div>
      )}
    </div>
  )
}