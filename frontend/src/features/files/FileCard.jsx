import { downloadFile } from '../../api'

export default function FileCard({ toolName, status, files, onOpen, manual }) {
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
                color: 'var(--accent-blue, #2563eb)',
                background: 'var(--accent-blue-wash, #eff6ff)',
                border: '1px solid #bfdbfe',
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
            background: ok ? '#ecfdf3' : '#fef2f2',
            color: ok ? '#166534' : '#b91c1c',
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
              background: '#eff6ff',
              border: '1px solid #bfdbfe',
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
              e.currentTarget.style.borderColor = '#d1cec7'
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
