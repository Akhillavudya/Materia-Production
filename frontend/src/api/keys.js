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
