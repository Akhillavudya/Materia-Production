/**
 * Direct tool-launch API (UI tool panel).
 *
 * Posts an optional structure file + curated parameters straight to the backend,
 * which stores the file (if any) and enqueues the same async job the chat agent
 * uses. Leaving the file out makes the tool auto-detect the session's active
 * structure. Each call returns the queued-job envelope ({ job_id, ... }).
 */

import { authRequest, readError } from './client'

/** Build FormData: attach the file only when present, stringify every param. */
function buildForm(file, params) {
  const form = new FormData()
  if (file) form.append('structure', file)
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') form.append(k, String(v))
  }
  return form
}

async function launch(sessionId, endpoint, file, params, errLabel) {
  const res = await authRequest(`/sessions/${sessionId}/${endpoint}`, {
    method: 'POST',
    body: buildForm(file, params),
  })
  if (!res.ok) throw new Error(await readError(res, errLabel))
  return res.json()
}

export const launchOptimize = (sessionId, file, params) =>
  launch(sessionId, 'optimize', file, params, 'Failed to start optimization')

export const launchMd = (sessionId, file, params) =>
  launch(sessionId, 'md', file, params, 'Failed to start MD')

export const launchPhonons = (sessionId, file, params) =>
  launch(sessionId, 'phonons', file, params, 'Failed to start phonons')

export const launchElastic = (sessionId, file, params) =>
  launch(sessionId, 'elastic', file, params, 'Failed to start mechanical')

export const launchSqs = (sessionId, file, params) =>
  launch(sessionId, 'sqs', file, params, 'Failed to start SQS')
