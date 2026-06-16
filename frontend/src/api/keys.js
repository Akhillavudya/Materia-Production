/**
 * API-key manager.
 */

import { authRequest, readError } from './client'

export async function saveApiKey(service, apiKey) {
  const res = await authRequest('/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service, key_value: apiKey }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not save API key'))
  return res.json()
}

// List which services the current user has a saved key for (values never returned).
export async function listKeys() {
  const res = await authRequest('/keys', { method: 'GET' })
  if (!res.ok) throw new Error(await readError(res, 'Could not load API keys'))
  return res.json()   // -> [{ service, exists }]
}

export async function deleteKey(service) {
  const res = await authRequest(`/keys/${service}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await readError(res, 'Could not remove API key'))
  return res.json()
}
