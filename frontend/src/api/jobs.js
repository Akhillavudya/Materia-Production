/**
 * Async simulation jobs (redesign §13).
 *
 * optimize_structure / run_md_simulation no longer block the chat stream — they
 * enqueue a job that runs in a separate worker. These helpers drive the live
 * job dashboard against /api/jobs.
 */

import { authRequest, readError } from './client'

export async function listAsyncJobs(sessionId) {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  const res = await authRequest(`/jobs${q}`)
  if (!res.ok) throw new Error(await readError(res, 'Failed to load jobs'))
  return res.json()
}

export async function getAsyncJob(jobId) {
  const res = await authRequest(`/jobs/${jobId}`)
  if (!res.ok) throw new Error(await readError(res, 'Failed to load job'))
  return res.json()
}

export async function cancelAsyncJob(jobId) {
  const res = await authRequest(`/jobs/${jobId}/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error(await readError(res, 'Failed to cancel job'))
  return res.json()
}

/**
 * Stream a single job's progress over SSE until it reaches a terminal state.
 * Mirrors the fetch-based reader used by streamChat (EventSource can't send the
 * auth header). Returns a function that aborts the stream.
 */
export function streamAsyncJob(jobId, onUpdate, onDone, onError) {
  const controller = new AbortController()

  ;(async () => {
    try {
      const res = await authRequest(`/jobs/${jobId}/stream`, { signal: controller.signal })
      if (!res.ok || !res.body) {
        onError?.(await readError(res, 'Stream failed'))
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const handle = (line) => {
        if (!line.startsWith('data: ')) return
        const payload = line.slice(6).trim()
        if (!payload || payload === '[DONE]') return
        try {
          const obj = JSON.parse(payload)
          if (obj.type === 'done') onDone?.(obj)
          else onUpdate?.(obj)
        } catch { /* ignore keep-alives */ }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) handle(line)
      }
    } catch (err) {
      if (err.name !== 'AbortError') onError?.(err.message)
    }
  })()

  return () => controller.abort()
}
