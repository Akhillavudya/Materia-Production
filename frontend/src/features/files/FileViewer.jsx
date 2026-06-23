import { useEffect, useRef, useState } from 'react'
import { fetchFileContent, fetchFileObjectUrl, downloadFile } from '../../api'

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico']

function extOf(name) {
  return (name.split('.').pop() || '').toLowerCase()
}

function kindOf(name) {
  const ext = extOf(name)
  if (IMAGE_EXTS.includes(ext)) return 'image'
  if (ext === 'html' || ext === 'htm') return 'html'
  return 'text'
}

/**
 * Full-height inline file viewer (Claude-style). Renders next to the chat with
 * the sidebar + right panel hidden. Previews images, HTML (interactive), and any
 * readable text/code; falls back to a download prompt for binary files.
 */
export default function FileViewer({ className, isMobile = false, relPath, fileName, onClose }) {
  const kind = kindOf(fileName)
  const [content, setContent] = useState('')
  const [imgUrl, setImgUrl] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [showSource, setShowSource] = useState(false)
  const urlRef = useRef(null)

  // ── drag-to-resize + maximize ──────────────────────────────────────────────
  const MIN_W = 360
  // open at a balanced 50/50 split with the chat; user can drag to resize
  const [width, setWidth] = useState(() => Math.round(window.innerWidth * 0.5))
  const prevWidthRef = useRef(null)

  function startDrag(e) {
    e.preventDefault()
    const onMove = (ev) => {
      const w = window.innerWidth - ev.clientX
      setWidth(Math.max(MIN_W, Math.min(w, window.innerWidth - MIN_W)))
      prevWidthRef.current = null   // a manual drag clears the "maximized" memory
    }
    const stop = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', stop)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', stop)
  }

  function toggleMax() {
    if (prevWidthRef.current != null) {
      setWidth(prevWidthRef.current)
      prevWidthRef.current = null
    } else {
      prevWidthRef.current = width
      setWidth(window.innerWidth - MIN_W)
    }
  }
  const maximized = prevWidthRef.current != null

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null); setContent(''); setImgUrl(null); setShowSource(false)

    async function load() {
      try {
        if (kind === 'image') {
          const url = await fetchFileObjectUrl(relPath)
          if (cancelled) { URL.revokeObjectURL(url); return }
          urlRef.current = url
          setImgUrl(url)
        } else {
          const data = await fetchFileContent(relPath)
          if (cancelled) return
          setContent(data.content ?? '')
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'This file type can’t be previewed.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()

    return () => {
      cancelled = true
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null }
    }
  }, [relPath, fileName, kind])

  // close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  function handleCopy() {
    navigator.clipboard?.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const lines = content ? content.split('\n') : []

  return (
    <div className={className} style={{ ...s.wrap, width: isMobile ? '100%' : width }}>
      {/* drag handle — left edge, resize the viewer (Claude-style; desktop only) */}
      {!isMobile && (
        <div
          style={s.handle}
          onMouseDown={startDrag}
          onDoubleClick={toggleMax}
          title="Drag to resize · double-click to maximize"
        />
      )}

      {/* ── header ── */}
      <div style={s.header}>
        <span style={s.icon}>{kind === 'image' ? '🖼' : kind === 'html' ? '🌐' : '📄'}</span>
        <span style={s.name} title={fileName}>{fileName}</span>
        <div style={{ flex: 1 }} />
        {kind === 'html' && !error && (
          <button style={s.btn} onClick={() => setShowSource(v => !v)}>
            {showSource ? 'Preview' : 'Source'}
          </button>
        )}
        {kind === 'text' && !error && (
          <button style={s.btn} onClick={handleCopy}>{copied ? '✓ Copied' : 'Copy'}</button>
        )}
        <button style={s.btn} onClick={() => downloadFile(relPath, fileName)}>↓ Download</button>
        {!isMobile && (
          <button style={s.closeBtn} onClick={toggleMax} title={maximized ? 'Restore size' : 'Maximize'}>
            {maximized ? '⤡' : '⤢'}
          </button>
        )}
        <button style={s.closeBtn} onClick={onClose} title="Close (Esc)">✕</button>
      </div>

      {/* ── body ── */}
      <div style={s.body}>
        {loading && <div style={s.msg}>Loading…</div>}

        {!loading && error && (
          <div style={s.msg}>
            <div style={{ marginBottom: 12 }}>{error}</div>
            <button style={s.bigBtn} onClick={() => downloadFile(relPath, fileName)}>
              ↓ Download {fileName}
            </button>
          </div>
        )}

        {!loading && !error && kind === 'image' && imgUrl && (
          <div style={s.imageWrap}>
            <img src={imgUrl} alt={fileName} style={s.image} />
          </div>
        )}

        {!loading && !error && kind === 'html' && (
          showSource
            ? <CodeBlock lines={content.split('\n')} />
            : <iframe title={fileName} srcDoc={content} sandbox="allow-scripts" style={s.iframe} />
        )}

        {!loading && !error && kind === 'text' && <CodeBlock lines={lines} />}
      </div>
    </div>
  )
}

