import { useEffect } from 'react'
import { Sun, Moon, Monitor, Check, X } from 'lucide-react'

// The three appearance choices shown on the Theme page. `mode` matches the
// values understood by useTheme() ('light' | 'dark' | 'system').
const OPTIONS = [
  { mode: 'light',  Icon: Sun,     name: 'Light',  desc: 'A bright theme for well-lit spaces.' },
  { mode: 'dark',   Icon: Moon,    name: 'Dark',   desc: 'Dimmed surfaces that are easy on the eyes.' },
  { mode: 'system', Icon: Monitor, name: 'System', desc: 'Follow your operating system automatically.' },
]

/**
 * Dedicated Appearance page (opened from the sidebar's "Theme" nav item).
 * Renders as a centered modal/overlay matching the Settings panel pattern.
 *
 *   mode      — current preference ('light' | 'dark' | 'system')
 *   onSelect  — (mode) => void, applies + persists the choice
 *   onClose   — dismiss the page
 */
export default function ThemePage({ mode, onSelect, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div style={s.overlay} onMouseDown={onClose}>
      <div style={s.panel} onMouseDown={(e) => e.stopPropagation()}>
        {/* header */}
        <div style={s.header}>
          <div>
            <div style={s.title}>Appearance</div>
            <div style={s.subtitle}>Choose how Materia looks across the application.</div>
          </div>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)"
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}>
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        {/* option rows */}
        <div style={s.body}>
          {OPTIONS.map(({ mode: m, Icon, name, desc }) => {
            const selected = mode === m
            return (
              <button
                key={m}
                onClick={() => onSelect(m)}
                style={{ ...s.option, ...(selected ? s.optionSelected : null) }}
                onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = 'var(--hover-bg)' }}
                onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = 'var(--bg-elevated)' }}
              >
                <span style={s.optionIcon}><Icon size={20} strokeWidth={1.75} /></span>
                <span style={s.optionText}>
                  <span style={s.optionName}>{name}</span>
                  <span style={s.optionDesc}>{desc}</span>
                </span>
                {selected && (
                  <span style={s.check}><Check size={18} strokeWidth={2.25} /></span>
                )}
              </button>
            )
          })}
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
    width: '520px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto',
    background: 'var(--bg-chat)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', boxShadow: '0 24px 70px rgba(0,0,0,0.22)',
    fontFamily: 'var(--font)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: '12px', padding: '20px 22px 16px', borderBottom: '1px solid var(--border-light)',
  },
  title: { fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' },
  subtitle: { fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '5px', lineHeight: 1.5 },
  closeBtn: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    padding: '6px', borderRadius: 'var(--radius-sm)', lineHeight: 1, transition: 'background 0.12s',
  },
  body: { padding: '16px 22px 22px', display: 'flex', flexDirection: 'column', gap: '10px' },

  option: {
    display: 'flex', alignItems: 'center', gap: '14px', width: '100%', textAlign: 'left',
    padding: '14px 16px', borderRadius: 'var(--radius-md)',
    border: '1px solid var(--border)', background: 'var(--bg-elevated)',
    cursor: 'pointer', fontFamily: 'var(--font)', transition: 'background 0.12s, border-color 0.12s',
  },
  optionSelected: {
    borderColor: 'var(--accent-solid)',
    boxShadow: '0 0 0 1px var(--accent-solid)',
    background: 'var(--bg-elevated)',
  },
  optionIcon: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '40px', height: '40px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
    background: 'var(--hover-bg)', color: 'var(--text-primary)',
  },
  optionText: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '2px' },
  optionName: { fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' },
  optionDesc: { fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.4 },
  check: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: 'var(--accent-solid)', flexShrink: 0,
  },
}
