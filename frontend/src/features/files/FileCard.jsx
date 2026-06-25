import { downloadFile } from '../../api'

// Status pill palette for a launched async job shown inline in the chat.
const JOB_STATUS = {
  queued:    { label: 'Queued',    color: 'var(--status-queued-fg)',  bg: 'var(--status-queued-bg)',  border: 'var(--status-queued-bd)' },
  running:   { label: 'Running',   color: 'var(--status-running-fg)', bg: 'var(--status-running-bg)', border: 'var(--status-running-bd)' },
  succeeded: { label: 'Succeeded', color: 'var(--status-ok-fg)',      bg: 'var(--status-ok-bg)',      border: 'var(--status-ok-bd)' },
  success:   { label: 'Succeeded', color: 'var(--status-ok-fg)',      bg: 'var(--status-ok-bg)',      border: 'var(--status-ok-bd)' },
  failed:    { label: 'Failed',    color: 'var(--status-fail-fg)',    bg: 'var(--status-fail-bg)',    border: 'var(--status-fail-bd)' },
  cancelled: { label: 'Cancelled', color: 'var(--status-neutral-fg)', bg: 'var(--status-neutral-bg)', border: 'var(--status-neutral-bd)' },
}

function JobCard({ toolName, label, status, jobId, manual }) {
  const cfg = JOB_STATUS[status] || JOB_STATUS.queued
  return (
    <div style={{
      marginTop: '12px', background: 'var(--bg-elevated)',
      border: '1px solid var(--border-light, #eceae4)', borderRadius: '14px',
      padding: '14px 16px', maxWidth: '420px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '7px', minWidth: 0 }}>
          <span style={{
            fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)',
            letterSpacing: '0.05em', textTransform: 'uppercase',
          }}>
            {(label || toolName || 'job').replace(/_/g, ' ')}
          </span>
          {manual && (
            <span style={{
              fontSize: '9.5px', fontWeight: '600', letterSpacing: '0.04em', textTransform: 'uppercase',
              color: 'var(--accent-blue-dark)', background: 'var(--accent-blue-wash)',
              border: '1px solid var(--accent-blue-border)', borderRadius: '999px', padding: '1px 7px', flexShrink: 0,
            }}>
              manual
            </span>
          )}
        </span>
        <span style={{
          fontSize: '11px', padding: '3px 8px', borderRadius: '20px', fontWeight: '500',
          background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
        }}>
          {cfg.label}
        </span>
      </div>
      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
        Job <span style={{ fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-primary)' }}>
          {String(jobId).slice(0, 8)}
        </span>{' '}
        {status === 'succeeded' || status === 'success'
          ? <>finished — see results in the <strong>Jobs</strong> tab.</>
          : status === 'failed'
            ? <>failed — open the <strong>Jobs</strong> tab for details.</>
            : status === 'cancelled'
              ? <>was cancelled.</>
              : <>running — track live progress in the <strong>Jobs</strong> tab.</>}
      </div>
    </div>
  )
}

export default function FileCard({ toolName, label, status, files, onOpen, manual, jobId }) {
  // An async-job launch (optimize / MD / phonons / …) carries a jobId and writes
  // no files at enqueue time — show a job card instead of nothing.
  if (jobId) {
    return <JobCard toolName={toolName} label={label} status={status} jobId={jobId} manual={manual} />
  }
  if (!files || files.length === 0) return null

  const ok = status === 'success'

  return (
    <div
      style={{
        marginTop: '12px',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-light, #eceae4)',
        borderRadius: '14px',
        padding: '14px 16px',
        maxWidth: '420px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '10px',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '7px', minWidth: 0 }}>
          <span
            style={{
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--text-muted)',
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
            }}
          >
            {toolName?.replace(/_/g, ' ')}
          </span>
          {manual && (
            <span
              style={{
                fontSize: '9.5px',
                fontWeight: '600',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                color: 'var(--accent-blue-dark)',
                background: 'var(--accent-blue-wash)',
                border: '1px solid var(--accent-blue-border)',
                borderRadius: '999px',
                padding: '1px 7px',
                flexShrink: 0,
              }}
            >
              manual
            </span>
          )}
        </span>

        <span
          style={{
            fontSize: '11px',
            padding: '3px 8px',
            borderRadius: '20px',
            fontWeight: '500',
            background: ok ? 'var(--status-ok-bg)' : 'var(--status-fail-bg)',
            color: ok ? 'var(--status-ok-fg)' : 'var(--status-fail-fg)',
          }}
        >
          {ok ? `✓ ${files.length} file${files.length !== 1 ? 's' : ''}` : 'error'}
        </span>
      </div>

      {files.map((file, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '8px 0',
            borderTop: i > 0 ? '1px solid var(--border-light, #eceae4)' : 'none',
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'var(--accent-blue-wash)',
              border: '1px solid var(--accent-blue-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              flexShrink: 0,
            }}
          >
            📄
          </div>

          <div
            style={{ flex: 1, minWidth: 0, cursor: onOpen ? 'pointer' : 'default' }}
            onClick={() => onOpen?.(file.rel_path, file.name)}
            title={onOpen ? `Open ${file.name}` : file.name}
          >
            <div
              style={{
                fontSize: '13px',
                fontWeight: '500',
                color: 'var(--text-primary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                textDecoration: onOpen ? 'underline' : 'none',
                textUnderlineOffset: '2px',
                textDecorationColor: 'var(--border)',
              }}
            >
              {file.name}
            </div>

            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {file.size_kb < 1
                ? `${(file.size_kb * 1024).toFixed(0)} B`
                : `${file.size_kb} KB`}{' '}
              · {file.name.split('.').pop()?.toUpperCase() || 'FILE'}
            </div>
          </div>

          <button
            type="button"
            onClick={() => downloadFile(file.rel_path, file.name)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '30px',
              height: '30px',
              borderRadius: '8px',
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              fontSize: '14px',
              transition: 'all 0.1s',
              flexShrink: 0,
            }}
            title={`Download ${file.name}`}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--hover-bg)'
              e.currentTarget.style.borderColor = 'var(--text-muted)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.borderColor = 'var(--border)'
            }}
          >
            ↓
          </button>
        </div>
      ))}
    </div>
  )
}
