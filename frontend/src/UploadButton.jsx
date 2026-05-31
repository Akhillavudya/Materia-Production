import { useRef, useState } from 'react'
import { uploadFiles, createSessionAndUpload } from './api'

// ── which file types the browser file picker will accept ─────────────────────
const ACCEPT = [
  // VASP files — no extension, listed by name in the input accept attribute
  // browsers don't support filtering by name, so we use a broad accept
  // and validate on the backend
  '.cif', '.xyz', '.txt', '.log', '.json', '.csv',
  // no extension files (POSCAR, INCAR, etc.) — user picks these manually
].join(',')

export default function UploadButton({
  sessionId,          // current session id — null if no session yet
  onUploadDone,       // called with (sessionId, uploadedFiles) after success
  onSessionCreated,   // called with new session_id if one was created
  disabled,           // true while chat is streaming
}) {
  const fileInputRef = useRef(null)
  const [status, setStatus] = useState(null)
  // status: null | 'uploading' | 'done' | 'error'

  async function handleFiles(e) {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return

    // reset the input so the same file can be picked again
    e.target.value = ''

    setStatus('uploading')

    try {
      let sid = sessionId
      let uploadedFiles

      if (sid) {
        // existing session — upload directly
        uploadedFiles = await uploadFiles(sid, files)
      } else {
        // no session yet — create one then upload
        const result = await createSessionAndUpload(files)
        sid           = result.session_id
        uploadedFiles = result.files
        onSessionCreated?.(sid)
      }

      setStatus('done')
      onUploadDone?.(sid, uploadedFiles)

      // clear status after 2 seconds
      setTimeout(() => setStatus(null), 2000)

    } catch (err) {
      console.error('Upload error:', err)
      setStatus('error')
      setTimeout(() => setStatus(null), 3000)
    }
  }

  // style changes based on upload status
  const iconColor = {
    null:        'var(--text-muted)',
    uploading:   '#6366f1',
    done:        '#166534',
    error:       '#b91c1c',
  }[status]

const icon = {
  null: '📎',
  uploading: '⏳',
  done: '✔',
  error: '⚠',
}[status]

  const title = {
    null:        'Upload POSCAR, CIF, INCAR, KPOINTS…',
    uploading:   'Uploading…',
    done:        'Uploaded successfully',
    error:       'Upload failed — check file type',
  }[status]

  return (
    <>
      {/* hidden file input — triggered by button click */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPT}
        onChange={handleFiles}
        style={{ display: 'none' }}
      />

      {/* visible button — matches the input area style */}
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || status === 'uploading'}
        title={title}
        style={{
          background: 'none',
          border: 'none',
          color: iconColor,
          cursor: disabled || status === 'uploading' ? 'not-allowed' : 'pointer',
          fontSize: status === 'uploading' ? '16px' : '20px',
          padding: '4px 8px 4px 0',
          flexShrink: 0,
          lineHeight: 1,
          transition: 'color 0.15s',
          // spin animation while uploading
          animation: status === 'uploading' ? 'spin 0.8s linear infinite' : 'none',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {icon}
      </button>
    </>
  )
}