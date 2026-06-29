// Locates, configures and launches the bundled (PyInstaller-frozen) Materia backend
// as a child process bound to 127.0.0.1, and waits until it answers /health.
//
// Design notes:
//  - The backend runs in JOB_BACKEND=inline mode (heavy jobs run in a daemon thread),
//    so there is NO Celery/Redis to manage. ENABLE_HEAVY_TOOLS is left ON (default).
//  - All mutable state (SQLite DB, models, local secrets) lives under Electron's
//    userData dir, so the install directory can stay read-only.
//  - Local JWT/Fernet secrets are generated once and persisted, so encrypted BYOK
//    API keys survive restarts.

const { app } = require('electron')
const { spawn } = require('child_process')
const net = require('net')
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const http = require('http')

let child = null

// Which build is this — the CPU installer or the GPU (CUDA) installer (C4)?
// electron-builder stamps `materiaVariant` into package.json via extraMetadata in
// CI (--config.extraMetadata.materiaVariant=gpu); defaults to 'cpu' for dev/local
// builds. The GPU build ships CUDA torch and lets the backend auto-detect the GPU;
// the CPU build pins cpu and hides any GPU so a stray CUDA torch can't JIT-crash.
function buildVariant () {
  if (process.env.MATERIA_VARIANT) return process.env.MATERIA_VARIANT.toLowerCase()
  try {
    return (require('../package.json').materiaVariant || 'cpu').toLowerCase()
  } catch {
    return 'cpu'
  }
}

// Pick a free TCP port by binding to 0 and reading back the assigned port.
function getFreePort () {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

// Absolute path to the frozen backend executable, in dev and packaged layouts.
function backendExePath () {
  const exeName = process.platform === 'win32' ? 'materia-backend.exe' : 'materia-backend'
  if (app.isPackaged) {
    // electron-builder places extraResources under process.resourcesPath (C3).
    return path.join(process.resourcesPath, 'backend', 'materia-backend', exeName)
  }
  // Dev/spike: the bundle sits in desktop/resources/backend/.
  return path.join(__dirname, '..', 'resources', 'backend', 'materia-backend', exeName)
}

// Generate-once, persist local secrets so BYOK keys remain decryptable across runs.
function loadOrCreateSecrets (userData) {
  const file = path.join(userData, 'secrets.json')
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    const secrets = {
      JWT_SECRET_KEY: crypto.randomBytes(48).toString('base64url'),
      // A Fernet key is urlsafe-base64 of 32 random bytes (keep the '=' padding).
      FIELD_ENCRYPTION_KEY: crypto.randomBytes(32).toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_')
    }
    fs.writeFileSync(file, JSON.stringify(secrets, null, 2), { mode: 0o600 })
    return secrets
  }
}

// Poll GET /health until the server answers or we time out.
function waitForHealth (port, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: 2000 }, (res) => {
        res.resume()
        if (res.statusCode === 200) return resolve()
        retry()
      })
      req.on('error', retry)
      req.on('timeout', () => { req.destroy(); retry() })
    }
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error('backend did not become healthy in time'))
      setTimeout(tick, 500)
    }
    tick()
  })
}

// Start the backend; returns { port }.
async function startBackend () {
  const exe = backendExePath()
  if (!fs.existsSync(exe)) {
    throw new Error(`backend executable not found: ${exe}\nRun: npm run build:backend`)
  }

  const userData = app.getPath('userData')
  const modelsDir = path.join(userData, 'models')
  const storageDir = path.join(userData, 'storage')
  fs.mkdirSync(modelsDir, { recursive: true })
  fs.mkdirSync(storageDir, { recursive: true })

  const port = await getFreePort()
  const secrets = loadOrCreateSecrets(userData)
  const variant = buildVariant()
  const isGpu = variant === 'gpu'

  const env = {
    ...process.env,
    MATERIA_HOST: '127.0.0.1',
    MATERIA_PORT: String(port),
    ENV: 'development',            // skips the production strong-secret gate
    ENABLE_HEAVY_TOOLS: 'true',    // desktop runs the 6 heavy simulations locally
    MATERIA_VARIANT: variant,      // surfaced by /api/system so the UI badge can explain CPU vs GPU
    // CPU build: pin cpu and hide any GPU so a stray CUDA torch can't nvrtc-JIT-crash.
    // GPU build (C4): leave MATERIA_DEVICE unset so the backend auto-detects cuda>mps>cpu
    //   — a GPU build on a machine with no usable GPU therefore degrades to CPU, not breaks.
    ...(isGpu ? {} : { MATERIA_DEVICE: 'cpu', CUDA_VISIBLE_DEVICES: '' }),
    JOB_BACKEND: 'inline',         // no Celery/Redis; jobs run in a daemon thread
    DATABASE_URL: '',              // force the SQLite fallback
    DB_PATH: path.join(userData, 'materia.db'),
    PRE_TRAINED_MODELS_DIR: modelsDir,
    STORAGE_ROOT: storageDir,      // honoured once file_service reads it (C2)
    PYDANTIC_DISABLE_PLUGINS: '1',
    JWT_SECRET_KEY: secrets.JWT_SECRET_KEY,
    FIELD_ENCRYPTION_KEY: secrets.FIELD_ENCRYPTION_KEY,
    SIGNUP_MODE: 'open',           // single local user; UI auto-provisions one account
    ALLOWED_ORIGINS: '*'           // dev mode; the only caller is the local renderer
  }

  child = spawn(exe, [], { cwd: userData, env, stdio: ['ignore', 'pipe', 'pipe'] })
  child.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  child.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  child.on('exit', (code, sig) => console.log(`[backend] exited code=${code} sig=${sig}`))

  await waitForHealth(port)
  return { port }
}

// Kill the backend child (called on app quit).
function stopBackend () {
  if (child && !child.killed) {
    child.kill()
    child = null
  }
}

module.exports = { startBackend, stopBackend }
