/**
 * Authentication API — signup, login, session validation.
 */

import { apiBase, authRequest, readError, setAuthSession } from './client'

// Resolve the same base as client.js (same-origin on web, dynamic localhost port
// on desktop) so the unauthenticated signup/login/config fetches below work there.
const API = apiBase

export async function signup(email, password, fullName = '', inviteCode = '') {
  const res = await fetch(`${API}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name: fullName, invite_code: inviteCode }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not create account'))
  return setAuthSession(await res.json())
}

// Public hint for the signup + tools UI, e.g.
//   { signup_mode: 'open'|'invite'|'closed', heavy_tools_enabled: bool }.
// Falls back to open signup + heavy tools enabled so the app still works (and
// never wrongly hides simulation tools) if the call fails.
export async function getAuthConfig() {
  try {
    const res = await fetch(`${API}/auth/config`)
    if (!res.ok) return { signup_mode: 'open', heavy_tools_enabled: true }
    return await res.json()
  } catch {
    return { signup_mode: 'open', heavy_tools_enabled: true }
  }
}

export async function login(email, password) {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not sign in'))
  return setAuthSession(await res.json())
}

// Exchange a Google Identity Services credential (ID token) for a Materia session.
export async function googleLogin(credential) {
  const res = await fetch(`${API}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not sign in with Google'))
  return setAuthSession(await res.json())
}

export async function getMe() {
  const res = await authRequest('/auth/me')
  if (!res.ok) throw new Error(await readError(res, 'Could not load user'))
  const user = await res.json()
  localStorage.setItem('materia_user', JSON.stringify(user))
  return user
}

export const fetchMe = getMe

// Update the signed-in user's editable profile fields (display name).
export async function updateProfile({ fullName }) {
  const res = await authRequest('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ full_name: fullName }),
  })
  if (!res.ok) throw new Error(await readError(res, 'Could not save profile'))
  const user = await res.json()
  localStorage.setItem('materia_user', JSON.stringify(user))
  return user
}
