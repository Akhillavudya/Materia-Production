import { useCallback, useEffect, useRef, useState } from 'react'
import { listModels, downloadModels } from '../../api/models'
import { getSystem } from '../../api/system'

// First-run (and re-openable) screen for the desktop app: download the ML-potential
// checkpoints onto the user's machine. The heavy simulations load these locally, so
// without at least one model the simulation tools can't run (chat still works online).
// On the lite web edition /api/models 404s and this screen is never shown.

const TYPE_LABEL = { mace: 'MACE', mattersim: 'MatterSim' }

function fmtMB(mb) {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`
}

export default function ModelSetup({ onClose }) {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [sys, setSys] = useState(null)
  const pollRef = useRef(null)

  // One-shot: which device will the heavy sims run on? (404s on web → stays null.)
  useEffect(() => {
    let alive = true
    getSystem().then((d) => { if (alive) setSys(d) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const data = await listModels()
      setModels(data.models)
      setError(null)
      return data.models
    } catch (err) {
      setError(err.message || 'Could not load models')
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Poll while anything is downloading; stop once everything settles.
  useEffect(() => {
    const anyDownloading = models.some((m) => m.status === 'downloading')
    if (anyDownloading && !pollRef.current) {
      pollRef.current = setInterval(refresh, 1500)
    } else if (!anyDownloading && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    }
  }, [models, refresh])

  async function startDownload(selection) {
    try {
      await downloadModels(selection)
      await refresh()
    } catch (err) {
      setError(err.message || 'Could not start download')
    }
  }

  const presentCount = models.filter((m) => m.exists).length
  const hasAny = presentCount > 0
  const recommended = models.filter((m) => m.recommended && !m.exists)
  const recMB = recommended.reduce((s, m) => s + m.approx_mb, 0)
  const allMissing = models.filter((m) => !m.exists && m.status !== 'downloading')
  const busy = models.some((m) => m.status === 'downloading')

  return (
    <div style={s.overlay}>
      <div style={s.panel}>
        <div style={s.header}>
          <div>
            <div style={s.title}>Simulation Models</div>
            <div style={s.subtitle}>
              Materia runs the heavy ML‑potential simulations on <strong>your own machine</strong>.
              Download at least one model to enable them. The AI chat works without these.
            </div>
          </div>
          <div style={s.count}>{presentCount}/{models.length} installed</div>
        </div>

        <div style={s.body}>
          {sys && <DeviceBadge sys={sys} />}

          {loading && <div style={s.muted}>Loading models…</div>}

          {!loading && recommended.length > 0 && (
            <div style={s.recCard}>
              <div style={s.recText}>
                <strong>Recommended set</strong> — a good general default
                ({recommended.map((m) => m.name).join(' + ')}).
              </div>
              <button style={s.primaryBtn(busy)} disabled={busy}
                onClick={() => startDownload('recommended')}>
                Download recommended (~{fmtMB(recMB)})
              </button>
            </div>
          )}

          {models.map((m) => (
            <ModelRow key={m.name} m={m} onDownload={() => startDownload([m.name])} />
          ))}

          {!loading && allMissing.length > 1 && (
            <button style={s.linkBtn} disabled={busy} onClick={() => startDownload('all')}>
              Download all remaining (~{fmtMB(allMissing.reduce((x, m) => x + m.approx_mb, 0))})
            </button>
          )}

          {error && <div style={s.errMsg}>⚠ {error}</div>}
        </div>

        <div style={s.footer}>
          <span style={s.muted}>
            {busy ? 'Downloading… you can keep this open or continue.'
                  : hasAny ? 'Ready — simulations are enabled.'
                           : 'You can download later from the sidebar.'}
          </span>
          <button style={s.continueBtn} onClick={onClose}>
            {hasAny ? 'Continue' : 'Skip for now'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Shows which device the heavy simulations will actually use, and nudges toward the
// GPU build when relevant. Three cases: accelerated (GPU/MPS), GPU build that fell
// back to CPU (no usable GPU), and the plain CPU build.
function DeviceBadge({ sys }) {
  let tone, icon, title, detail

  if (sys.device === 'cuda') {
    tone = 'ok'; icon = '⚡'
    title = 'Running on GPU'
    detail = sys.gpu_name || 'CUDA device'
  } else if (sys.device === 'mps') {
    tone = 'ok'; icon = '⚡'
    title = 'Running on GPU'
    detail = 'Apple GPU (Metal / MPS)'
  } else if (sys.variant === 'gpu') {
    // GPU installer, but torch found no usable GPU → graceful CPU fallback.
    tone = 'warn'; icon = '◧'
    title = 'Running on CPU'
    detail = 'GPU build, but no compatible GPU was detected — check your NVIDIA drivers.'
  } else {
    tone = 'muted'; icon = '▣'
    title = 'Running on CPU'
    detail = 'For NVIDIA acceleration, install the GPU build of Materia.'
  }

  return (
    <div style={s.devBadge(tone)}>
      <span style={s.devIcon(tone)}>{icon}</span>
      <div style={s.devText}>
        <span style={s.devTitle}>{title}</span>
        <span style={s.devDetail}>{detail}</span>
      </div>
    </div>
  )
}

function ModelRow({ m, onDownload }) {
  const pct = m.total ? Math.round((m.downloaded / m.total) * 100) : null
  const dlMB = m.downloaded ? (m.downloaded / 1e6).toFixed(0) : 0

  return (
    <div style={s.row}>
      <div style={s.rowMain}>
        <span style={s.modelName}>{m.name}</span>
        <span style={s.typePill}>{TYPE_LABEL[m.type] || m.type}</span>
        {m.recommended && <span style={s.recPill}>Recommended</span>}
      </div>

      <div style={s.rowSide}>
        {m.exists ? (
          <span style={s.okBadge}>✓ Installed</span>
        ) : m.status === 'downloading' ? (
          <div style={s.progWrap}>
            <div style={s.progBar}>
              <div style={{ ...s.progFill, width: pct != null ? `${pct}%` : '40%' }} />
            </div>
            <span style={s.progText}>
              {pct != null ? `${pct}%` : `${dlMB} MB`}
            </span>
          </div>
        ) : m.status === 'error' ? (
          <div style={s.errWrap}>
            <span style={s.errSmall} title={m.error}>Failed</span>
            <button style={s.smallBtn} onClick={onDownload}>Retry</button>
          </div>
        ) : (
          <button style={s.smallBtn} onClick={onDownload}>
            Download (~{fmtMB(m.approx_mb)})
          </button>
        )}
      </div>
    </div>
  )
}

const s = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(26,26,26,0.45)',
    backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1100, padding: '16px',
  },
  panel: {
    width: '640px', maxWidth: '96vw', maxHeight: '90vh', display: 'flex',
    flexDirection: 'column', background: 'var(--bg-chat)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
    boxShadow: '0 24px 70px rgba(0,0,0,0.22)', fontFamily: 'var(--font)',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    gap: '14px', padding: '20px 22px 16px', borderBottom: '1px solid var(--border-light)',
  },
  title: { fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' },
  subtitle: { fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '5px', lineHeight: 1.5, maxWidth: '470px' },
  count: { fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', whiteSpace: 'nowrap', marginTop: '3px' },

  body: { padding: '16px 22px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px' },
  muted: { fontSize: '12px', color: 'var(--text-muted)' },

  devBadge: (tone) => ({
    display: 'flex', alignItems: 'center', gap: '10px',
    padding: '10px 13px', borderRadius: 'var(--radius-md)',
    background: tone === 'ok' ? 'var(--status-ok-bg, var(--accent-blue))'
             : tone === 'warn' ? 'var(--status-warn-bg, var(--accent-blue))'
             : 'var(--hover-bg)',
    border: `1px solid ${tone === 'ok' ? 'var(--status-ok-fg)'
             : tone === 'warn' ? 'var(--danger-fg)' : 'var(--border)'}`,
  }),
  devIcon: (tone) => ({
    fontSize: '16px', lineHeight: 1,
    color: tone === 'ok' ? 'var(--status-ok-fg)'
         : tone === 'warn' ? 'var(--danger-fg)' : 'var(--text-muted)',
  }),
  devText: { display: 'flex', flexDirection: 'column', gap: '1px', minWidth: 0 },
  devTitle: { fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)' },
  devDetail: { fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.4 },

  recCard: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
    background: 'var(--accent-blue)', border: '1px solid var(--accent-blue-border)',
    borderRadius: 'var(--radius-md)', padding: '12px 14px',
  },
  recText: { fontSize: '12.5px', color: 'var(--accent-blue-dark)', lineHeight: 1.5 },

  row: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '11px 14px',
  },
  rowMain: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', minWidth: 0 },
  modelName: { fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' },
  typePill: {
    fontSize: '10px', fontWeight: 600, padding: '2px 7px', borderRadius: '20px',
    background: 'var(--hover-bg)', color: 'var(--text-muted)', border: '1px solid var(--border)',
  },
  recPill: {
    fontSize: '10px', fontWeight: 600, padding: '2px 7px', borderRadius: '20px',
    background: 'var(--accent-blue)', color: 'var(--accent-blue-dark)', border: '1px solid var(--accent-blue-border)',
  },
  rowSide: { flexShrink: 0 },
  okBadge: { fontSize: '12px', fontWeight: 600, color: 'var(--status-ok-fg)' },

  progWrap: { display: 'flex', alignItems: 'center', gap: '8px', minWidth: '160px' },
  progBar: { flex: 1, height: '6px', background: 'var(--hover-bg)', borderRadius: '4px', overflow: 'hidden' },
  progFill: { height: '100%', background: 'var(--accent-solid)', transition: 'width 0.4s ease' },
  progText: { fontSize: '11px', color: 'var(--text-muted)', width: '40px', textAlign: 'right' },

  errWrap: { display: 'flex', alignItems: 'center', gap: '8px' },
  errSmall: { fontSize: '12px', color: 'var(--danger-fg)', cursor: 'help' },

  primaryBtn: (disabled) => ({
    padding: '8px 14px', borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap',
    background: disabled ? 'var(--bg-sidebar)' : 'var(--accent-solid)',
    border: `1px solid ${disabled ? 'var(--border)' : 'var(--accent-solid)'}`,
    color: disabled ? 'var(--text-muted)' : 'var(--accent-solid-fg)',
    fontSize: '12.5px', fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'var(--font)',
  }),
  smallBtn: {
    padding: '6px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--accent-blue)',
    border: '1px solid var(--accent-blue-border)', color: 'var(--accent-blue-dark)',
    fontSize: '12px', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'var(--font)',
  },
  linkBtn: {
    alignSelf: 'flex-start', background: 'none', border: 'none', color: 'var(--text-secondary)',
    fontSize: '12px', cursor: 'pointer', textDecoration: 'underline', padding: '4px 0', fontFamily: 'var(--font)',
  },
  errMsg: { fontSize: '12px', color: 'var(--danger-fg)' },

  footer: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
    padding: '14px 22px', borderTop: '1px solid var(--border-light)',
  },
  continueBtn: {
    padding: '9px 20px', borderRadius: 'var(--radius-sm)', background: 'var(--accent-solid)',
    border: '1px solid var(--accent-solid)', color: 'var(--accent-solid-fg)', fontSize: '13px',
    fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'var(--font)',
  },
}
