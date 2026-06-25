import { useEffect } from 'react'
import { X, MessageSquarePlus, Upload, Box, Wrench, Keyboard, Mail } from 'lucide-react'

// Quick orientation shown from the sidebar profile menu → "Help".
const TIPS = [
  { Icon: MessageSquarePlus, title: 'Start a chat', desc: 'Ask Materia to generate VASP inputs, build structures, or run an MLP simulation in plain English.' },
  { Icon: Upload, title: 'Upload structures', desc: 'Use the + in the message box to attach a POSCAR, CIF, INCAR or other structure file.' },
  { Icon: Box, title: 'Visualize', desc: 'Open the structure viewer from the sidebar to inspect crystals (VESTA-style).' },
  { Icon: Wrench, title: 'Tools & jobs', desc: 'Launch tools manually and track long-running simulations from the right panel.' },
  { Icon: Keyboard, title: 'Shortcuts', desc: 'Enter sends a message · Shift + Enter adds a new line · Esc closes dialogs.' },
]

/**
 * Help / getting-started panel. Centered modal matching the other dialogs.
 *   onClose — dismiss
 */
export default function HelpPanel({ onClose }) {
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
            <div style={s.title}>Help & tips</div>
            <div style={s.subtitle}>A quick tour of what Materia can do.</div>
          </div>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)"
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}>
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        <div style={s.body}>
          {TIPS.map(({ Icon, title, desc }) => (
            <div key={title} style={s.row}>
              <span style={s.iconChip}><Icon size={18} strokeWidth={1.75} /></span>
              <span style={s.rowText}>
                <span style={s.rowTitle}>{title}</span>
                <span style={s.rowDesc}>{desc}</span>
              </span>
            </div>
          ))}

          <a href="mailto:support@materia.app" style={s.contact}>
            <Mail size={16} strokeWidth={1.75} />
            Contact support
          </a>
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
    width: '500px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto',
    background: 'var(--bg-chat)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', boxShadow: '0 24px 70px rgba(0,0,0,0.22)',
    fontFamily: 'var(--font)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: '12px', padding: '20px 22px 14px', borderBottom: '1px solid var(--border-light)',
  },
  title: { fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' },
  subtitle: { fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '5px' },
  closeBtn: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    padding: '6px', borderRadius: 'var(--radius-sm)', lineHeight: 1, transition: 'background 0.12s',
  },
  body: { padding: '14px 22px 22px', display: 'flex', flexDirection: 'column', gap: '12px' },
  row: { display: 'flex', alignItems: 'flex-start', gap: '13px' },
  iconChip: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '36px', height: '36px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
    background: 'var(--hover-bg)', color: 'var(--text-primary)',
  },
  rowText: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 },
  rowTitle: { fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)' },
  rowDesc: { fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.45 },
  contact: {
    display: 'inline-flex', alignItems: 'center', gap: '8px', marginTop: '4px',
    fontSize: '13px', fontWeight: 500, color: 'var(--accent-solid)',
    textDecoration: 'none',
  },
}
