
import { useEffect, useState, useCallback } from 'react'
import { fetchJobs } from '../../api'

const TOOL_LABELS = {
  generate_vasp_poscar: 'POSCAR from Materials Project',
  generate_vasp_poscar_with_vacancy_defects: 'Vacancy defects',
  generate_vasp_poscar_with_substitution_defects: 'Substitution defects',
  generate_supercell_from_poscar: 'Supercell generation',
  generate_surface_slab_from_poscar: 'Surface slab',
  customize_vasp_kpoints_with_accuracy: 'KPOINTS generation',
  generate_vasp_inputs_from_poscar: 'VASP inputs (full set)',
  generate_vasp_workflow_of_eos: 'EOS workflow',
  run_simulation_using_mlps: 'MLP simulation',
  visualize_structure_from_poscar: 'Structure visualization',
}

const STATUS_CONFIG = {
  success: { color: '#166534', bg: '#ecfdf3', border: '#bbf7d0', icon: '✓' },
  error: { color: '#b91c1c', bg: '#fef2f2', border: '#fecaca', icon: '✗' },
  running: { color: '#2563eb', bg: '#eff6ff', border: '#bfdbfe', icon: '⟳' },
  pending: { color: 'var(--text-muted)', bg: 'var(--hover-bg)', border: 'var(--border)', icon: '○' },
}

function formatDuration(sec) {
  if (sec === null || sec === undefined) return '—'
  if (sec < 1) return `${(sec * 1000).toFixed(0)}ms`
  if (sec < 60) return `${sec.toFixed(1)}s`
  return `${Math.floor(sec / 60)}m ${(sec % 60).toFixed(0)}s`
}

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function parseArgs(argsStr) {
  try {
    return JSON.parse(argsStr)
  } catch {
    return {}
  }
}

const s = {
  panel: {
    width: '260px',
    minWidth: '260px',
    height: '100vh',
    borderLeft: '1px solid var(--border)',
    background: 'var(--bg-panel)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },

  header: {
    padding: '14px 14px 10px',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexShrink: 0,
  },

  headerTitle: {
    fontSize: '11px',
    fontWeight: '600',
    color: 'var(--text-secondary)',
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
  },

  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },

  countBadge: {
    fontSize: '11px',
    padding: '1px 6px',
    borderRadius: '8px',
    background: 'var(--hover-bg)',
    border: '1px solid var(--border)',
    color: 'var(--text-secondary)',
  },

  refreshBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '14px',
    padding: '0',
    lineHeight: 1,
    transition: 'color 0.15s',
  },

  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '8px 8px 16px',
  },

  empty: {
    padding: '30px 14px',
    fontSize: '12px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    lineHeight: '1.9',
    whiteSpace: 'pre-line',
  },

  jobCard: (status) => {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending
    return {
      background: cfg.bg,
      border: `1px solid ${cfg.border}`,
      borderRadius: '8px',
      padding: '10px 12px',
      marginBottom: '8px',
      cursor: 'default',
    }
  },

  jobTop: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '8px',
    marginBottom: '6px',
  },

  jobIcon: (status) => {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending
    return {
      width: '18px',
      height: '18px',
      borderRadius: '50%',
      background: cfg.border,
      color: cfg.color,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '10px',
      fontWeight: '600',
      flexShrink: 0,
      marginTop: '1px',
      animation: status === 'running' ? 'spin 1.2s linear infinite' : 'none',
    }
  },

  jobName: {
    fontSize: '12px',
    fontWeight: '500',
    color: 'var(--text-secondary)',
    flex: 1,
    lineHeight: '1.3',
  },

  jobStats: {
    display: 'flex',
    gap: '10px',
    marginTop: '6px',
    flexWrap: 'wrap',
  },

  stat: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    gap: '3px',
  },

  statVal: {
    color: 'var(--text-secondary)',
  },

  argsRow: {
    marginTop: '5px',
    fontSize: '10px',
    color: 'var(--text-muted)',
    fontFamily: 'monospace',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  msgRow: {
    marginTop: '5px',
    fontSize: '11px',
    lineHeight: '1.4',
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
  },

  rerunBtn: {
    marginTop: '8px',
    width: '100%',
    padding: '5px 8px',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '6px',
    color: 'var(--text-muted)',
    fontSize: '11px',
    cursor: 'pointer',
    transition: 'all 0.15s',
    textAlign: 'center',
  },

  summaryBar: {
    padding: '8px 12px',
    borderTop: '1px solid var(--border)',
    display: 'flex',
    gap: '12px',
    flexShrink: 0,
    flexWrap: 'wrap',
  },

  summaryItem: {
    fontSize: '11px',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },

  summaryVal: (color) => ({
    color,
    fontWeight: '500',
  }),
}

