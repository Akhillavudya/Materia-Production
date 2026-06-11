/**
 * Chat streaming API.
 *
 * The backend emits a custom SSE protocol:
 *   data: {"type":"token","value":"..."}  — text token
 *   data: {"type":"status","value":"..."}  — spinner label
 *   data: [FILES:{...json...}]             — tool result card
 *   data: [TOOL_START:<name>]
 *   data: [TOOL_END:<name>:<status>]
 *   data: [NEED_API_KEY:<service>]
 *   data: [SESSION:<id>]
 *   data: [DONE]
 */

import { authRequest, readError } from './client'

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
  options = {},
) {
  try {
    const response = await authRequest('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: options.signal,
      body: JSON.stringify({ session_id: sessionId || null, message }),
    })

    if (!response.ok) {
      const msg = response.status === 401
        ? 'Session expired. Please log in again.'
        : await readError(response, `Server error: ${response.status}`)
      onError(msg)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const handleLine = (line) => {
      if (!line.startsWith('data: ')) return
      const payload = line.slice(6).trim()
      if (!payload) return

      if (payload.startsWith('{')) {
        try {
          const obj = JSON.parse(payload)
          if (obj.type === 'token') { onToken(obj.value); return }
          if (obj.type === 'status') { onStatus?.(obj.value); return }
        } catch { return }
        return
      }

      if (payload === '[DONE]') { onDone(); return }

      if (payload.startsWith('[SESSION:')) {
        onSessionId(payload.slice(9, -1))
        return
      }

      if (payload.startsWith('[FILES:')) {
        const jsonStr = payload.slice(7, payload.lastIndexOf(']') === payload.length - 1
          ? payload.length - 1
          : payload.length)
        try { onFiles(JSON.parse(jsonStr)) } catch (e) {
          console.warn('[streamChat] Failed to parse FILES payload', e, jsonStr)
        }
        return
      }

      if (payload.startsWith('[TOOL_START:')) {
        onToolStart(payload.slice(12, -1))
        return
      }

      if (payload.startsWith('[NEED_API_KEY:')) {
        onNeedApiKey?.(payload.slice(14, -1))
        return
      }

      if (payload.startsWith('[TOOL_END:')) {
        const inner = payload.slice(10, -1)
        const colon = inner.lastIndexOf(':')
        const tName = colon >= 0 ? inner.slice(0, colon) : inner
        const status = colon >= 0 ? inner.slice(colon + 1) : 'unknown'
        onToolEnd(tName, status)
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) handleLine(line)
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
