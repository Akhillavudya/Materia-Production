/**
 * Sessions API — list, messages, export.
 */

import { authRequest, downloadBlob, readError } from './client'

export async function fetchSessions() {
  const res = await authRequest('/sessions')
  if (!res.ok) throw new Error(await readError(res, 'Could not load sessions'))
  return res.json()
}

export async function fetchMessages(sessionId) {
  const res = await authRequest(`/sessions/${sessionId}/messages`)
  if (!res.ok) throw new Error(await readError(res, 'Could not load messages'))
  const messages = await res.json()

  return messages.map(m => {
    let toolCards = []
    if (m.tool_result) {
      try {
        const parsed = JSON.parse(m.tool_result)
        if (Array.isArray(parsed)) {
          toolCards = parsed.map(r => ({
            toolName: r.tool,
            label: r.label || r.tool,
            status: r.status,
            files: r.files || [],
          }))
        } else if (parsed && typeof parsed === 'object') {
          toolCards = [{
            toolName: parsed.tool,
            label: parsed.label || parsed.tool,
            status: parsed.status,
            files: parsed.files || [],
          }]
        }
      } catch {
        toolCards = []
      }
    }
    return { ...m, toolCards }
  })
}

export async function downloadSessionTxt(sessionId) {
  if (!sessionId) return
  return downloadBlob(
    `/sessions/${sessionId}/export/txt`,
    `materia-session-${sessionId.slice(0, 8)}.txt`,
  )
}

export async function fetchJobs(sessionId) {
  const res = await authRequest(`/sessions/${sessionId}/jobs`)
  if (!res.ok) throw new Error(await readError(res, 'Could not load jobs'))
  return res.json()
}

export async function downloadSessionJson(sessionId) {
  if (!sessionId) return
  return downloadBlob(
    `/sessions/${sessionId}/export/json`,
    `materia-session-${sessionId.slice(0, 8)}.json`,
  )
}
