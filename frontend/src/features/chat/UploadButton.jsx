import { useRef, useState } from 'react'
import { Plus, Loader2, Check, AlertCircle } from 'lucide-react'
import { uploadFiles, createSessionAndUpload } from '../../api'

// ── which file types the browser file picker will accept ─────────────────────
const ACCEPT = [
  // structure formats (validated on the backend)
  '.cif', '.xyz', '.vasp', '.poscar', '.contcar', '.cssr',
  '.pwscf', '.in', '.pdb', '.xsf', '.res', '.gen',
  // text / data
  '.txt', '.log', '.json', '.csv',
  // no-extension files (POSCAR, INCAR, etc.) — user picks these manually
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
      let activation

      if (sid) {
        // existing session — upload directly
        const res    = await uploadFiles(sid, files)
        uploadedFiles = res.files
        activation    = res.activation
      } else {
        // no session yet — create one then upload
        const result = await createSessionAndUpload(files)
        sid           = result.session_id
        uploadedFiles = result.files
        activation    = result.activation
        onSessionCreated?.(sid)
      }

      setStatus('done')
      onUploadDone?.(sid, uploadedFiles, activation)

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
    null:        'var(--text-secondary)',
    uploading:   'var(--accent-solid)',
    done:        'var(--status-ok-fg)',
    error:       'var(--status-fail-fg)',
  }[status]

  // Claude-style: a single clean "+" to attach files; swaps to a status glyph
  const IconCmp = {
    null:      Plus,
    uploading: Loader2,
    done:      Check,
    error:     AlertCircle,
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

      {/* visible button — clean circular "+" (Claude-style attach control) */}
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || status === 'uploading'}
        title={title}
        style={{
          width: '34px',
          height: '34px',
          borderRadius: '50%',
          background: 'transparent',
          border: '1px solid var(--border)',
          color: iconColor,
          cursor: disabled || status === 'uploading' ? 'not-allowed' : 'pointer',
          flexShrink: 0,
          marginRight: '8px',
          lineHeight: 1,
          transition: 'background 0.15s, color 0.15s, border-color 0.15s',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onMouseEnter={e => { if (!disabled && status !== 'uploading') { e.currentTarget.style.background = 'var(--hover-bg)'; e.currentTarget.style.borderColor = 'var(--text-muted)' } }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'var(--border)' }}
      >
        <IconCmp
          size={18}
          strokeWidth={2}
          style={{ animation: status === 'uploading' ? 'spin 0.8s linear infinite' : 'none' }}
        />
      </button>
    </>
  )
}