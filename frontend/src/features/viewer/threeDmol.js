/**
 * Lazy-load 3Dmol.js from CDN exactly once and hand back window.$3Dmol.
 * Shared by the inline StructureViewer modal and the full-screen
 * StructureWorkspace so the heavy script is fetched a single time.
 */

let _loaded = false
let _loading = false
let _callbacks = []

export function load3Dmol() {
  return new Promise((resolve, reject) => {
    if (_loaded) { resolve(window.$3Dmol); return }

    _callbacks.push({ resolve, reject })

    if (_loading) return
    _loading = true

    const script = document.createElement('script')
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.1.0/3Dmol-min.js'
    script.integrity = 'sha384-TxfnTy2TY3ms7kc3hVNjePx2ekn5oouyllBzqjsaZMmtran9oNs+yTKd0TY+x0eY'
    script.crossOrigin = 'anonymous'
    script.onload = () => {
      _loaded = true
      _callbacks.forEach(cb => cb.resolve(window.$3Dmol))
      _callbacks = []
    }
    script.onerror = () => {
      _loading = false
      _callbacks.forEach(cb => cb.reject(new Error('Failed to load 3Dmol.js')))
      _callbacks = []
    }
    document.head.appendChild(script)
  })
}
