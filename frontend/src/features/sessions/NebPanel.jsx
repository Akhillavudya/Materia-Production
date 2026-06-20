/**
 * NEB workflow panel (bottom of the Jobs tab).
 *
 * NEB is the one tool that needs TWO structures — an initial and a final state.
 * Picking them through chat is error-prone (uploads get renamed / mis-resolved),
 * so this gives a deterministic form: choose the initial POSCAR, the final POSCAR,
 * a couple of options, and launch. The job then appears in the jobs list above.
 */

import { useState } from 'react'
import { launchNeb } from '../../api'

const FilePick = ({ label, file, onPick, accent }) => (
  <label style={{
    flex: 1, display: 'flex', flexDirection: 'column', gap: 4,
    fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer',
  }}>
    <span>{label}</span>
    <div style={{
      border: `1px dashed ${file ? accent : 'var(--border)'}`,
      borderRadius: 6, padding: '8px 10px', fontSize: 11,
      color: file ? 'var(--text-primary)' : 'var(--text-muted)',
      background: file ? `${accent}11` : 'transparent',
      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
    }}>
      {file ? file.name : 'Choose file…'}
    </div>
    <input
      type="file"
      style={{ display: 'none' }}
      onChange={(e) => onPick(e.target.files?.[0] || null)}
    />
  </label>
)

export default function NebPanel({ sessionId, onLaunched }) {
  const [open, setOpen] = useState(false)
  const [initial, setInitial] = useState(null)
  const [final, setFinal] = useState(null)
  const [nImages, setNImages] = useState(7)
  const [calc, setCalc] = useState('mace')
  const [climb, setClimb] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  if (!sessionId) return null

  const run = async () => {
    setMsg(null)
    if (!initial || !final) { setMsg({ kind: 'err', text: 'Pick both an initial and a final structure.' }); return }
    setBusy(true)
    try {
      const res = await launchNeb(sessionId, initial, final, {
        nImages, calculatorType: calc, climb,
      })
      setMsg({ kind: 'ok', text: `NEB job started (${(res.job_id || '').slice(0, 8)}). Tracking above.` })
      setInitial(null); setFinal(null)
      onLaunched?.()
    } catch (e) {
      setMsg({ kind: 'err', text: e.message || 'Failed to start NEB.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '12px 14px', flexShrink: 0 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
          fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font)',
        }}
      >
        <span>⛰ NEB — migration barrier</span>
        <span style={{ color: 'var(--text-muted)' }}>{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.4 }}>
            Pick two structures of the same atoms — a start and an end state (e.g. an atom
            before and after a hop). NEB finds the energy barrier between them.
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <FilePick label="Initial state" file={initial} onPick={setInitial} accent="#2563eb" />
            <FilePick label="Final state" file={final} onPick={setFinal} accent="#16a34a" />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 4 }}>
              Images
              <input
                type="number" min={3} max={15} value={nImages}
                onChange={(e) => setNImages(Number(e.target.value))}
                style={{ width: 56, padding: '5px 6px', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12 }}
              />
            </label>
            <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 4 }}>
              Potential
              <select
                value={calc} onChange={(e) => setCalc(e.target.value)}
                style={{ padding: '5px 6px', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12 }}
              >
                <option value="mace">MACE</option>
                <option value="mattersim">MatterSim</option>
              </select>
            </label>
            <label style={{ fontSize: 11, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 5, paddingBottom: 6 }}>
              <input type="checkbox" checked={climb} onChange={(e) => setClimb(e.target.checked)} />
              Climbing image
            </label>
          </div>

          <button
            onClick={run}
            disabled={busy}
            style={{
              padding: '8px 0', borderRadius: 6, border: 'none', cursor: busy ? 'default' : 'pointer',
              background: busy ? '#9ca3af' : '#2563eb', color: '#fff', fontSize: 12, fontWeight: 600,
              fontFamily: 'var(--font)',
            }}
          >
            {busy ? 'Starting…' : 'Run NEB'}
          </button>

          {msg && (
            <div style={{ fontSize: 11, color: msg.kind === 'ok' ? '#166534' : '#b91c1c', lineHeight: 1.4 }}>
              {msg.kind === 'ok' ? '✓ ' : '⚠ '}{msg.text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
