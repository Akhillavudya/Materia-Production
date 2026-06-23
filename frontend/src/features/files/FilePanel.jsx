import { useEffect, useState, useCallback } from 'react'
import { downloadFile, fetchSessionFilesGrouped } from '../../api'
import StructureViewer from '../viewer/StructureViewer'

// ── palette (kept local to this panel, matching the method-card launcher) ──
const T = {
  surface: 'var(--bg-elevated)',
  ink: 'var(--text-primary)', inkSoft: 'var(--text-secondary)', inkFaint: 'var(--text-muted)',
  border: 'var(--border)',
  teal: '#00B4A6', tealDeep: '#0d9488', tealWash: 'var(--hover-bg)',
}
const FONT_MONO = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace'

// per-type accent colors for the icon chips
const C = { teal: '#00B4A6', purple: '#7F77DD', blue: '#378ADD', coral: '#D85A30', pink: '#D4537E', gray: '#8B9591' }

// ── inline Tabler-style outline icons (dependency-free) ──
const ICONS = {
  cube: ['M12 2 L21 7 L21 17 L12 22 L3 17 L3 7 Z', 'M12 12 L12 22', 'M12 12 L21 7', 'M12 12 L3 7'],
  'file-text': [
    'M14 3v4a1 1 0 0 0 1 1h4',
    'M5 5a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z',
    'M9 13h6', 'M9 17h4',
  ],
  file: [
    'M14 3v4a1 1 0 0 0 1 1h4',
    'M5 5a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z',
  ],
  table: [
    'M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1 -1 1h-16a1 1 0 0 1 -1 -1v-14a1 1 0 0 1 1 -1z',
    'M3 10h18', 'M10 3v18',
  ],
  photo: [
    'M4 4a1 1 0 0 1 1 -1h14a1 1 0 0 1 1 1v14a1 1 0 0 1 -1 1h-14a1 1 0 0 1 -1 -1z',
    'M4 16l5 -5c.928 -.893 2.072 -.893 3 0l5 5', 'M14 14l1 -1c.928 -.893 2.072 -.893 3 0l2 2',
  ],
  braces: [
    'M7 4a2 2 0 0 0 -2 2v3a2 2 0 0 1 -2 2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2',
    'M17 4a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2a2 2 0 0 0 -2 2v3a2 2 0 0 1 -2 2',
  ],
  route: ['M6 17 V14 a4 4 0 0 1 4 -4 h4 a4 4 0 0 0 4 -4'], // + two endpoint circles
  download: ['M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2', 'M7 11l5 5l5 -5', 'M12 4v12'],
}
const GRID_DOTS = [[6, 6], [12, 6], [18, 6], [6, 12], [12, 12], [18, 12], [6, 18], [12, 18], [18, 18]]
const GEAR_TEETH = [0, 45, 90, 135, 180, 225, 270, 315]

function Icon({ name, color, size = 15 }) {
  const common = {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: color, strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round',
  }
  if (name === 'photo') {
    return (
      <svg {...common}>
        <circle cx="15" cy="8.5" r="1.2" fill={color} stroke="none" />
        {ICONS.photo.map((d, i) => <path key={i} d={d} />)}
      </svg>
    )
  }
  if (name === 'grid-dots') {
    return (
      <svg {...common}>
        {GRID_DOTS.map(([cx, cy], i) => <circle key={i} cx={cx} cy={cy} r="1.3" fill={color} stroke="none" />)}
      </svg>
    )
  }
  if (name === 'settings') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3.2" />
        {GEAR_TEETH.map((deg, i) => {
          const r = (deg * Math.PI) / 180
          const x1 = 12 + 5 * Math.cos(r), y1 = 12 + 5 * Math.sin(r)
          const x2 = 12 + 7.3 * Math.cos(r), y2 = 12 + 7.3 * Math.sin(r)
          return <line key={i} x1={x1.toFixed(2)} y1={y1.toFixed(2)} x2={x2.toFixed(2)} y2={y2.toFixed(2)} />
        })}
      </svg>
    )
  }
  if (name === 'route') {
    return (
      <svg {...common}>
        <circle cx="6" cy="19" r="2" />
        <circle cx="18" cy="5" r="2" />
        {ICONS.route.map((d, i) => <path key={i} d={d} />)}
      </svg>
    )
  }
  return <svg {...common}>{(ICONS[name] || ICONS.file).map((d, i) => <path key={i} d={d} />)}</svg>
}

