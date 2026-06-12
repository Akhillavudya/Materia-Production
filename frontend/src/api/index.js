/**
 * Barrel re-export of all API slices.
 *
 * Components may import directly from a slice (preferred for new code) or
 * from this barrel (safe for existing imports).
 *
 *   import { streamChat } from '../api/chat'   ← slice import (preferred)
 *   import { streamChat } from '../api'        ← barrel import (also works)
 */

export * from './client'
export * from './auth'
export * from './sessions'
export * from './chat'
export * from './files'
export * from './keys'
export * from './c2db'
export * from './jobs'
