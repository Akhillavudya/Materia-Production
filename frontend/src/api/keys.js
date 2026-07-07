/**
 * API-key manager. A user can pool several keys per service; the LLM
 * key-rotation cycles through them when one hits its rate limit.
 */

import { authRequest, readError } from './client'

// Append a key to the user's pool for a service.
export async function saveApiKey(service, apiKey) {
  const res = await authRequest('/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service, key_value: apiKey }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not save API key'))
  return res.json()
}

// List each service with its pooled key count + masked hints (values never returned).
export async function listKeys() {
  const res = await authRequest('/keys', { method: 'GET' })
  if (!res.ok) throw new Error(await readError(res, 'Could not load API keys'))
  return res.json()   // -> [{ service, exists, count, keys: [{ index, hint }] }]
}

// Remove one key from a service's pool by its position.
export async function deleteKeyAt(service, index) {
  const res = await authRequest(`/keys/${service}/${index}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await readError(res, 'Could not remove API key'))
  return res.json()
}

// Remove every key the user has for a service.
export async function deleteKey(service) {
  const res = await authRequest(`/keys/${service}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await readError(res, 'Could not remove API key'))
  return res.json()
}