// Map a filename to its type icon + accent color (visual only).
function fileType(name) {
  const upper = name.toUpperCase()
  const lower = name.toLowerCase()
  const ext = lower.includes('.') ? lower.split('.').pop() : ''

  if (['POSCAR', 'CONTCAR'].includes(upper) || upper.startsWith('POSCAR_') || ext === 'cif')
    return { icon: 'cube', color: C.teal }
  if (upper === 'INCAR') return { icon: 'settings', color: C.purple }
  if (upper === 'KPOINTS') return { icon: 'grid-dots', color: C.purple }
  if (ext === 'log') return { icon: 'file-text', color: C.gray }
  if (ext === 'csv') return { icon: 'table', color: C.blue }
  if (['png', 'jpg', 'jpeg'].includes(ext)) return { icon: 'photo', color: C.coral }
  if (ext === 'json') return { icon: 'braces', color: C.gray }
  if (['traj', 'xyz'].includes(ext)) return { icon: 'route', color: C.pink }
  return { icon: 'file', color: C.gray }
}

const s = {
  panel: {
    width: '100%', minWidth: 0, height: '100%',
    background: 'var(--bg-panel)',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  header: { padding: '16px 14px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 },
  headerTitle: {
    fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)',
    letterSpacing: '0.06em', textTransform: 'uppercase',
  },
  headerSub: { fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' },
  scrollArea: { flex: 1, overflowY: 'auto', padding: '10px 8px' },
  emptyState: {
    padding: '30px 14px', fontSize: '12px', color: 'var(--text-muted)',
    textAlign: 'center', lineHeight: '1.8',
  },
  group: { marginBottom: '16px' },

  // ── group header: label + thin rule + item count ──
  groupHeader: { display: 'flex', alignItems: 'center', gap: '8px', padding: '0 6px 7px' },
  groupLabel: {
    fontSize: '10.5px', fontWeight: '500', color: T.inkFaint,
    letterSpacing: '0.05em', textTransform: 'uppercase',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0,
  },
  groupRule: { flex: 1, height: '1px', background: 'var(--border)' },
  groupCount: { fontSize: '10.5px', color: T.inkFaint, fontFamily: FONT_MONO, flexShrink: 0 },

  fileRow: {
    display: 'flex', alignItems: 'center', gap: '8px',
    padding: '5px 6px', borderRadius: '6px', marginBottom: '2px',
    borderLeft: '2px solid transparent', transition: 'background 0.1s',
  },

  iconChip: {
    width: '26px', height: '26px', borderRadius: '7px', flexShrink: 0,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },

  fileName: {
    flex: 1, fontSize: '12px', color: T.ink, fontFamily: FONT_MONO,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  fileSize: { fontSize: '10px', color: T.inkFaint, fontFamily: FONT_MONO, flexShrink: 0 },

  activeBadge: {
    fontSize: '9px', fontWeight: '500', letterSpacing: '0.03em',
    color: T.tealDeep, background: T.surface,
    borderRadius: '5px', padding: '1px 6px', flexShrink: 0,
  },

  // 3D viewer trigger — quiet outline chip
  viewBtn: {
    background: 'transparent', border: '1px solid var(--border)', borderRadius: '5px',
    color: T.inkFaint, fontSize: '9px', cursor: 'pointer',
    padding: '1px 5px', flexShrink: 0, transition: 'all 0.1s',
  },

  // download — icon only, no chrome
  downloadBtn: {
    background: 'transparent', border: 'none', padding: '2px', flexShrink: 0,
    cursor: 'pointer', color: T.inkFaint, display: 'inline-flex', alignItems: 'center',
    transition: 'color 0.1s',
  },

  footer: { padding: '10px 8px 14px', borderTop: '1px solid var(--border)', flexShrink: 0 },
  downloadAllBtn: {
    width: '100%', padding: '8px', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-muted)',
    fontSize: '12px', cursor: 'pointer', transition: 'all 0.15s',
  },
  refreshBtn: {
    background: 'none', border: 'none', color: 'var(--text-secondary)',
    cursor: 'pointer', fontSize: '14px', padding: '0 0 0 6px', lineHeight: 1,
  },
  topRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
}

export default function FilePanel({ sessionId, refreshTrigger, onOpenFile }) {
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [viewer, setViewer] = useState(null)

  const load = useCallback(async () => {
    if (!sessionId) {
      setGroups([])
      return
    }

    setLoading(true)
    setError(null)

    try {
      const data = await fetchSessionFilesGrouped(sessionId)
      setGroups(data.groups || [])
    } catch {
      setError('Could not load files')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load, refreshTrigger])

  const totalFiles = groups.reduce((n, g) => n + g.files.length, 0)

  return (
    <div style={s.panel}>
      <div style={s.header}>
        <div style={s.topRow}>
          <div style={s.headerTitle}>Session Files</div>

          <button style={s.refreshBtn} onClick={load} title="Refresh file list">
            ↻
          </button>
        </div>

        <div style={s.headerSub}>
          {sessionId
            ? loading
              ? 'loading…'
              : `${totalFiles} file${totalFiles !== 1 ? 's' : ''}`
            : 'start a conversation'}
        </div>
      </div>

      <div style={s.scrollArea}>
        {!sessionId && (
          <div style={s.emptyState}>
            Files generated during
            <br />
            this session appear here.
          </div>
        )}

        {sessionId && !loading && groups.length === 0 && (
          <div style={s.emptyState}>
            No files yet.
            <br />
            Ask Materia to generate
            <br />
            a POSCAR or run a workflow.
          </div>
        )}

        {error && <div style={{ ...s.emptyState, color: '#b91c1c' }}>{error}</div>}

        {groups.map((group, gi) => (
          <div key={gi} style={s.group}>
            <div style={s.groupHeader}>
              <span style={s.groupLabel} title={group.group_name}>
                {group.group_name.replace(/_/g, ' ')}
              </span>
              <span style={s.groupRule} />
              <span style={s.groupCount}>{group.files.length}</span>
            </div>

            {group.files.map((file, fi) => {
              const upperName = file.name.toUpperCase()

              const isPoscar =
                ['POSCAR', 'CONTCAR'].includes(upperName) ||
                upperName.startsWith('POSCAR_') ||
                file.name.toLowerCase().endsWith('.cif') ||
                file.name.toLowerCase().endsWith('.xyz')

              // The plain "POSCAR" is the session's active structure — the one
              // optimize / MD / VASP pick up by default (S2). Tagged copies
              // (POSCAR_Si_slab111, …) say what each artifact is.
              const isActive = upperName === 'POSCAR'

              const type = fileType(file.name)

              return (
                <div
                  key={fi}
                  style={{
                    ...s.fileRow,
                    ...(isActive
                      ? { borderLeft: `2px solid ${type.color}`, background: T.tealWash }
                      : null),
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = T.surface
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent'
                  }}
                >
                  <span style={{ ...s.iconChip, background: `${type.color}29` }}>
                    <Icon name={type.icon} color={type.color} />
                  </span>

                  <span
                    style={{ ...s.fileName, cursor: onOpenFile ? 'pointer' : 'default' }}
                    title={onOpenFile ? `Open ${file.name}` : file.name}
                    onClick={() => onOpenFile && onOpenFile(file.rel_path, file.name)}
                  >
                    {file.name}
                  </span>

                  {isActive && (
                    <span style={s.activeBadge} title="Active structure — used by optimize / MD / VASP">
                      ACTIVE
                    </span>
                  )}

                  <span style={s.fileSize}>
                    {file.size_kb < 1
                      ? `${(file.size_kb * 1024).toFixed(0)}B`
                      : `${file.size_kb}K`}
                  </span>

                  {isPoscar && (
                    <button
                      title="View 3D structure"
                      onClick={() => setViewer({ relPath: file.rel_path, fileName: file.name })}
                      style={s.viewBtn}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--hover-bg)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                    >
                      3D
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => downloadFile(file.rel_path, file.name)}
                    style={s.downloadBtn}
                    title={`Download ${file.name}`}
                    onMouseEnter={(e) => { e.currentTarget.style.color = T.ink }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = T.inkFaint }}
                  >
                    <Icon name="download" color="currentColor" size={13} />
                  </button>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {totalFiles > 1 && (
        <div style={s.footer}>
          <button
            style={s.downloadAllBtn}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--hover-bg)' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
            onClick={() => {
              groups.forEach((group) => {
                group.files.forEach((file, i) => {
                  setTimeout(() => {
                    downloadFile(file.rel_path, file.name)
                  }, i * 300)
                })
              })
            }}
          >
            ↓ download all ({totalFiles})
          </button>
        </div>
      )}

      {viewer && (
        <StructureViewer
          relPath={viewer.relPath}
          fileName={viewer.fileName}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  )
}
