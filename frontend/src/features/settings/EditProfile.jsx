import { useEffect, useState } from 'react'
import { Camera, X } from 'lucide-react'
import { updateProfile } from '../../api'

/**
 * "Edit profile" modal (opened from the sidebar profile menu).
 * Mirrors the ChatGPT pattern: a centered card with a large avatar, an editable
 * display name, the (read-only) account email, and Cancel / Save.
 *
 *   user     — current user object ({ full_name, email, ... })
 *   onSaved  — (updatedUser) => void, called after a successful save
 *   onClose  — dismiss without saving
 */
export default function EditProfile({ user, onSaved, onClose }) {
  const [name, setName] = useState(user?.full_name || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, saving])

  const initial = (name || user?.email || 'M').trim().charAt(0).toUpperCase()
  const dirty = (name.trim() || '') !== (user?.full_name || '')

  async function handleSave() {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateProfile({ fullName: name.trim() })
      onSaved?.(updated)
      onClose()
    } catch (err) {
      setError(err.message || 'Could not save profile')
      setSaving(false)
    }
  }

  return (
    <div style={s.overlay} onMouseDown={() => { if (!saving) onClose() }}>
      <div style={s.panel} onMouseDown={(e) => e.stopPropagation()}>
        {/* header */}
        <div style={s.header}>
          <div style={s.title}>Edit profile</div>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)"
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}>
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        {/* avatar */}
        <div style={s.avatarWrap}>
          <div style={s.avatar}>
            {initial}
            <span style={s.cameraBadge} title="Avatar is generated from your name">
              <Camera size={13} strokeWidth={2} />
            </span>
          </div>
        </div>

        {/* fields */}
        <div style={s.body}>
          <label style={s.field}>
            <span style={s.label}>Display name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              maxLength={255}
              autoFocus
              style={s.input}
              onKeyDown={(e) => { if (e.key === 'Enter' && dirty) handleSave() }}
            />
          </label>

          <label style={s.field}>
            <span style={s.label}>Email</span>
            <input value={user?.email || ''} disabled style={{ ...s.input, ...s.inputDisabled }} />
          </label>

          <div style={s.hint}>Your display name is how Materia greets you across the app.</div>

          {error && <div style={s.error}>{error}</div>}
        </div>

        {/* footer */}
        <div style={s.footer}>
          <button style={s.cancelBtn} onClick={onClose} disabled={saving}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}>
            Cancel
          </button>
          <button
            style={{ ...s.saveBtn, ...((!dirty || saving) ? s.saveBtnDisabled : null) }}
            onClick={handleSave}
            disabled={!dirty || saving}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
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
    width: '460px', maxWidth: '96vw', maxHeight: '92vh', overflowY: 'auto',
    background: 'var(--bg-chat)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', boxShadow: '0 24px 70px rgba(0,0,0,0.22)',
    fontFamily: 'var(--font)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '18px 20px 4px',
  },
  title: { fontSize: '17px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' },
  closeBtn: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    padding: '6px', borderRadius: 'var(--radius-sm)', lineHeight: 1, transition: 'background 0.12s',
  },
  avatarWrap: { display: 'flex', justifyContent: 'center', padding: '14px 0 6px' },
  avatar: {
    position: 'relative', width: '92px', height: '92px', borderRadius: '50%',
    background: 'linear-gradient(135deg, #00b4a6, #0ea5e9)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '34px', fontWeight: 600, color: '#fff', userSelect: 'none',
  },
  cameraBadge: {
    position: 'absolute', right: '-2px', bottom: '-2px',
    width: '28px', height: '28px', borderRadius: '50%',
    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
    color: 'var(--text-secondary)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  body: { padding: '12px 22px 8px', display: 'flex', flexDirection: 'column', gap: '14px' },
  field: { display: 'flex', flexDirection: 'column', gap: '6px' },
  label: { fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' },
  input: {
    width: '100%', boxSizing: 'border-box', padding: '10px 12px',
    fontSize: '14px', color: 'var(--text-primary)', fontFamily: 'var(--font)',
    background: 'var(--bg-input)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', outline: 'none',
  },
  inputDisabled: { color: 'var(--text-muted)', cursor: 'not-allowed', background: 'var(--bg-page)' },
  hint: { fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 },
  error: {
    fontSize: '12.5px', color: 'var(--status-fail-fg)',
    background: 'var(--status-fail-bg)', border: '1px solid var(--status-fail-bd)',
    borderRadius: 'var(--radius-sm)', padding: '8px 10px',
  },
  footer: {
    display: 'flex', justifyContent: 'flex-end', gap: '10px',
    padding: '12px 22px 20px',
  },
  cancelBtn: {
    padding: '9px 16px', fontSize: '13.5px', fontWeight: 500, fontFamily: 'var(--font)',
    color: 'var(--text-secondary)', background: 'var(--bg-elevated)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
    cursor: 'pointer', transition: 'background 0.12s',
  },
  saveBtn: {
    padding: '9px 18px', fontSize: '13.5px', fontWeight: 600, fontFamily: 'var(--font)',
    color: 'var(--accent-solid-fg)', background: 'var(--accent-solid)',
    border: '1px solid var(--accent-solid)', borderRadius: 'var(--radius-md)',
    cursor: 'pointer', transition: 'opacity 0.12s',
  },
  saveBtnDisabled: { opacity: 0.5, cursor: 'not-allowed' },
}
