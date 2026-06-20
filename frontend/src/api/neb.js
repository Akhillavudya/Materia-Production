/**
 * NEB workflow launch (UI panel).
 *
 * Posts two endpoint structures (initial + final) directly to the backend, which
 * stores them and enqueues an NEB job via the same compute_neb tool the agent
 * uses. Bypasses chat/file-resolution so the user explicitly picks both states.
 */

import { authRequest, readError } from './client'

export async function launchNeb(sessionId, initialFile, finalFile, opts = {}) {
  const form = new FormData()
  form.append('initial', initialFile)
  form.append('final', finalFile)
  if (opts.nImages != null) form.append('n_images', String(opts.nImages))
  if (opts.calculatorType) form.append('calculator_type', opts.calculatorType)
  if (opts.calculatorModel) form.append('calculator_model', opts.calculatorModel)
  form.append('climb', opts.climb === false ? 'false' : 'true')

  const res = await authRequest(`/sessions/${sessionId}/neb`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await readError(res, 'Failed to start NEB'))
  return res.json()
}
