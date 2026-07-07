import { useEffect, useRef, useState } from 'react'
import { fetchFileContent } from '../../api'
import { load3Dmol } from './threeDmol'

const s = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.75)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: '#0d1117',
    border: '1px solid #1e2a3a',
    borderRadius: '14px',
    width:  'min(860px, 92vw)',
    height: 'min(640px, 90vh)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 18px',
    borderBottom: '1px solid #1a2030',
    flexShrink: 0,
  },
  titleRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  title: {
    fontSize: '14px',
    fontWeight: '500',
    color: '#a0c4ff',
    fontFamily: 'monospace',
  },
  badge: {
    fontSize: '11px',
    padding: '2px 8px',
    borderRadius: '4px',
    background: '#0a1a2a',
    border: '1px solid #1a3050',
    color: '#5090c0',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: '#445',
    fontSize: '20px',
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    transition: 'color 0.15s',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '10px 18px',
    borderBottom: '1px solid #1a2030',
    flexShrink: 0,
    flexWrap: 'wrap',
  },
  toolBtn: (active) => ({
    padding: '5px 12px',
    borderRadius: '6px',
    background: active ? '#1c3558' : 'transparent',
    border: `1px solid ${active ? '#274878' : '#1e2a3a'}`,
    color: active ? '#a0c4ff' : '#556',
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  }),
  separator: {
    width: '1px',
    height: '20px',
    background: '#1e2a3a',
    margin: '0 4px',
  },
  viewerWrap: {
    flex: 1,
    position: 'relative',
    overflow: 'hidden',
    background: '#060a0f',
  },
  viewerDiv: {
    width: '100%',
    height: '100%',
  },
  loadingOverlay: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#060a0f',
    gap: '12px',
  },
  spinner: {
    width: '28px', height: '28px',
    border: '2px solid #1a2a3a',
    borderTop: '2px solid #4080c0',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  loadingText: {
    fontSize: '13px',
    color: '#446',
  },
  errorBox: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
  },
  errorText: {
    fontSize: '13px',
    color: '#e07070',
    maxWidth: '380px',
    textAlign: 'center',
    lineHeight: '1.6',
  },
  footer: {
    padding: '8px 18px',
    borderTop: '1px solid #1a2030',
    fontSize: '11px',
    color: '#334',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  },
}

// inject spin keyframe once
if (!document.getElementById('sv-styles')) {
  const st = document.createElement('style')
  st.id = 'sv-styles'
  st.textContent = `@keyframes spin { to { transform: rotate(360deg) } }`
  document.head.appendChild(st)
}

// ── 3Dmol style helper ───────────────────────────────────────────────────────
function getStyle3Dmol(style) {
  switch (style) {
    case 'stick':    return { stick:   { radius: 0.15, colorscheme: 'Jmol' } }
    case 'sphere':   return { sphere:  { scale: 0.35,  colorscheme: 'Jmol' } }
    case 'line':     return { line:    { colorscheme: 'Jmol' } }
    case 'ballstick':return {
      stick:  { radius: 0.12, colorscheme: 'Jmol' },
      sphere: { scale: 0.28,  colorscheme: 'Jmol' },
    }
    default:         return { stick: { radius: 0.15, colorscheme: 'Jmol' } }
  }
}

// ── parse atom count from POSCAR ─────────────────────────────────────────────
function parsePoscarInfo(content) {
  try {
    const lines = content.split('\n')
    // line 5 (index 5) = element symbols, line 6 = counts
    const elements = lines[5]?.trim().split(/\s+/) || []
    const counts   = lines[6]?.trim().split(/\s+/).map(Number) || []
    const total    = counts.reduce((a, b) => a + b, 0)
    return { elements, counts, total }
  } catch {
    return { elements: [], counts: [], total: 0 }
  }
}

// ── main component ────────────────────────────────────────────────────────────
// props:
//   relPath   — file rel_path from the file panel e.g. "uuid/POSCAR"
//   fileName  — display name e.g. "POSCAR"
//   onClose() — called when user dismisses the viewer

