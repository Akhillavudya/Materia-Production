/**
 * PlanCard — the multi-tool confirmation gate.
 *
 * When the agent proposes a workflow that needs ≥2 tools, the backend streams a
 * [PLAN:{...}] event instead of running anything. This card shows the ordered
 * steps and a Confirm / Cancel gate; only Confirm executes the tools. During
 * execution the parent updates each step's `status` so the list checks off live.
 *
 *   plan: { summary, steps: [{ tool, title, detail, status }], final_output }
 *   planState: 'proposed' | 'running' | 'done' | 'canceled'
 */

const STEP_ICON = {
  pending: { mark: '○', color: 'var(--text-muted)' },
  running: { mark: '◐', color: '#6366f1' },
  done:    { mark: '✓', color: '#16a34a' },
  error:   { mark: '✕', color: '#dc2626' },
}

export default function PlanCard({ plan, planState, onConfirm, onCancel }) {
  if (!plan || !plan.steps?.length) return null

  const proposed = planState === 'proposed'
  const running = planState === 'running'
  const canceled = planState === 'canceled'

  return (
    <div style={{
      marginTop: '12px',
      background: '#ffffff',
      border: '1px solid var(--border)',
      borderRadius: '14px',
      padding: '16px 18px',
      maxWidth: '460px',
    }}>
      {/* header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px',
      }}>
        <span style={{ fontSize: '16px' }}>🧭</span>
        <span style={{
          fontSize: '12px', fontWeight: 700, letterSpacing: '0.05em',
          textTransform: 'uppercase', color: 'var(--text-muted)',
        }}>
          {running ? 'Running plan' : canceled ? 'Plan canceled' : 'Proposed plan'}
        </span>
      </div>

      {plan.summary && (
        <div style={{
          fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)',
          marginBottom: '12px', lineHeight: 1.45,
        }}>
          {plan.summary}
        </div>
      )}

      {/* steps */}
      <ol style={{ listStyle: 'none', margin: 0, padding: 0,
                   display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {plan.steps.map((step, i) => {
          const st = STEP_ICON[step.status || 'pending'] || STEP_ICON.pending
          const spin = step.status === 'running'
          return (
            <li key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
              <span style={{
                flexShrink: 0, width: '18px', textAlign: 'center',
                color: st.color, fontSize: '13px', fontWeight: 700,
                marginTop: '1px',
                display: 'inline-block',
                animation: spin ? 'spin 1s linear infinite' : 'none',
              }}>
                {st.mark}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)',
                }}>
                  {step.title || step.tool}
                  <code style={{
                    marginLeft: '8px', fontSize: '11px', fontWeight: 500,
                    color: 'var(--text-muted)', background: 'var(--hover-bg)',
                    padding: '1px 6px', borderRadius: '6px',
                    fontFamily: 'ui-monospace, monospace',
                  }}>
                    {step.tool}
                  </code>
                </div>
                {step.detail && (
                  <div style={{
                    fontSize: '12.5px', color: 'var(--text-secondary)',
                    lineHeight: 1.45, marginTop: '2px',
                  }}>
                    {step.detail}
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      {plan.final_output && (
        <div style={{
          marginTop: '12px', paddingTop: '12px',
          borderTop: '1px solid var(--border)',
          fontSize: '12.5px', color: 'var(--text-secondary)',
        }}>
          <strong style={{ color: 'var(--text-primary)' }}>You'll get: </strong>
          {plan.final_output}
        </div>
      )}

      {/* action gate — only while awaiting confirmation */}
      {proposed && (
        <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
          <button
            onClick={onConfirm}
            style={{
              flex: 1, padding: '9px 14px', borderRadius: '10px', border: 'none',
              background: '#6366f1', color: '#ffffff', fontSize: '13px',
              fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font)',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#4f46e5')}
            onMouseLeave={e => (e.currentTarget.style.background = '#6366f1')}
          >
            ✓ Confirm & run
          </button>
          <button
            onClick={onCancel}
            style={{
              padding: '9px 16px', borderRadius: '10px',
              border: '1px solid var(--border)', background: '#ffffff',
              color: 'var(--text-secondary)', fontSize: '13px', fontWeight: 500,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover-bg)')}
            onMouseLeave={e => (e.currentTarget.style.background = '#ffffff')}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}
