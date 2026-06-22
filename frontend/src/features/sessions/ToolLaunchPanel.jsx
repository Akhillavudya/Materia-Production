/**
 * RightPanel simulation launcher — category-coded "method cards".
 *
 * Replaces the old flat WORKFLOW accordion. Each long-running tool is a card
 * with a colored left-edge rail keyed to a physics category (Structure,
 * Dynamics, Vibrational, Mechanical, Statistical, Pathway). Exactly one card is
 * open at a time. Launching posts to the matching api/tools.js endpoint (the
 * same async jobs the chat agent enqueues) and fires onLaunched() so
 * AsyncJobsPanel above refreshes. Frontend-only — no backend changes.
 */

import { useEffect, useState } from 'react'
import { TOOL_FORMS } from './toolForms'
import {
  uploadFiles, fetchSessionFilesGrouped,
  launchOptimize, launchMd, launchPhonons, launchElastic, launchSqs, launchNeb,
} from '../../api'

// ── visual tokens (theme palette for this panel) ──
const T = {
  bg: '#FAFAF8', surface: '#FFFFFF',
  ink: '#10221F', inkSoft: '#5C6864', inkFaint: '#8B9591',
  border: '#E6E4DD',
  teal: '#00B4A6', tealDeep: '#007F76', tealWash: '#E6F8F5',
}
const FONT_DISPLAY = '"DM Sans", Inter, ui-sans-serif, system-ui, sans-serif'
const FONT_BODY = 'Inter, ui-sans-serif, system-ui, sans-serif'
const FONT_MONO = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace'

// Single-file tool launchers, dispatched by endpoint name (NEB handled apart).
const LAUNCHERS = {
  optimize: launchOptimize, md: launchMd, phonons: launchPhonons,
  elastic: launchElastic, sqs: launchSqs,
}

// ── inline Tabler-style outline icons (dependency-free) ──
const ICON_PATHS = {
  optimize: ['M5 9l4 0l0 -4', 'M3 3l6 6', 'M5 15l4 0l0 4', 'M3 21l6 -6',
             'M19 9l-4 0l0 -4', 'M21 3l-6 6', 'M19 15l-4 0l0 4', 'M21 21l-6 -6'],
  phonons: ['M3 12 q3 -7 6 0 t6 0 t6 0'],
  elastic: ['M12 2 L21 7 L21 17 L12 22 L3 17 L3 7 Z',
            'M12 12 L12 22', 'M12 12 L21 7', 'M12 12 L3 7'],
  neb: ['M6 17 V14 a4 4 0 0 1 4 -4 h4 a4 4 0 0 0 4 -4'],
}
const GRAIN_DOTS = [[6, 6], [12, 5], [18, 7], [5, 12], [12, 12], [19, 12], [7, 18], [13, 18], [18, 17]]