function CodeBlock({ lines }) {
  return (
    <div style={s.code}>
      <div style={s.gutter}>
        {lines.map((_, i) => <div key={i} style={s.lineNo}>{i + 1}</div>)}
      </div>
      <pre style={s.pre}>
        {lines.map((ln, i) => <div key={i} style={s.codeLine}>{ln || ' '}</div>)}
      </pre>
    </div>
  )
}

const s = {
  wrap: {
    position: 'relative', flexShrink: 0, minWidth: 0, height: '100vh',
    display: 'flex', flexDirection: 'column',
    background: 'var(--bg-chat)', borderLeft: '1px solid var(--border)',
  },
  handle: {
    position: 'absolute', left: '-3px', top: 0, bottom: 0, width: '7px',
    cursor: 'col-resize', zIndex: 5,
  },
  header: {
    display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px',
    borderBottom: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-chat)',
  },
  icon: { fontSize: '14px', flexShrink: 0 },
  name: {
    fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)',
    fontFamily: 'ui-monospace, monospace', overflow: 'hidden', textOverflow: 'ellipsis',
    whiteSpace: 'nowrap', maxWidth: '50%',
  },
  btn: {
    background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    color: 'var(--text-secondary)', fontSize: '12px', cursor: 'pointer', padding: '5px 10px',
    fontFamily: 'var(--font)', whiteSpace: 'nowrap', flexShrink: 0,
  },
  closeBtn: {
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    fontSize: '15px', padding: '5px 8px', borderRadius: 'var(--radius-sm)', flexShrink: 0, lineHeight: 1,
  },
  body: { flex: 1, overflow: 'auto', minHeight: 0 },
  msg: { padding: '40px 24px', textAlign: 'center', fontSize: '13px', color: 'var(--text-muted)' },

  imageWrap: { display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', minHeight: '100%' },
  image: { maxWidth: '100%', maxHeight: '85vh', objectFit: 'contain', borderRadius: 'var(--radius-md)' },

  iframe: { width: '100%', height: '100%', border: 'none', background: '#fff' },

  code: { display: 'flex', fontSize: '12.5px', fontFamily: 'ui-monospace, monospace', lineHeight: '1.55' },
  gutter: {
    flexShrink: 0, padding: '14px 10px 14px 14px', textAlign: 'right',
    color: 'var(--text-muted)', userSelect: 'none', background: 'var(--bg-sidebar)',
    borderRight: '1px solid var(--border-light)',
  },
  lineNo: { fontSize: '11.5px' },
  pre: { margin: 0, padding: '14px 16px', whiteSpace: 'pre', overflowX: 'auto', flex: 1, color: 'var(--text-primary)' },
  codeLine: {},
  bigBtn: {
    background: 'var(--accent-blue)', border: '1px solid #bfdbfe', color: 'var(--accent-blue-dark)',
    borderRadius: 'var(--radius-sm)', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
    padding: '9px 16px', fontFamily: 'var(--font)',
  },
}
