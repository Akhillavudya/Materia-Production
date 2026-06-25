/**
 * Loader for Google Identity Services (GIS).
 *
 * Injects the official `https://accounts.google.com/gsi/client` script once and
 * resolves with the global `window.google` object so callers can initialise and
 * render the Sign-in-with-Google button. Subsequent calls reuse the same promise.
 */

const GIS_SRC = 'https://accounts.google.com/gsi/client'
let gisPromise = null

export function loadGoogleIdentity() {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'))
  if (window.google?.accounts?.id) return Promise.resolve(window.google)
  if (gisPromise) return gisPromise

  gisPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GIS_SRC}"]`)
    const onReady = () => {
      if (window.google?.accounts?.id) resolve(window.google)
      else reject(new Error('Google Identity Services failed to initialise'))
    }
    if (existing) {
      existing.addEventListener('load', onReady, { once: true })
      existing.addEventListener('error', () => reject(new Error('Failed to load Google script')), { once: true })
      if (window.google?.accounts?.id) onReady()
      return
    }
    const script = document.createElement('script')
    script.src = GIS_SRC
    script.async = true
    script.defer = true
    script.onload = onReady
    script.onerror = () => { gisPromise = null; reject(new Error('Failed to load Google script')) }
    document.head.appendChild(script)
  })
  return gisPromise
}
