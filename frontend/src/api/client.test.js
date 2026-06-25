// Token & session storage helpers (Step 9 frontend test net).
//
// These pure functions back every authenticated request — if they ever stop
// round-tripping the token/user through localStorage, login silently breaks.
import { describe, it, expect, beforeEach } from 'vitest'

import {
  getAuthToken,
  getStoredUser,
  setAuthSession,
  clearAuthSession,
} from './client.js'

beforeEach(() => {
  localStorage.clear()
})

describe('auth session helpers', () => {
  it('stores and reads back the access token and user', () => {
    const user = { id: 1, email: 'lab@example.com' }
    const returned = setAuthSession({ access_token: 'tok_abc', user })

    expect(returned).toEqual(user)
    expect(getAuthToken()).toBe('tok_abc')
    expect(getStoredUser()).toEqual(user)
  })

  it('returns null when nothing is stored', () => {
    expect(getAuthToken()).toBeNull()
    expect(getStoredUser()).toBeNull()
  })

  it('clears the token and user on logout', () => {
    setAuthSession({ access_token: 'tok_abc', user: { id: 1 } })
    clearAuthSession()

    expect(getAuthToken()).toBeNull()
    expect(getStoredUser()).toBeNull()
  })

  it('survives a corrupt stored user without throwing', () => {
    localStorage.setItem('materia_user', '{not valid json')
    expect(getStoredUser()).toBeNull()
  })
})
