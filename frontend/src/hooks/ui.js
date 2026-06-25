import { useEffect, useState, useCallback } from 'react'

// Mobile breakpoint — matches the < 768px rule used across the responsive CSS.
const MOBILE_QUERY = '(max-width: 767px)'

/**
 * Returns true when the viewport is at/below the mobile breakpoint.
 * Uses matchMedia so it updates live on resize / orientation change.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
  )

  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY)
    const onChange = (e) => setIsMobile(e.matches)
    // addEventListener is the modern API; fall back for older Safari
    if (mq.addEventListener) mq.addEventListener('change', onChange)
    else mq.addListener(onChange)
    setIsMobile(mq.matches)
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange)
      else mq.removeListener(onChange)
    }
  }, [])

  return isMobile
}

/**
 * Locks <body> scrolling while `locked` is true — used so the page behind an
 * open drawer / bottom-sheet doesn't scroll on touch devices.
 */
export function useBodyScrollLock(locked) {
  useEffect(() => {
    if (!locked) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [locked])
}

const THEME_KEY = 'materia-theme'

// The user's chosen preference: an explicit 'light'/'dark', or 'system' to
// follow the OS. This is what we persist.
function readStoredMode() {
  if (typeof window === 'undefined') return 'system'
  const saved = window.localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  // first visit (or legacy value): follow the OS by default
  return 'system'
}

function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * App theme controller.
 *
 *   mode     — the user's preference: 'light' | 'dark' | 'system' (persisted)
 *   theme    — the *resolved* theme actually applied: 'light' | 'dark'
 *
 * In 'system' mode `theme` tracks the OS preference live. The resolved theme is
 * reflected onto <html data-theme> so the CSS variable overrides take effect.
 */
export function useTheme() {
  const [mode, setModeState] = useState(readStoredMode)
  const [theme, setTheme] = useState(() =>
    readStoredMode() === 'system' ? systemTheme() : readStoredMode()
  )

  // Recompute the resolved theme when the mode changes, and — only while in
  // 'system' mode — keep it in sync with live OS preference changes.
  useEffect(() => {
    const apply = () => setTheme(mode === 'system' ? systemTheme() : mode)
    apply()
    if (mode !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply()
    if (mq.addEventListener) mq.addEventListener('change', onChange)
    else mq.addListener(onChange)
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange)
      else mq.removeListener(onChange)
    }
  }, [mode])

  // Reflect the resolved theme onto the document.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const setMode = useCallback((next) => {
    setModeState(next)
    window.localStorage.setItem(THEME_KEY, next)
  }, [])

  // Explicit light/dark flip (used by the chat header button). Picks the
  // opposite of whatever is currently showing and pins it as an explicit mode.
  const toggleTheme = useCallback(
    () => setMode(theme === 'dark' ? 'light' : 'dark'),
    [theme, setMode]
  )

  return { theme, mode, setMode, toggleTheme }
}
