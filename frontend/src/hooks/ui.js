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

function readStoredTheme() {
  if (typeof window === 'undefined') return 'light'
  const saved = window.localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  // honour the OS preference on first visit
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * App theme ('light' | 'dark'). Persists to localStorage and reflects onto
 * <html data-theme> so the CSS variable overrides take effect everywhere.
 */
export function useTheme() {
  const [theme, setTheme] = useState(readStoredTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const toggleTheme = useCallback(
    () => setTheme(t => (t === 'dark' ? 'light' : 'dark')),
    []
  )

  return { theme, toggleTheme, setTheme }
}
