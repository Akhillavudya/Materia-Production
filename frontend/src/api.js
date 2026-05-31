const API = '/api'

export async function streamChat(
  sessionId,
  message,
  onToken,
  onSessionId,
  onFiles,
  onToolStart,
  onToolEnd,
  onStatus,      
  onNeedApiKey,
  onJobDone,
  onDone,
  onError,
  options = {}
) {
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: options.signal,
      body: JSON.stringify({
        session_id: sessionId || null,
        message,
      }),
    })

    if (!response.ok) { onError(`Server error: ${response.status}`); return }

    const reader  = response.body.getReader()
    const decoder = new TextDecoder()
    let   buffer  = ''   // accumulate partial SSE lines across chunks

    const handleLine = (line) => {
      if (!line.startsWith('data: ')) return
      const payload = line.slice(6).trim()
      if (!payload) return

      // ── JSON events: { type, value } ─────────────────────────────────
      if (payload.startsWith('{')) {
        try {
          const obj = JSON.parse(payload)

          if (obj.type === 'token') {
            onToken(obj.value)
            return
          }

          if (obj.type === 'status') {
            // status events show a transient label — NEVER go into token text
            onStatus?.(obj.value)
            return
          }
        } catch {
          // malformed JSON — drop silently, don't leak to chat
          return
        }
        return   // any other JSON type — ignore, don't fall through to onToken
      }

      // ── bracket events ────────────────────────────────────────────────
      if (payload === '[DONE]') {
        onDone()
        return
      }

      if (payload.startsWith('[SESSION:')) {
        onSessionId(payload.slice(9, -1))
        return
      }

      if (payload.startsWith('[FILES:')) {
        // payload: [FILES:{...json...}]
        // the JSON object itself may contain ']' so we strip only the outer wrapper
        const jsonStr = payload.slice(7, payload.lastIndexOf(']') === payload.length - 1
          ? payload.length - 1
          : payload.length)
        try { onFiles(JSON.parse(jsonStr)) } catch (e) {
          console.warn('[streamChat] Failed to parse FILES payload', e, jsonStr)
        }
        return
      }

      if (payload.startsWith('[TOOL_START:')) {
        const toolName = payload.slice(12, -1)
        onToolStart(toolName)
        return
      }

      if (payload.startsWith('[TOOL_END:')) {
        // [TOOL_END:tool_name:status]
        const inner = payload.slice(10, -1)           // "tool_name:status"
        const colon = inner.lastIndexOf(':')
        const tName  = colon >= 0 ? inner.slice(0, colon) : inner
        const status = colon >= 0 ? inner.slice(colon + 1) : 'unknown'
        onToolEnd(tName, status)
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // accumulate — a single read() may contain partial lines
      buffer += decoder.decode(value, { stream: true })

      // split on double-newline (SSE event boundary)
      // or single newline (our backend sends one event per line)
      const lines = buffer.split('\n')
      // keep the last (potentially incomplete) line in the buffer
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        handleLine(line)
      }
    }

    const tail = buffer.trim()
    if (tail) handleLine(tail)
  } catch (err) {
    if (err.name === 'AbortError') {
      options.onAbort?.()
      return
    }
    onError(err.message)
  }
}

export async function fetchSessions() {
  const res = await fetch('/api/sessions')
  if (!res.ok) throw new Error('Could not load sessions')
  return res.json()
}

// export async function fetchMessages(sessionId) {
//   const res = await fetch(`${API}/sessions/${sessionId}/messages`)
//   if (!res.ok) throw new Error('Could not load messages')
//   const messages = await res.json()

//   return messages.map(m => ({
//     ...m,
//     toolCards: m.tool_result ? (() => {
//       try {
//         const parsed = JSON.parse(m.tool_result)
//         // tool_result from DB is a single object — wrap in array for uniform rendering
//         return parsed ? [parsed] : []
//       } catch { return [] }
//     })() : [],
//   }))
// }

export async function fetchMessages(sessionId) {
  const res = await fetch(`${API}/sessions/${sessionId}/messages`)
  if (!res.ok) throw new Error('Could not load messages')
  const messages = await res.json()

  return messages.map(m => {
    let toolCards = []

    if (m.tool_result) {
      try {
        const parsed = JSON.parse(m.tool_result)
        if (Array.isArray(parsed)) {
          // new format — array of tool results (one per tool call)
          toolCards = parsed.map(r => ({
            toolName: r.tool,
            label:    r.label || r.tool,
            status:   r.status,
            files:    r.files || [],
          }))
        } else if (parsed && typeof parsed === 'object') {
          // old format — single object, wrap in array
          toolCards = [{
            toolName: parsed.tool,
            label:    parsed.label || parsed.tool,
            status:   parsed.status,
            files:    parsed.files || [],
          }]
        }
      } catch {
        toolCards = []
      }
    }

    return { ...m, toolCards }
  })
}

export async function fetchSessionFilesGrouped(sessionId) {
  const res = await fetch(`/api/sessions/${sessionId}/files/grouped`)
  if (!res.ok) throw new Error('Could not load files')
  return res.json()
}

export async function fetchFileContent(relPath) {
  const res = await fetch(`/api/files/content/${relPath}`)
  if (!res.ok) throw new Error(`Could not read file: ${res.status}`)
  return res.json()
}

export async function downloadSessionTxt(sessionId) {
  if (!sessionId) return
  const response = await fetch(`/api/sessions/${sessionId}/export/txt`)
  if (!response.ok) throw new Error('Failed to download session')
  const blob = await response.blob()
  const url  = window.URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `materia-session-${sessionId.slice(0, 8)}.txt`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export async function downloadSessionJson(sessionId) {
  if (!sessionId) return
  const response = await fetch(`/api/sessions/${sessionId}/export/json`)
  if (!response.ok) throw new Error('Failed to download session JSON')
  const blob = await response.blob()
  const url  = window.URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `materia-session-${sessionId.slice(0, 8)}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export async function fetchJobs(sessionId) {
  const res = await fetch(`/api/sessions/${sessionId}/jobs`)
  if (!res.ok) throw new Error('Could not load jobs')
  return res.json()
}

export async function saveApiKey(service, apiKey) {
  const res = await fetch('/api/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service, api_key: apiKey }),
  })
  if (!res.ok) throw new Error('Could not save API key')
  return res.json()
}

export async function uploadFiles(sessionId, files) {
  const formData = new FormData()
  for (const file of files) formData.append('files', file)
  const res = await fetch(`/api/sessions/${sessionId}/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()
}

export async function createSessionAndUpload(files) {
  const formData = new FormData()
  for (const file of files) formData.append('files', file)
  const res = await fetch('/api/sessions/create-and-upload', {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()
}