export default function StructureViewer({ relPath, fileName, onClose }) {
  const viewerRef  = useRef(null)     // DOM div for 3Dmol
  const glViewerRef = useRef(null)    // 3Dmol viewer instance
  const isAnimRef  = useRef(false)    // true when showing a multi-frame .xyz

  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [info,     setInfo]     = useState(null)   // { elements, total }
  const [style,    setStyle]    = useState('stick')  // stick | sphere | line | cartoon
  const [showCell, setShowCell] = useState(true)

  // ── load and render on mount ───────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        setLoading(true)
        setError(null)

        // fetch file content and 3Dmol in parallel
        const [$3Dmol, fileData] = await Promise.all([
          load3Dmol(),
          fetchFileContent(relPath),
        ])

        if (cancelled) return

        const content = fileData.content
        // A multi-frame .xyz (e.g. the NEB path) plays as an animation; a POSCAR
        // is a single static frame.
        const isAnim = /\.xyz$/i.test(relPath)
        isAnimRef.current = isAnim
        if (!isAnim) setInfo(parsePoscarInfo(content))

        // wait for DOM element to be ready
        if (!viewerRef.current) return

        // create viewer
        const viewer = $3Dmol.createViewer(viewerRef.current, {
          backgroundColor: '#060a0f',
          antialias: true,
          defaultcolors: $3Dmol.elementColors.Jmol,
        })

        glViewerRef.current = viewer

        if (isAnim) {
          // load every frame and loop through them (the NEB migration path)
          viewer.addModelsAsFrames(content, 'xyz')
          viewer.setStyle({}, { stick: { radius: 0.15, colorscheme: 'Jmol' } })
          viewer.zoomTo()
          viewer.animate({ loop: 'forward', reps: 0 })
          viewer.render()
        } else {
          // add the structure — POSCAR format
          viewer.addModel(content, 'vasp')
          // default style
          viewer.setStyle({}, { stick: { radius: 0.15, colorscheme: 'Jmol' } })
          // show unit cell box
          viewer.addUnitCell()
          viewer.zoomTo()
          viewer.render()
        }

        setLoading(false)

      } catch (err) {
        if (!cancelled) {
          setError(err.message)
          setLoading(false)
        }
      }
    }

    init()
    return () => { cancelled = true }
  }, [relPath])

  // ── update style when toolbar button changes ───────────────────────────────
  useEffect(() => {
    const viewer = glViewerRef.current
    if (!viewer) return

    viewer.setStyle({}, getStyle3Dmol(style))
    viewer.render()
  }, [style])

  // ── toggle unit cell ───────────────────────────────────────────────────────
  useEffect(() => {
    const viewer = glViewerRef.current
    if (!viewer || isAnimRef.current) return   // .xyz frames carry no unit cell

    if (showCell) {
      viewer.addUnitCell()
    } else {
      viewer.removeUnitCell()
    }
    viewer.render()
  }, [showCell])

  function resetView() {
    const viewer = glViewerRef.current
    if (!viewer) return
    viewer.zoomTo()
    viewer.render()
  }

  // close on Escape key
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.modal}>

        {/* header */}
        <div style={s.header}>
          <div style={s.titleRow}>
            <span style={s.title}>{fileName}</span>
            {info && (
              <span style={s.badge}>
                {info.total} atoms
                {info.elements.length > 0 && ` · ${info.elements.join(' ')}`}
              </span>
            )}
          </div>
          <button
            style={s.closeBtn}
            onClick={onClose}
            onMouseEnter={e => e.target.style.color = '#a0c4ff'}
            onMouseLeave={e => e.target.style.color = '#445'}
          >
            ✕
          </button>
        </div>

        {/* toolbar */}
        <div style={s.toolbar}>
          <span style={{ fontSize: '11px', color: '#334', marginRight: '4px' }}>
            style
          </span>
          {['stick', 'ballstick', 'sphere', 'line'].map(st => (
            <button
              key={st}
              style={s.toolBtn(style === st)}
              onClick={() => setStyle(st)}
            >
              {st}
            </button>
          ))}

          <div style={s.separator} />

          <button
            style={s.toolBtn(showCell)}
            onClick={() => setShowCell(v => !v)}
          >
            unit cell
          </button>

          <div style={s.separator} />

          <button style={s.toolBtn(false)} onClick={resetView}>
            reset view
          </button>
        </div>

        {/* viewer area */}
        <div style={s.viewerWrap}>
          <div ref={viewerRef} style={s.viewerDiv} />

          {loading && (
            <div style={s.loadingOverlay}>
              <div style={s.spinner} />
              <div style={s.loadingText}>Loading structure…</div>
            </div>
          )}

          {error && !loading && (
            <div style={s.errorBox}>
              <div style={{ fontSize: '24px' }}>⚠</div>
              <div style={s.errorText}>
                Could not render structure.<br />
                {error}<br />
                <span style={{ fontSize: '11px', color: '#334' }}>
                  Only POSCAR and CONTCAR files are supported.
                </span>
              </div>
            </div>
          )}
        </div>

        {/* footer */}
        <div style={s.footer}>
          <span>drag to rotate · scroll to zoom · right-drag to pan</span>
          <span style={{ color: '#224' }}>3Dmol.js</span>
        </div>

      </div>
    </div>
  )
}