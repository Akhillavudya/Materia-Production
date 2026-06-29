/**
 * Compute-device / build-variant info (desktop Part C / C4 — the GPU pack).
 *
 * Backed by /api/system, which only exists when the server runs heavy tools
 * locally (the desktop app). On the lite web edition it 404s and callers hide the
 * device badge. Lets the UI show whether simulations run on the GPU or the CPU —
 * and surface a GPU build that quietly fell back to CPU.
 */

import { authRequest, readError } from './client'

// -> { variant: 'cpu'|'gpu', device: 'cpu'|'cuda'|'mps',
//      cuda_available: bool, gpu_name: string|null, torch_version: string|null }
export async function getSystem() {
  const res = await authRequest('/system', { method: 'GET' })
  if (!res.ok) throw new Error(await readError(res, 'Could not load system info'))
  return res.json()
}
