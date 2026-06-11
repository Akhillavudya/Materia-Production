import { useEffect, useState, useCallback } from 'react'
import { downloadFile, fetchSessionFilesGrouped } from '../../api'
import StructureViewer from '../viewer/StructureViewer'

const s = {
  panel: {
    width: '240px',
    minWidth: '240px',
    height: '100vh',
    borderLeft: '1px solid var(--border)',
    background: 'var(--bg-panel)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },

  header: {
    padding: '16px 14px 10px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },

  headerTitle: {
    fontSize: '12px',
    fontWeight: '600',
    color: 'var(--text-muted)',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },

  headerSub: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    marginTop: '2px',
  },

  scrollArea: {
    flex: 1,
    overflowY: 'auto',
    padding: '10px 8px',
  },

  emptyState: {
    padding: '30px 14px',
    fontSize: '12px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    lineHeight: '1.8',
  },

  group: {
    marginBottom: '16px',
  },

  groupLabel: {
    fontSize: '10px',
    fontWeight: '600',
    color: 'var(--text-muted)',
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
    padding: '0 6px 6px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  fileRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '5px 6px',
    borderRadius: '6px',
    marginBottom: '2px',
    transition: 'all 0.1s',
  },

  fileIcon: {
    fontSize: '11px',
    flexShrink: 0,
    width: '16px',
    textAlign: 'center',
  },

  fileName: {
    flex: 1,
    fontSize: '12px',
    color: 'var(--text-secondary)',
    fontFamily: 'monospace',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  fileSize: {
    fontSize: '10px',
    color: 'var(--text-muted)',
    flexShrink: 0,
  },

  downloadLink: {
    fontSize: '11px',
    color: 'var(--text-secondary)',
    textDecoration: 'none',
    padding: '2px 5px',
    borderRadius: '4px',
    border: '1px solid var(--border)',
    flexShrink: 0,
    transition: 'all 0.1s',
    display: 'inline-block',
  },

  footer: {
    padding: '10px 8px 14px',
    borderTop: '1px solid var(--border)',
    flexShrink: 0,
  },

  downloadAllBtn: {
    width: '100%',
    padding: '8px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    color: 'var(--text-muted)',
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },

  refreshBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-secondary)',
    cursor: 'pointer',
    fontSize: '14px',
    padding: '0 0 0 6px',
    lineHeight: 1,
  },

  topRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },

  viewBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    color: 'var(--text-muted)',
    fontSize: '11px',
    cursor: 'pointer',
    padding: '2px 5px',
    flexShrink: 0,
    transition: 'all 0.1s',
  },
}

function fileIcon(name) {
  const ext = name.split('.').pop()?.toLowerCase()

  const map = {
    png: '🖼',
    jpg: '🖼',
    jpeg: '🖼',
    html: '🌐',
    csv: '📊',
    txt: '📄',
    log: '📋',
    pkl: '📦',
    sh: '⚙',
  }

  return map[ext] || '📄'
}

export default function FilePanel({ sessionId, refreshTrigger }) {
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

          <button
            style={s.refreshBtn}
            onClick={load}
            title="Refresh file list"
          >
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

        {error && (
          <div style={{ ...s.emptyState, color: '#b91c1c' }}>
            {error}
          </div>
        )}

        {groups.map((group, gi) => (
          <div key={gi} style={s.group}>
            <div style={s.groupLabel} title={group.group_name}>
              {group.group_name.replace(/_/g, ' ')}
            </div>

            {group.files.map((file, fi) => {
              const upperName = file.name.toUpperCase()

              // const isPoscar =
              //   ['POSCAR', 'CONTCAR'].includes(upperName) ||
              //   upperName.startsWith('POSCAR_')
              const isPoscar =
                    ['POSCAR', 'CONTCAR'].includes(upperName) ||
                    upperName.startsWith('POSCAR_') ||
                    file.name.toLowerCase().endsWith('.cif') ||
                    file.name.toLowerCase().endsWith('.xyz')

              return (
                <div
                  key={fi}
                  style={s.fileRow}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--hover-bg)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent'
                  }}
                >
                  <span style={s.fileIcon}>
                    {fileIcon(file.name)}
                  </span>

                  <span
                    style={s.fileName}
                    title={file.name}
                  >
                    {file.name}
                  </span>

                  <span style={s.fileSize}>
                    {file.size_kb < 1
                      ? `${(file.size_kb * 1024).toFixed(0)}B`
                      : `${file.size_kb}K`}
                  </span>

                  {isPoscar && (
                    <button
                      title="View 3D structure"
                      onClick={() =>
                        setViewer({
                          relPath: file.rel_path,
                          fileName: file.name,
                        })
                      }
                      style={s.viewBtn}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--hover-bg)'
                        e.currentTarget.style.color = 'var(--text-secondary)'
                        e.currentTarget.style.borderColor = 'var(--border)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent'
                        e.currentTarget.style.color = 'var(--text-muted)'
                        e.currentTarget.style.borderColor = 'var(--border)'
                      }}
                    >
                      3D
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => downloadFile(file.rel_path, file.name)}
                    style={s.downloadLink}
                    title={`Download ${file.name}`}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--hover-bg)'
                      e.currentTarget.style.color = 'var(--text-secondary)'
                      e.currentTarget.style.borderColor = 'var(--border)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.color = 'var(--text-secondary)'
                      e.currentTarget.style.borderColor = 'var(--border)'
                    }}
                  >
                    ↓
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
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--hover-bg)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
            }}
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