if (!document.getElementById('jd-styles')) {
  const st = document.createElement('style')
  st.id = 'jd-styles'
  st.textContent = `@keyframes spin { to { transform: rotate(360deg) } }`
  document.head.appendChild(st)
}

export default function JobDashboard({ sessionId, refreshTrigger, onRerun }) {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!sessionId) {
      setJobs([])
      return
    }

    setLoading(true)

    try {
      const data = await fetchJobs(sessionId)
      setJobs(data)
    } catch {
      // dashboard is non-critical
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load, refreshTrigger])

  const successCount = jobs.filter((j) => j.status === 'success').length
  const errorCount = jobs.filter((j) => j.status === 'error').length
  const totalFiles = jobs.reduce((sum, j) => sum + (j.file_count || 0), 0)
  const totalTime = jobs.reduce((sum, j) => sum + (j.duration_sec || 0), 0)

  return (
    <div style={s.panel}>
      <div style={s.header}>
        <span style={s.headerTitle}>Workflow</span>

        <div style={s.headerRight}>
          {jobs.length > 0 && (
            <span style={s.countBadge}>{jobs.length}</span>
          )}

          <button
            style={s.refreshBtn}
            onClick={load}
            title="Refresh"
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--text-secondary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-muted)'
            }}
          >
            ↻
          </button>
        </div>
      </div>

      <div style={s.list}>
        {(!sessionId || jobs.length === 0) && !loading && (
          <div style={s.empty}>
            {sessionId
              ? 'No tools run yet.\nAsk Materia to generate\na POSCAR or run a workflow.'
              : 'Select a session\nto see workflow history.'}
          </div>
        )}

        {jobs.map((job) => {
          const cfg = STATUS_CONFIG[job.status] || STATUS_CONFIG.pending
          const label =
            TOOL_LABELS[job.tool_name] ||
            job.tool_name.replace(/_/g, ' ')
          const args = parseArgs(job.tool_args)

          const argSummary = Object.entries(args)
            .slice(0, 2)
            .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
            .join('  ·  ')

          return (
            <div key={job.id} style={s.jobCard(job.status)}>
              <div style={s.jobTop}>
                <div style={s.jobIcon(job.status)}>
                  {cfg.icon}
                </div>

                <div style={s.jobName}>
                  {label}
                </div>
              </div>

              {argSummary && (
                <div style={s.argsRow} title={JSON.stringify(args)}>
                  {argSummary}
                </div>
              )}

              <div style={s.jobStats}>
                <span style={s.stat}>
                  ⏱ <span style={s.statVal}>{formatDuration(job.duration_sec)}</span>
                </span>

                {job.file_count > 0 && (
                  <span style={s.stat}>
                    📄{' '}
                    <span style={s.statVal}>
                      {job.file_count} file{job.file_count !== 1 ? 's' : ''}
                    </span>
                  </span>
                )}

                {job.started_at && (
                  <span style={s.stat}>
                    🕐 <span style={s.statVal}>{formatTime(job.started_at)}</span>
                  </span>
                )}
              </div>

              {job.status === 'success' && job.output_msg && (
                <div style={{ ...s.msgRow, color: '#166534' }}>
                  {job.output_msg}
                </div>
              )}

              {job.status === 'error' && job.error_msg && (
                <div style={{ ...s.msgRow, color: '#b91c1c' }}>
                  ⚠ {job.error_msg}
                </div>
              )}

              {job.status !== 'running' && onRerun && (
                <button
                  style={s.rerunBtn}
                  onClick={() => {
                    const argsStr = Object.entries(args)
                      .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                      .join(', ')

                    const msg = argsStr
                      ? `Run ${job.tool_name} again with ${argsStr}`
                      : `Run ${job.tool_name} again`

                    onRerun(msg)
                  }}
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
                  ↺ re-run
                </button>
              )}
            </div>
          )
        })}
      </div>

      {jobs.length > 0 && (
        <div style={s.summaryBar}>
          <span style={s.summaryItem}>
            <span style={s.summaryVal('#166534')}>{successCount}</span> ok
          </span>

          {errorCount > 0 && (
            <span style={s.summaryItem}>
              <span style={s.summaryVal('#b91c1c')}>{errorCount}</span> err
            </span>
          )}

          <span style={s.summaryItem}>
            <span style={s.summaryVal('var(--text-secondary)')}>
              {totalFiles}
            </span>{' '}
            files
          </span>

          <span style={s.summaryItem}>
            <span style={s.summaryVal('var(--text-muted)')}>
              {formatDuration(totalTime)}
            </span>{' '}
            total
          </span>
        </div>
      )}
    </div>
  )
}

