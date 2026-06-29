/**
 * Base HTTP client with auth headers, 401 handling and error normalisation.
 * All other api/* modules build on these primitives.
 */

// Same-origin "/api" by default (Caddy proxies it to the backend). The desktop app
// loads the SPA from file:// and runs the backend on a dynamic localhost port, so the
// Electron preload injects the absolute base on window.__MATERIA_API__. Priority:
// runtime global → build-time env → same-origin. The global is undefined in the
// browser build, so the web app is unaffected.
const API =
  (typeof window !== 'undefined' && window.__MATERIA_API__) ||
  import.meta.env.VITE_API_BASE_URL ||
  '/api'
// Re-exported so the few modules that issue *unauthenticated* fetches (auth.js)
// resolve the same base — otherwise they'd hit a literal "/api" which is broken
// under the desktop's file:// + dynamic-port setup.
export const apiBase = API
// True only inside the Electron desktop shell (its preload sets window.__MATERIA_API__).
// Used to gate desktop-only UI such as the local model-download screen.
export const isDesktop = typeof window !== 'undefined' && !!window.__MATERIA_API__
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
