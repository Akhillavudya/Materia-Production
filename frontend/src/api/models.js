/**
 * ML-potential model manager (desktop Part C / C2).
 *
 * Lists the downloadable MACE / MatterSim checkpoints with on-disk availability
 * and live download progress, and triggers downloads. Backed by /api/models,
 * which only exists when the server runs heavy tools locally (the desktop app);
 * on the lite web edition these calls 404 and the UI hides itself.
 */

import { authRequest, readError } from './client'

// -> { models: [{ name, type, recommended, approx_mb, exists, status,
//                 downloaded, total, error }], present, total }
export async function listModels() {
  const res = await authRequest('/models', { method: 'GET' })
  if (!res.ok) throw new Error(await readError(res, 'Could not load models'))
  return res.json()
}

// selection: 'recommended' | 'all' | array of model names. -> { queued, requested }
export async function downloadModels(selection = 'recommended') {
  const res = await authRequest('/models/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models: selection }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not start download'))
  return res.json()
}

// Offline chat brain (Ollama). Unlike the checkpoints above it lives in a
// separately-installed Ollama server, so the shape differs.
// -> { model, server, present, status, downloaded, total, phase, error }
export async function getLlm() {
  const res = await authRequest('/models/llm', { method: 'GET' })
  if (!res.ok) throw new Error(await readError(res, 'Could not load offline model'))
  return res.json()
}

// Start `ollama pull <model>` in the background. -> status + { queued, reason }
export async function pullLlm() {
  const res = await authRequest('/models/llm/pull', { method: 'POST' })
  if (!res.ok) throw new Error(await readError(res, 'Could not start model download'))
  return res.json()
}
