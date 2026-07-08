import { useEffect } from 'react'
import {
  X, Mail, Sparkles, KeyRound, Search, Layers, FileCog,
  Atom, Activity, Upload, Box, Wrench, Keyboard,
} from 'lucide-react'

// Grouped getting-started guide shown from the sidebar profile menu → "Help".
const SECTIONS = [
  {
    heading: 'Getting started',
    rows: [
      { Icon: KeyRound, title: 'Add your API key', desc: 'Open Settings → API keys and paste a free Gemini API key. Materia uses it to power the AI agent. You can add several keys per provider — they rotate automatically to dodge rate limits.' },
      { Icon: Sparkles, title: 'Just ask in plain English', desc: 'Describe your goal and the agent decides which tools to run. It proposes a plan for multi-step tasks, then streams progress back to you live.' },
      { Icon: Upload, title: 'Upload structures', desc: 'Use the + in the message box to attach a POSCAR, CIF, INCAR or other file, then reference it in your prompt.' },
    ],
  },
  {
    heading: 'What Materia can do',
    rows: [
      { Icon: Search, title: 'Search materials', desc: 'Find candidates across Materials Project, C2DB and OQMD by formula, elements, band gap or dimensionality.' },
      { Icon: Layers, title: 'Build & edit crystals', desc: 'Supercells, slabs, vacuum, vacancies, substitutions, interstitials, adsorbates, symmetry analysis and random-alloy SQS.' },
      { Icon: FileCog, title: 'Generate VASP inputs', desc: 'Complete POSCAR + INCAR + KPOINTS + POTCAR sets for static, relaxation, band, DOS, AIMD, elastic, phonon and more.' },
      { Icon: Atom, title: 'Optimize with ML potentials', desc: 'Relax structures with MACE / MatterSim potentials as background jobs — no DFT wait.' },
      { Icon: Activity, title: 'Simulate & compute', desc: 'Molecular dynamics (NVE/NVT), elastic tensor & moduli, phonon spectra, and NEB migration barriers.' },
    ],
  },
  {
    heading: 'Working with results',
    rows: [
      { Icon: Box, title: 'Visualize', desc: 'Open the VESTA-style structure viewer from the sidebar to inspect crystals, coordination polyhedra and supercells.' },
      { Icon: Wrench, title: 'Tools & jobs', desc: 'Launch tools manually and track long-running simulations from the right panel; results land back in the chat.' },
      { Icon: Keyboard, title: 'Shortcuts', desc: 'Enter sends · Shift + Enter adds a new line · Esc closes dialogs.' },
    ],
  },
]

// A few copy-and-tweak prompts to get people going.
const EXAMPLES = [
  'Find a 2D semiconductor with a band gap between 1 and 2 eV.',
  'Generate VASP relaxation inputs for silicon.',
  'Build a 2×2 Cu(111) slab, 4 layers, and add a CO adsorbate.',
  'Relax MoS₂ with an ML potential.',
  'Compute the NEB migration barrier for Li in the uploaded structure.',
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
            <div style={s.title}>Help & instructions</div>
            <div style={s.subtitle}>How to get the most out of Materia.</div>
          </div>
          <button style={s.closeBtn} onClick={onClose} title="Close (Esc)"
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}>
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        <div style={s.body}>
          {SECTIONS.map(({ heading, rows }) => (
            <div key={heading} style={s.section}>
              <div style={s.sectionHeading}>{heading}</div>
              {rows.map(({ Icon, title, desc }) => (
                <div key={title} style={s.row}>
                  <span style={s.iconChip}><Icon size={18} strokeWidth={1.75} /></span>
                  <span style={s.rowText}>
                    <span style={s.rowTitle}>{title}</span>
                    <span style={s.rowDesc}>{desc}</span>
                  </span>
                </div>
              ))}
            </div>
          ))}

          <div style={s.section}>
            <div style={s.sectionHeading}>Try asking</div>
            <div style={s.examples}>
              {EXAMPLES.map((ex) => (
                <span key={ex} style={s.example}>“{ex}”</span>
              ))}
            </div>
          </div>

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
    width: '560px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto',
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
  body: { padding: '14px 22px 22px', display: 'flex', flexDirection: 'column', gap: '18px' },
  section: { display: 'flex', flexDirection: 'column', gap: '12px' },
  sectionHeading: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
    color: 'var(--text-muted)',
  },
  row: { display: 'flex', alignItems: 'flex-start', gap: '13px' },
  iconChip: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: '36px', height: '36px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
    background: 'var(--hover-bg)', color: 'var(--text-primary)',
  },
  rowText: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 },
  rowTitle: { fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)' },
  rowDesc: { fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.45 },
  examples: { display: 'flex', flexDirection: 'column', gap: '7px' },
  example: {
    fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: 1.4,
    padding: '8px 11px', borderRadius: 'var(--radius-sm)',
    background: 'var(--hover-bg)', border: '1px solid var(--border-light)',
  },
  contact: {
    display: 'inline-flex', alignItems: 'center', gap: '8px', marginTop: '4px',
    fontSize: '13px', fontWeight: 500, color: 'var(--accent-solid)',
    textDecoration: 'none',
  },
}
