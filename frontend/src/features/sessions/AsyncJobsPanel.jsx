/**
 * Live async-job panel (redesign §11/§13).
 *
 * Lists optimize / MD jobs for the current session and polls /api/jobs so
 * queued → running → succeeded/failed transitions and per-step progress appear
 * without a page refresh. Polls fast (2.5s) while any job is active, slow (12s)
 * otherwise. Jobs are launched from chat or the ToolLaunchPanel below it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { listAsyncJobs, cancelAsyncJob } from '../../api'

const ACTIVE = new Set(['queued', 'running'])

const STATUS = {
  queued:    { label: 'Queued',    color: '#92400e', bg: '#fffbeb', border: '#fde68a' },
  running:   { label: 'Running',   color: '#1d4ed8', bg: '#eff6ff', border: '#bfdbfe' },
  succeeded: { label: 'Succeeded', color: '#166534', bg: '#ecfdf3', border: '#bbf7d0' },
  failed:    { label: 'Failed',    color: '#b91c1c', bg: '#fef2f2', border: '#fecaca' },
  cancelled: { label: 'Cancelled', color: '#6b7280', bg: '#f9fafb', border: '#e5e7eb' },
}

const TYPE_LABEL = {
  optimize: 'Geometry optimization',
  md: 'Molecular dynamics',
  elastic: 'Elastic / mechanical',
  phonon: 'Phonons',
  sqs: 'SQS (random alloy)',
  neb: 'NEB migration barrier',
}

function ProgressBar({ pct }) {
  return (
    <div style={{ height: 5, borderRadius: 3, background: 'var(--hover-bg)', overflow: 'hidden', marginTop: 6 }}>
      <div style={{
        width: `${Math.min(100, Math.max(2, pct || 0))}%`,
        height: '100%',
        background: '#2563eb',
        transition: 'width 0.4s ease',
      }} />
    </div>
  )
}

export default function AsyncJobsPanel({ sessionId, refreshSignal }) {
  const [jobs, setJobs] = useState([])
  const timer = useRef(null)

  const load = useCallback(async () => {
    if (!sessionId) { setJobs([]); return }
    try {
      setJobs(await listAsyncJobs(sessionId))
    } catch { /* non-critical */ }
  }, [sessionId])

  // Immediate refresh when a job is launched from elsewhere (e.g. the NEB panel).
  useEffect(() => { if (refreshSignal) load() }, [refreshSignal, load])

  useEffect(() => {
    let stopped = false
    const tick = async () => {
      await load()
      if (stopped) return
      const anyActive = (await listAsyncJobs(sessionId).catch(() => []))
        .some((j) => ACTIVE.has(j.status))
      timer.current = window.setTimeout(tick, anyActive ? 2500 : 12000)
    }
    tick()
    return () => { stopped = true; if (timer.current) window.clearTimeout(timer.current) }
  }, [load, sessionId])

  const onCancel = async (id) => {
    try { await cancelAsyncJob(id); await load() } catch { /* ignore */ }
  }

  if (!sessionId || jobs.length === 0) return null

  return (
    <div style={{ padding: '10px 8px', borderBottom: '1px solid var(--border)' }}>
      <div style={{
        fontSize: 11, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase',
        color: 'var(--text-secondary)', padding: '0 6px 8px',
      }}>
        Simulations
      </div>

      {jobs.map((job) => {
        const cfg = STATUS[job.status] || STATUS.queued
        const p = job.progress || {}
        const artifacts = job.artifacts || []
        return (
          <div key={job.id} style={{
            background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 8,
            padding: '9px 11px', marginBottom: 8,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ flex: 1, fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>
                {TYPE_LABEL[job.type] || job.type}
              </span>
              <span style={{
                fontSize: 10, fontWeight: 600, color: cfg.color,
                border: `1px solid ${cfg.border}`, borderRadius: 6, padding: '1px 6px',
              }}>
                {cfg.label}
              </span>
            </div>

            {job.status === 'running' && (
              <>
                <ProgressBar pct={p.pct} />
                <div style={{ marginTop: 5, fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {p.total ? <span>step {p.step}/{p.total}{p.pct != null ? ` · ${p.pct}%` : ''}</span> : null}
                  {p.energy != null ? <span>E {p.energy} eV</span> : null}
                  {p.fmax != null ? <span>fmax {p.fmax}</span> : null}
                  {p.temperature != null ? <span>T {p.temperature} K</span> : null}
                </div>
              </>
            )}

            {job.status === 'failed' && job.error && (
              <div style={{ marginTop: 5, fontSize: 11, color: '#b91c1c', lineHeight: 1.4 }}>
                ⚠ {job.error}
              </div>
            )}

            {job.status === 'succeeded' && (
              <div style={{ marginTop: 5, fontSize: 11, color: '#166534' }}>
                {job.result?.final_energy != null ? `E = ${job.result.final_energy} eV · ` : ''}
                {job.result?.barrier_forward_eV != null ? `barrier = ${job.result.barrier_forward_eV} eV · ` : ''}
                {artifacts.length} file{artifacts.length !== 1 ? 's' : ''}
              </div>
            )}

            {ACTIVE.has(job.status) && (
              <button
                onClick={() => onCancel(job.id)}
                style={{
                  marginTop: 8, width: '100%', padding: '4px 8px', fontSize: 11,
                  background: 'transparent', border: '1px solid var(--border)',
                  borderRadius: 6, color: 'var(--text-muted)', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
