/**
 * C2DB search API.
 * The backend proxies this through the main chat SSE stream; this endpoint
 * is reserved for direct queries when that route is added.
 */

import { authRequest, readError } from './client'

const C2DB_BASE = '/c2db'

export async function searchC2DB(params) {
  const qs = new URLSearchParams(
    Object.entries(params || {})
      .filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
  const res = await authRequest(`${C2DB_BASE}/search?${qs.toString()}`)
  if (!res.ok) throw new Error(await readError(res, 'Could not search C2DB materials'))
  return res.json()
}
