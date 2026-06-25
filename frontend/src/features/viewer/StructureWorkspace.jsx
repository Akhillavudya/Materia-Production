import { useEffect, useRef, useState, useCallback } from 'react'
import { fetchSessionFilesGrouped, fetchFileContent } from '../../api'
import { load3Dmol } from './threeDmol'
import { buildPolyhedra, geometryFor, parsePoscar, replicateAtoms, expandBoundaryAtoms, toXyz } from './polyhedra'

/**
 * Full-screen, VESTA-style structure visualizer.
 *
 * Opened from the sidebar. Lists the structure files (POSCAR / CONTCAR / .cif /
 * .xyz) of the active session, or accepts pasted structure text, and renders
 * them with 3Dmol.js. The left rail mirrors VESTA's control panel: render
 * style, unit cell + supercell boundary, atom/bond sizing, labels, scene
 * background, axes and spin — plus reset view and PNG export.
 */

// ── format / parsing helpers ──────────────────────────────────────────────────
function formatOf(name = '') {
  const lower = name.toLowerCase()
  if (lower.endsWith('.cif')) return 'cif'
  if (lower.endsWith('.xyz')) return 'xyz'
  return 'vasp' // POSCAR / CONTCAR / POSCAR_*
}

function isStructureFile(name = '') {
  const upper = name.toUpperCase()
  return (
    ['POSCAR', 'CONTCAR'].includes(upper) ||
    upper.startsWith('POSCAR_') ||
    upper.startsWith('CONTCAR_') ||
    name.toLowerCase().endsWith('.cif') ||
    name.toLowerCase().endsWith('.xyz')
  )
}

// Empirical chemical formula from the rendered model's atoms.
function summarize(model) {
  try {
    const atoms = model.selectedAtoms({})
    const counts = {}
    for (const a of atoms) {
      const el = a.elem || a.atom || '?'
      counts[el] = (counts[el] || 0) + 1
    }
    const elements = Object.keys(counts).sort()
    const formula = elements.map(el => (counts[el] > 1 ? `${el}${counts[el]}` : el)).join(' ')
    return { total: atoms.length, elements, formula }
  } catch {
    return { total: 0, elements: [], formula: '' }
  }
}

// VESTA-style render style → 3Dmol style spec.
function styleSpec(style, atomScale, bondScale) {
  const cs = 'Jmol'
  switch (style) {
    case 'spacefill':
      return { sphere: { scale: 1.0 * atomScale, colorscheme: cs } }
    case 'stick':
      return { stick: { radius: 0.18 * bondScale, colorscheme: cs } }
    case 'wireframe':
      return { line: { colorscheme: cs } }
    case 'polyhedral': // 3Dmol has no true polyhedra → best-effort ball-and-stick
    case 'ballstick':
    default:
      return {
        stick: { radius: 0.13 * bondScale, colorscheme: cs },
        sphere: { scale: 0.30 * atomScale, colorscheme: cs },
      }
  }
}

const STYLES = [
  { id: 'ballstick',  label: 'Ball-and-stick' },
  { id: 'spacefill',  label: 'Space-filling' },
  { id: 'polyhedral', label: 'Polyhedral' },
  { id: 'wireframe',  label: 'Wireframe' },
  { id: 'stick',      label: 'Stick' },
]

const BG_PRESETS = {
  dark:  '#0b0f14',
  light: '#ffffff',
  navy:  '#0d1117',
}