function Icon({ name, color, size = 18 }) {
  const common = {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: color, strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round',
  }
  if (name === 'md') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="1.5" fill={color} stroke="none" />
        <ellipse cx="12" cy="12" rx="9" ry="3.6" />
        <ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)" />
        <ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(120 12 12)" />
      </svg>
    )
  }
  if (name === 'sqs') {
    return (
      <svg {...common}>
        {GRAIN_DOTS.map(([cx, cy], i) => (
          <circle key={i} cx={cx} cy={cy} r="1.1" fill={color} stroke="none" />
        ))}
      </svg>
    )
  }
  if (name === 'neb') {
    return (
      <svg {...common}>
        <circle cx="6" cy="19" r="2" />
        <circle cx="18" cy="5" r="2" />
        {ICON_PATHS.neb.map((d, i) => <path key={i} d={d} />)}
      </svg>
    )
  }
  return (
    <svg {...common}>
      {(ICON_PATHS[name] || []).map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

// ── file picker (reused from the former NebPanel) ──
const FilePick = ({ label, file, onPick, accent }) => (
  <label style={{
    flex: 1, display: 'flex', flexDirection: 'column', gap: 4,
    fontSize: 11, color: T.inkSoft, cursor: 'pointer', fontFamily: FONT_BODY,
  }}>
    <span>{label}</span>
    <div style={{
      border: `1px dashed ${file ? accent : T.border}`,
      borderRadius: 6, padding: '8px 10px', fontSize: 11,
      color: file ? T.ink : T.inkFaint,
      background: file ? `${accent}11` : 'transparent',
      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      fontFamily: FONT_MONO,
    }}>
      {file ? file.name : 'Choose file…'}
    </div>
    <input type="file" style={{ display: 'none' }}
      onChange={(e) => onPick(e.target.files?.[0] || null)} />
  </label>
)

const inputBox = {
  padding: '5px 7px', borderRadius: 6, border: `1px solid ${T.border}`,
  fontSize: 12, fontFamily: FONT_MONO, color: T.ink, background: T.surface, width: '100%',
}

function Field({ spec, value, onChange }) {
  if (spec.type === 'checkbox') {
    return (
      <label style={{ fontSize: 11, color: T.ink, display: 'flex', alignItems: 'center', gap: 6, fontFamily: FONT_BODY }}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {spec.label}
      </label>
    )
  }
  return (
    <label style={{ fontSize: 10.5, color: T.inkSoft, display: 'flex', flexDirection: 'column', gap: 3, fontFamily: FONT_BODY }}>
      {spec.label}
      {spec.type === 'select' ? (
        <select value={value} onChange={(e) => onChange(e.target.value)} style={inputBox}>
          {spec.options.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}
        </select>
      ) : spec.type === 'number' ? (
        <input type="number" value={value} min={spec.min} max={spec.max} step={spec.step}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          style={inputBox} />
      ) : (
        <input type="text" value={value} placeholder={spec.placeholder}
          onChange={(e) => onChange(e.target.value)} style={inputBox} />
      )}
    </label>
  )
}

function initialValues(spec) {
  const v = {}
  for (const f of spec.fields) v[f.name] = f.default
  return v
}

function ToolCard({ sessionId, spec, isOpen, onToggle, onLaunched }) {
  const [file, setFile] = useState(null)
  const [initial, setInitial] = useState(null)
  const [final, setFinal] = useState(null)
  const [values, setValues] = useState(() => initialValues(spec))
  const [calcType, setCalcType] = useState('mace')
  const [calcModel, setCalcModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const setField = (name, val) => setValues((p) => ({ ...p, [name]: val }))

  const run = async () => {
    setMsg(null)
    if (spec.twoFiles && (!initial || !final)) {
      setMsg({ kind: 'err', text: 'Pick both an initial and a final structure.' }); return
    }
    setBusy(true)
    try {
      let res
      if (spec.key === 'neb') {
        res = await launchNeb(sessionId, initial, final, {
          nImages: values.n_images, climb: values.climb,
          calculatorType: calcType, calculatorModel: calcModel || undefined,
        })
      } else {
        const params = { ...values }
        if (spec.calculator) {
          params.calculator_type = calcType
          if (calcModel) params.calculator_model = calcModel
        }
        res = await LAUNCHERS[spec.endpoint](sessionId, file, params)
      }
      const id = (res.job_id || '').slice(0, 8)
      setMsg({ kind: 'ok', text: `Job started${id ? ` (${id})` : ''}. Tracking above.` })
      setFile(null); setInitial(null); setFinal(null)
      onLaunched?.()
    } catch (e) {
      setMsg({ kind: 'err', text: e.message || 'Failed to start job.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      background: T.surface, border: `1px solid ${T.border}`, borderLeft: `3px solid ${spec.color}`,
      borderRadius: 8, overflow: 'hidden',
    }}>
      {/* header */}
      <button
        onClick={() => onToggle(spec.key)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 9,
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: '10px 11px', textAlign: 'left',
        }}
      >
        <span style={{ flexShrink: 0, display: 'flex' }}><Icon name={spec.icon} color={spec.color} /></span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ fontFamily: FONT_DISPLAY, fontWeight: 600, fontSize: 13, color: T.ink }}>
              {spec.label}
            </span>
            <span style={{
              fontFamily: FONT_BODY, fontSize: 9.5, fontWeight: 600, letterSpacing: '0.03em',
              textTransform: 'uppercase', color: spec.color,
              background: `${spec.color}1A`, borderRadius: 999, padding: '2px 7px',
            }}>
              {spec.category}
            </span>
          </span>
          {!isOpen && (
            <span style={{
              display: 'block', marginTop: 3, fontFamily: FONT_BODY, fontSize: 11, color: T.inkSoft,
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {spec.description}
            </span>
          )}
        </span>
        <span style={{ color: T.inkFaint, fontSize: 12, flexShrink: 0 }}>{isOpen ? '▾' : '▸'}</span>
      </button>

      {/* body */}
      {isOpen && (
        <div style={{ padding: '0 11px 12px', display: 'flex', flexDirection: 'column', gap: 11 }}>
          {/* file picker(s) */}
          {spec.twoFiles ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <FilePick label="Initial state" file={initial} onPick={setInitial} accent="#2563eb" />
              <FilePick label="Final state" file={final} onPick={setFinal} accent="#16a34a" />
            </div>
          ) : (
            <FilePick label="Structure — uses active if empty" file={file} onPick={setFile} accent={spec.color} />
          )}

          {/* param grid */}
          {spec.fields.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9, alignItems: 'end' }}>
              {spec.fields.map((f) => (
                <Field key={f.name} spec={f} value={values[f.name]} onChange={(v) => setField(f.name, v)} />
              ))}
            </div>
          )}

          {/* teal-tinted Potential row */}
          {spec.calculator && (
            <div style={{
              background: T.tealWash, border: `1px solid ${T.teal}33`, borderRadius: 6,
              padding: '8px 9px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9,
            }}>
              <label style={{ fontSize: 10.5, color: T.tealDeep, display: 'flex', flexDirection: 'column', gap: 3, fontFamily: FONT_BODY, fontWeight: 600 }}>
                Potential
                <select value={calcType} onChange={(e) => setCalcType(e.target.value)} style={inputBox}>
                  <option value="mace">MACE</option>
                  <option value="mattersim">MatterSim</option>
                </select>
              </label>
              <label style={{ fontSize: 10.5, color: T.tealDeep, display: 'flex', flexDirection: 'column', gap: 3, fontFamily: FONT_BODY, fontWeight: 600 }}>
                Model
                <input type="text" value={calcModel} placeholder="default" onChange={(e) => setCalcModel(e.target.value)} style={inputBox} />
              </label>
            </div>
          )}

          {/* run */}
          <button
            onClick={run}
            disabled={busy}
            style={{
              padding: '9px 0', borderRadius: 6, border: 'none', cursor: busy ? 'default' : 'pointer',
              background: busy ? '#9ca3af' : T.teal, color: '#fff', fontSize: 12.5, fontWeight: 600,
              fontFamily: FONT_DISPLAY,
            }}
          >
            {busy ? 'Starting…' : `Run ${spec.label}`}
          </button>

          {msg && (
            <div style={{ fontSize: 11, color: msg.kind === 'ok' ? T.tealDeep : '#b91c1c', lineHeight: 1.4, fontFamily: FONT_BODY }}>
              {msg.kind === 'ok' ? '✓ ' : '⚠ '}{msg.text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function UploadRow({ sessionId, onUploaded }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const onPick = async (e) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length) return
    setMsg(null); setBusy(true)
    try {
      const res = await uploadFiles(sessionId, files)
      const names = (res.files || []).map((f) => f.name)
      setMsg({ kind: 'ok', text: `Uploaded ${names.join(', ') || files.length + ' file(s)'}.` })
      onUploaded?.(names[0] || null)
    } catch (err) {
      setMsg({ kind: 'err', text: err.message || 'Upload failed.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        padding: '9px 0', borderRadius: 6, border: `1px dashed ${T.border}`, cursor: busy ? 'default' : 'pointer',
        fontSize: 12, fontWeight: 600, color: T.ink, fontFamily: FONT_BODY, background: T.surface,
      }}>
        {busy ? 'Uploading…' : '⬆ Upload structure'}
        <input type="file" multiple style={{ display: 'none' }} disabled={busy} onChange={onPick} />
      </label>
      {msg && (
        <div style={{ fontSize: 11, color: msg.kind === 'ok' ? T.tealDeep : '#b91c1c', lineHeight: 1.4, fontFamily: FONT_BODY }}>
          {msg.kind === 'ok' ? '✓ ' : '⚠ '}{msg.text}
        </div>
      )}
    </div>
  )
}

// Session's auto-detected active structure (the plain POSCAR/CONTCAR copy).
function detectActive(groups) {
  const files = (groups || []).flatMap((g) => g.files || [])
  const active = files.find((f) => ['POSCAR', 'CONTCAR'].includes((f.name || '').toUpperCase()))
  return active ? active.name : null
}

export default function ToolLaunchPanel({ sessionId, onLaunched, onUploaded }) {
  const [openKey, setOpenKey] = useState(null)
  const [detectedName, setDetectedName] = useState(null)
  const [uploadedName, setUploadedName] = useState(null)

  // Detect the active structure on mount / session change.
  useEffect(() => {
    let alive = true
    setUploadedName(null)
    if (!sessionId) { setDetectedName(null); return }
    fetchSessionFilesGrouped(sessionId)
      .then((data) => { if (alive) setDetectedName(detectActive(data.groups || [])) })
      .catch(() => { if (alive) setDetectedName(null) })
    return () => { alive = false }
  }, [sessionId])

  if (!sessionId) return null

  const activeName = uploadedName || detectedName
  const toggle = (key) => setOpenKey((cur) => (cur === key ? null : key))
  const handleUploaded = (name) => { if (name) setUploadedName(name); onUploaded?.() }

  return (
    <div style={{
      borderTop: `1px solid ${T.border}`, flexShrink: 0, background: T.bg,
      padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 11,
    }}>
      {/* section header + active structure */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span style={{
          fontFamily: FONT_DISPLAY, fontSize: 11.5, fontWeight: 700, letterSpacing: '0.04em',
          textTransform: 'uppercase', color: T.inkSoft,
        }}>
          Run a simulation
        </span>
        <span style={{
          fontFamily: FONT_BODY, fontSize: 10.5, color: T.inkFaint,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '55%',
        }}>
          {activeName
            ? <>active: <span style={{ fontFamily: FONT_MONO, color: T.tealDeep }}>{activeName}</span></>
            : 'no active structure'}
        </span>
      </div>

      <UploadRow sessionId={sessionId} onUploaded={handleUploaded} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {TOOL_FORMS.map((spec) => (
          <ToolCard
            key={spec.key}
            sessionId={sessionId}
            spec={spec}
            isOpen={openKey === spec.key}
            onToggle={toggle}
            onLaunched={onLaunched}
          />
        ))}
      </div>
    </div>
  )
}
