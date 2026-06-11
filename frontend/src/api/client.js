/**
 * Base HTTP client with auth headers, 401 handling and error normalisation.
 * All other api/* modules build on these primitives.
 */

const API = '/api'
const TOKEN_KEY = 'materia_access_token'
const USER_KEY = 'materia_user'

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser() {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

export function setAuthSession(auth) {
  localStorage.setItem(TOKEN_KEY, auth.access_token)
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user))
  return auth.user
}

export function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function logout() {
  clearAuthSession()
}

export function notifyAuthExpired() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('materia-auth-expired', {
    detail: { message: 'Session expired. Please log in again.' },
  }))
}

function authHeaders(extra = {}) {
  const token = getAuthToken()
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export async function readError(res, fallback) {
  const payload = await res.json().catch(() => null)
  return payload?.detail || fallback
}

export async function authRequest(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: authHeaders(options.headers || {}),
  })

  if (res.status === 401) {
    clearAuthSession()
    notifyAuthExpired()
  }

  return res
}

export async function downloadBlob(path, fileName) {
  const response = await authRequest(path)
  if (!response.ok) throw new Error(await readError(response, 'Failed to download file'))
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