export default function StructureWorkspace({ sessionId, onClose }) {
  const viewerRef   = useRef(null)   // DOM mount for 3Dmol
  const glRef       = useRef(null)   // 3Dmol viewer instance
  const dmolRef     = useRef(null)   // the loaded $3Dmol namespace (for colors)
  const modelRef    = useRef(null)   // current 3Dmol model
  const geomKeyRef  = useRef('')     // last geometry signature (for zoom reset)

  // data
  const [files, setFiles]       = useState([])
  const [selected, setSelected] = useState(null) // { relPath, fileName } | null
  const [content, setContent]   = useState('')
  const [format, setFormat]     = useState('vasp')
  const [info, setInfo]         = useState(null)

  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [ready, setReady]       = useState(false) // 3Dmol viewer created

  // paste box
  const [showPaste, setShowPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteFmt, setPasteFmt]   = useState('vasp')

  // ── render options (VESTA controls) ──
  const [style, setStyle]         = useState('ballstick')
  const [showCell, setShowCell]   = useState(true)
  const [showBoundary, setShowBoundary] = useState(true) // VESTA-style edge atoms
  const [sa, setSa] = useState(1)
  const [sb, setSb] = useState(1)
  const [sc, setSc] = useState(1)
  const [atomScale, setAtomScale] = useState(1)
  const [bondScale, setBondScale] = useState(1)
  const [showLabels, setShowLabels] = useState(false)
  const [bg, setBg] = useState(BG_PRESETS.dark)
  const [showAxes, setShowAxes] = useState(true)
  const [spin, setSpin] = useState(false)
  // polyhedral-mode controls
  const [polyTol, setPolyTol]         = useState(1.3)
  const [polyOpacity, setPolyOpacity] = useState(0.85)

  // ── load list of structure files for the session ──
  useEffect(() => {
    if (!sessionId) { setFiles([]); return }
    let cancelled = false
    fetchSessionFilesGrouped(sessionId)
      .then(data => {
        if (cancelled) return
        const flat = []
        for (const g of data.groups || []) {
          for (const f of g.files || []) {
            if (isStructureFile(f.name)) flat.push({ relPath: f.rel_path, fileName: f.name })
          }
        }
        setFiles(flat)
        // auto-select the active POSCAR, else the first structure
        const active = flat.find(f => f.fileName.toUpperCase() === 'POSCAR') || flat[0]
        if (active) setSelected(active)
      })
      .catch(() => { if (!cancelled) setFiles([]) })
    return () => { cancelled = true }
  }, [sessionId])

  // ── create the 3Dmol viewer once ──
  useEffect(() => {
    let cancelled = false
    load3Dmol()
      .then($3Dmol => {
        if (cancelled || !viewerRef.current) return
        dmolRef.current = $3Dmol
        glRef.current = $3Dmol.createViewer(viewerRef.current, {
          backgroundColor: bg,
          antialias: true,
          defaultcolors: $3Dmol.elementColors.Jmol,
        })
        setReady(true)
      })
      .catch(() => setError('Failed to load the 3D engine (3Dmol.js). Check your connection.'))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── fetch the selected file's content ──
  useEffect(() => {
    if (!selected) return
    let cancelled = false
    setLoading(true); setError(null)
    fetchFileContent(selected.relPath)
      .then(data => {
        if (cancelled) return
        setContent(data.content ?? '')
        setFormat(formatOf(selected.fileName))
      })
      .catch(e => { if (!cancelled) setError(e.message || 'Could not read file') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selected])

  // ── draw / redraw the scene whenever content or options change ──
  const renderScene = useCallback(() => {
    const viewer = glRef.current
    if (!viewer || !content) return

    try {
      viewer.clear()

      // Geometry source of truth. For POSCAR we parse it ourselves (3Dmol's VASP
      // reader silently drops atoms on minor quirks) and feed 3Dmol a rock-solid
      // XYZ; for CIF/XYZ we let 3Dmol parse. `geom` (lattice + base-cell atoms)
      // drives both the cell box and the polyhedra so they stay consistent.
      let model
      let geom = null
      let ownCell = false

      const parsed = format === 'vasp' ? parsePoscar(content) : null
      if (parsed && parsed.atoms.length) {
        geom = parsed
        ownCell = !!parsed.lattice
        // supercell tiling takes precedence; otherwise duplicate boundary atoms
        // (VESTA default) so slabs/crystals fill out instead of looking sparse
        let shown = parsed.atoms
        if (sa > 1 || sb > 1 || sc > 1) shown = replicateAtoms(parsed.atoms, parsed.lattice, sa, sb, sc)
        else if (showBoundary) shown = expandBoundaryAtoms(parsed.atoms, parsed.lattice)
        model = viewer.addModel(toXyz(shown), 'xyz')
      } else {
        // CIF / XYZ (or a POSCAR our parser couldn't read → let 3Dmol try)
        model = viewer.addModel(content, format)
        if (format !== 'xyz' && (sa > 1 || sb > 1 || sc > 1) && viewer.replicateUnitCell) {
          try { viewer.replicateUnitCell(sa, sb, sc, model) } catch { /* non-periodic */ }
        }
        geom = geometryFor(model, content, format)
      }
      modelRef.current = model
      setInfo(summarize(model))

      viewer.setStyle({}, styleSpec(style, atomScale, bondScale))

      // coordination polyhedra (VESTA-style) — computed by us, drawn as meshes
      if (style === 'polyhedral' && geom?.atoms?.length) {
        try {
          const getColor = el => jmolColor(dmolRef.current, el)
          for (const shape of buildPolyhedra(geom, { tol: polyTol, getColor })) {
            viewer.addCustom({
              vertexArr: shape.vertexArr,
              normalArr: shape.normalArr,
              faceArr: shape.faceArr,
              color: shape.color,
              opacity: polyOpacity,
            })
          }
        } catch { /* fall back to the plain ball-and-stick already set */ }
      }

      if (showCell && format !== 'xyz') {
        if (ownCell && geom.lattice) drawCellBox(viewer, geom.lattice, sa, sb, sc)
        else { try { viewer.addUnitCell(model) } catch { /* no cell info */ } }
      }

      if (showLabels) {
        for (const a of model.selectedAtoms({})) {
          viewer.addLabel(a.elem || '?', {
            position: { x: a.x, y: a.y, z: a.z },
            fontSize: 11, fontColor: 'white', backgroundColor: 'black',
            backgroundOpacity: 0.45, inFront: true, alignment: 'center',
          })
        }
      }

      if (showAxes) drawAxes(viewer)

      viewer.setBackgroundColor(bg)
      viewer.spin(spin ? 'y' : false)

      // only reframe the camera when the geometry (not just styling) changed
      const geomKey = `${content.length}:${format}:${sa}-${sb}-${sc}`
      if (geomKey !== geomKeyRef.current) {
        viewer.zoomTo()
        geomKeyRef.current = geomKey
      }
      viewer.render()
    } catch (e) {
      setError(e.message || 'Could not render this structure.')
    }
  }, [content, format, style, showCell, showBoundary, sa, sb, sc, atomScale, bondScale, showLabels, bg, showAxes, spin, polyTol, polyOpacity])

  useEffect(() => {
    if (ready) renderScene()
  }, [ready, renderScene])

  // close on Escape
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function resetView() {
    const viewer = glRef.current
    if (!viewer) return
    viewer.zoomTo(); viewer.render()
  }

  function savePng() {
    const viewer = glRef.current
    if (!viewer) return
    const uri = viewer.pngURI()
    const a = document.createElement('a')
    a.href = uri
    a.download = `${(selected?.fileName || 'structure').replace(/\W+/g, '_')}.png`
    a.click()
  }

  function renderPaste() {
    if (!pasteText.trim()) return
    setSelected(null)
    setFormat(pasteFmt)
    setContent(pasteText)
    geomKeyRef.current = '' // force reframe
    setShowPaste(false)
  }

  const hasStructure = !!content

  return (
    <div style={s.overlay}>
      {/* ── top bar ── */}
      <div style={s.topbar}>
        <span style={s.brand}>⬡ Structure Viewer</span>

        <select
          style={s.select}
          value={selected?.relPath || ''}
          onChange={e => {
            const f = files.find(x => x.relPath === e.target.value)
            if (f) { geomKeyRef.current = ''; setSelected(f) }
          }}
        >
          <option value="" disabled>
            {files.length ? 'Select a structure…' : 'No structure files in this session'}
          </option>
          {files.map(f => (
            <option key={f.relPath} value={f.relPath}>{f.fileName}</option>
          ))}
        </select>

        <button style={s.topBtn} onClick={() => setShowPaste(v => !v)}>
          {showPaste ? 'Close paste' : 'Paste structure'}
        </button>

        <div style={{ flex: 1 }} />

        {info && hasStructure && (
          <span style={s.headInfo}>
            {info.total} atoms · {info.formula}
          </span>
        )}
        <button style={s.closeBtn} onClick={onClose} title="Close (Esc)">✕</button>
      </div>

      {/* paste drawer */}
      {showPaste && (
        <div style={s.pasteRow}>
          <textarea
            style={s.textarea}
            placeholder="Paste POSCAR / CIF / XYZ text here…"
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
          />
          <div style={s.pasteSide}>
            <label style={s.pasteLabel}>Format</label>
            <select style={s.select} value={pasteFmt} onChange={e => setPasteFmt(e.target.value)}>
              <option value="vasp">POSCAR (vasp)</option>
              <option value="cif">CIF</option>
              <option value="xyz">XYZ</option>
            </select>
            <button style={{ ...s.topBtn, marginTop: 8 }} onClick={renderPaste}>Render →</button>
          </div>
        </div>
      )}

      {/* ── body: left controls + canvas ── */}
      <div style={s.body}>
        {/* control rail */}
        <div style={s.rail}>
          <Section title="Style">
            {STYLES.map(st => (
              <Radio
                key={st.id}
                label={st.label}
                checked={style === st.id}
                onChange={() => setStyle(st.id)}
              />
            ))}
          </Section>

          {style === 'polyhedral' && (
            <Section title="Polyhedra">
              <Slider label={`Bond tolerance  ${polyTol.toFixed(2)}`} min={1.0} max={1.8} step={0.05}
                value={polyTol} onChange={setPolyTol} />
              <Slider label={`Opacity  ${polyOpacity.toFixed(2)}`} min={0.2} max={1} step={0.05}
                value={polyOpacity} onChange={setPolyOpacity} />
              <div style={s.note}>
                Cations are linked to coordinating anions; raise the tolerance if a
                polyhedron is missing vertices.
              </div>
            </Section>
          )}

          <Section title="Unit cell & boundary">
            <Check label="Show unit cell" checked={showCell} onChange={() => setShowCell(v => !v)} />
            <Check label="Boundary atoms" checked={showBoundary} onChange={() => setShowBoundary(v => !v)} />
            <div style={s.superRow}>
              <span style={s.superLabel}>Supercell</span>
              <NumBox value={sa} onChange={setSa} />×
              <NumBox value={sb} onChange={setSb} />×
              <NumBox value={sc} onChange={setSc} />
            </div>
          </Section>

          <Section title="Atoms & bonds">
            <Slider label={`Atom size  ${atomScale.toFixed(2)}`} min={0.2} max={2} step={0.05}
              value={atomScale} onChange={setAtomScale} />
            <Slider label={`Bond size  ${bondScale.toFixed(2)}`} min={0.2} max={3} step={0.05}
              value={bondScale} onChange={setBondScale} />
            <Check label="Atom labels" checked={showLabels} onChange={() => setShowLabels(v => !v)} />
          </Section>

          <Section title="Scene">
            <Check label="Show axes" checked={showAxes} onChange={() => setShowAxes(v => !v)} />
            <Check label="Spin" checked={spin} onChange={() => setSpin(v => !v)} />
            <div style={{ ...s.superRow, marginTop: 6 }}>
              <span style={s.superLabel}>Background</span>
              <button style={s.bgChip(bg === BG_PRESETS.dark)}  onClick={() => setBg(BG_PRESETS.dark)} title="Dark" />
              <button style={s.bgChip(bg === BG_PRESETS.navy)}  onClick={() => setBg(BG_PRESETS.navy)} title="Navy" />
              <button style={s.bgChip(bg === BG_PRESETS.light)} onClick={() => setBg(BG_PRESETS.light)} title="Light" />
              <input type="color" value={bg} onChange={e => setBg(e.target.value)} style={s.colorInput} title="Custom" />
            </div>
          </Section>

          <div style={s.railFooter}>
            <button style={s.actionBtn} onClick={resetView}>Reset view</button>
            <button style={s.actionBtn} onClick={savePng} disabled={!hasStructure}>Save PNG</button>
          </div>
        </div>

        {/* canvas */}
        <div style={s.canvasWrap}>
          <div ref={viewerRef} style={s.canvas} />

          {!hasStructure && !loading && !error && (
            <div style={s.placeholder}>
              <div style={{ fontSize: 30, marginBottom: 10 }}>⬡</div>
              <div>{files.length
                ? 'Select a structure from the top bar to visualize it.'
                : 'No structure files in this session. Generate a POSCAR or paste structure text.'}</div>
            </div>
          )}

          {loading && (
            <div style={s.placeholder}>
              <div style={s.spinner} />
              <div style={{ marginTop: 10 }}>Loading structure…</div>
            </div>
          )}

          {error && (
            <div style={{ ...s.placeholder, color: '#e07070' }}>
              <div style={{ fontSize: 24 }}>⚠</div>
              <div style={{ maxWidth: 360, marginTop: 8 }}>{error}</div>
            </div>
          )}

          <div style={s.statusbar}>
            <span>drag = rotate · scroll = zoom · right-drag = pan</span>
            <span style={{ opacity: 0.6 }}>
              {selected?.fileName || (hasStructure ? 'pasted structure' : '')} · 3Dmol.js
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// element → Jmol hex color (used to tint polyhedra by their central cation)
function jmolColor($3Dmol, el) {
  const c = $3Dmol?.elementColors?.Jmol?.[el]
  if (c == null) return '#cc66cc'
  return '#' + c.toString(16).padStart(6, '0')
}

// ── unit-cell box: 12 edges of the (super)cell parallelepiped ─────────────────
function drawCellBox(viewer, lattice, na = 1, nb = 1, nc = 1) {
  const A = lattice[0].map(x => x * na)
  const B = lattice[1].map(x => x * nb)
  const C = lattice[2].map(x => x * nc)
  const corner = (i, j, k) => ({
    x: i * A[0] + j * B[0] + k * C[0],
    y: i * A[1] + j * B[1] + k * C[1],
    z: i * A[2] + j * B[2] + k * C[2],
  })
  const edges = [
    [[0, 0, 0], [1, 0, 0]], [[0, 0, 0], [0, 1, 0]], [[0, 0, 0], [0, 0, 1]],
    [[1, 1, 1], [0, 1, 1]], [[1, 1, 1], [1, 0, 1]], [[1, 1, 1], [1, 1, 0]],
    [[1, 0, 0], [1, 1, 0]], [[1, 0, 0], [1, 0, 1]],
    [[0, 1, 0], [1, 1, 0]], [[0, 1, 0], [0, 1, 1]],
    [[0, 0, 1], [1, 0, 1]], [[0, 0, 1], [0, 1, 1]],
  ]
  for (const [p, q] of edges) {
    viewer.addLine({ start: corner(...p), end: corner(...q), color: '#8a97a8' })
  }
}

// ── orientation gizmo: x/y/z arrows at the origin ─────────────────────────────
function drawAxes(viewer) {
  const L = 2.2
  const defs = [
    { dir: { x: L, y: 0, z: 0 }, color: 0xff4d4d, label: 'x' },
    { dir: { x: 0, y: L, z: 0 }, color: 0x4dff7a, label: 'y' },
    { dir: { x: 0, y: 0, z: L }, color: 0x4d8bff, label: 'z' },
  ]
  for (const d of defs) {
    viewer.addArrow({
      start: { x: 0, y: 0, z: 0 }, end: d.dir,
      radius: 0.06, radiusRatio: 2.2, mid: 0.8, color: d.color,
    })
    viewer.addLabel(d.label, {
      position: d.dir, fontSize: 12, inFront: true,
      fontColor: 'white', backgroundOpacity: 0,
    })
  }
}

// ── small control primitives ──────────────────────────────────────────────────
function Section({ title, children }) {
  return (
    <div style={s.section}>
      <div style={s.sectionTitle}>{title}</div>
      {children}
    </div>
  )
}

function Radio({ label, checked, onChange }) {
  return (
    <label style={s.row} onClick={onChange}>
      <span style={s.radioDot(checked)} />
      <span style={s.rowLabel(checked)}>{label}</span>
    </label>
  )
}

function Check({ label, checked, onChange }) {
  return (
    <label style={s.row} onClick={onChange}>
      <span style={s.checkBox(checked)}>{checked ? '✓' : ''}</span>
      <span style={s.rowLabel(checked)}>{label}</span>
    </label>
  )
}

function NumBox({ value, onChange }) {
  return (
    <input
      type="number" min={1} max={6} value={value}
      onChange={e => onChange(Math.max(1, Math.min(6, Number(e.target.value) || 1)))}
      style={s.numBox}
    />
  )
}

function Slider({ label, min, max, step, value, onChange }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={s.sliderLabel}>{label}</div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%' }}
      />
    </div>
  )
}

// inject spin keyframe once (shared id is fine if StructureViewer already added it)
if (!document.getElementById('sv-styles')) {
  const st = document.createElement('style')
  st.id = 'sv-styles'
  st.textContent = `@keyframes spin { to { transform: rotate(360deg) } }`
  document.head.appendChild(st)
}

const s = {
  overlay: {
    position: 'fixed', inset: 0, zIndex: 900,
    background: 'var(--bg-chat)', display: 'flex', flexDirection: 'column',
    fontFamily: 'var(--font)',
  },
  topbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    borderBottom: '1px solid var(--border)', flexShrink: 0,
  },
  brand: { fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' },
  select: {
    background: 'var(--bg-elevated)', color: 'var(--text-primary)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    padding: '6px 10px', fontSize: 13, fontFamily: 'var(--font)', maxWidth: 320,
  },
  topBtn: {
    background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    padding: '6px 12px', fontSize: 13, cursor: 'pointer', fontFamily: 'var(--font)',
  },
  headInfo: { fontSize: 12, color: 'var(--text-muted)', fontFamily: 'ui-monospace, monospace' },
  closeBtn: {
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    fontSize: 18, padding: '4px 8px', lineHeight: 1,
  },
  pasteRow: {
    display: 'flex', gap: 12, padding: '12px 16px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-sidebar)',
  },
  textarea: {
    flex: 1, minHeight: 120, resize: 'vertical', padding: 10, fontSize: 12.5,
    fontFamily: 'ui-monospace, monospace', borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border)', background: 'var(--bg-elevated)',
    color: 'var(--text-primary)',
  },
  pasteSide: { display: 'flex', flexDirection: 'column', minWidth: 160 },
  pasteLabel: { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 },

  body: { flex: 1, display: 'flex', minHeight: 0 },
  rail: {
    width: 264, minWidth: 264, overflowY: 'auto', flexShrink: 0,
    borderRight: '1px solid var(--border)', background: 'var(--bg-sidebar)',
    padding: '14px 16px',
  },
  section: { marginBottom: 18 },
  sectionTitle: {
    fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
    color: 'var(--text-muted)', marginBottom: 8,
  },
  row: {
    display: 'flex', alignItems: 'center', gap: 9, padding: '5px 2px',
    cursor: 'pointer', userSelect: 'none',
  },
  radioDot: (on) => ({
    width: 13, height: 13, borderRadius: '50%', flexShrink: 0,
    border: `2px solid ${on ? 'var(--accent-blue-dark, #2a7de1)' : 'var(--border)'}`,
    background: on ? 'var(--accent-blue-dark, #2a7de1)' : 'transparent',
    boxShadow: on ? 'inset 0 0 0 2px var(--bg-sidebar)' : 'none',
  }),
  checkBox: (on) => ({
    width: 15, height: 15, borderRadius: 3, flexShrink: 0,
    border: `1.5px solid ${on ? 'var(--accent-blue-dark, #2a7de1)' : 'var(--border)'}`,
    background: on ? 'var(--accent-blue-dark, #2a7de1)' : 'transparent',
    color: '#fff', fontSize: 11, lineHeight: '13px', textAlign: 'center',
  }),
  rowLabel: (on) => ({
    fontSize: 13, color: on ? 'var(--text-primary)' : 'var(--text-secondary)',
    fontWeight: on ? 500 : 400,
  }),
  note: { fontSize: 10.5, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.4 },
  superRow: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 13, color: 'var(--text-secondary)' },
  superLabel: { fontSize: 13, color: 'var(--text-secondary)', marginRight: 4 },
  numBox: {
    width: 42, padding: '4px 6px', fontSize: 13, textAlign: 'center',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    background: 'var(--bg-elevated)', color: 'var(--text-primary)',
  },
  sliderLabel: { fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 },
  bgChip: (on) => ({
    width: 20, height: 20, borderRadius: 4, cursor: 'pointer',
    border: on ? '2px solid var(--accent-blue-dark, #2a7de1)' : '1px solid var(--border)',
    background: 'currentColor',
  }),
  colorInput: { width: 26, height: 22, padding: 0, border: '1px solid var(--border)', borderRadius: 4, background: 'none', cursor: 'pointer' },
  railFooter: { display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 },
  actionBtn: {
    width: '100%', padding: '9px 12px', fontSize: 13, fontWeight: 500, cursor: 'pointer',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontFamily: 'var(--font)',
  },

  canvasWrap: { flex: 1, position: 'relative', minWidth: 0, background: '#060a0f' },
  canvas: { position: 'absolute', inset: 0, width: '100%', height: '100%' },
  placeholder: {
    position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', textAlign: 'center',
    color: '#7a8aa0', fontSize: 13, padding: 24, pointerEvents: 'none',
  },
  spinner: {
    width: 28, height: 28, border: '2px solid #1a2a3a', borderTop: '2px solid #4080c0',
    borderRadius: '50%', animation: 'spin 0.8s linear infinite',
  },
  statusbar: {
    position: 'absolute', left: 0, right: 0, bottom: 0,
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 14px', fontSize: 11, color: '#9fb0c8',
    background: 'rgba(0,0,0,0.35)', backdropFilter: 'blur(2px)',
  },
}
