// Materia desktop — Electron main process.
// Lifecycle: start the bundled backend → open a window pointed at the local SPA →
// tear the backend down on quit.

const { app, BrowserWindow } = require('electron')
const path = require('path')
const { startBackend, stopBackend } = require('./backend')

let mainWindow = null

function createWindow (port) {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // Hand the renderer the backend port so preload can build the API base URL.
      additionalArguments: [`--materia-port=${port}`]
    }
  })

  // The SPA is built with `--base=./` into resources/spa so file:// asset paths resolve.
  mainWindow.loadFile(path.join(__dirname, '..', 'resources', 'spa', 'index.html'))
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.on('closed', () => { mainWindow = null })
}

app.whenReady().then(async () => {
  try {
    const { port } = await startBackend()
    createWindow(port)
  } catch (err) {
    console.error('[main] failed to start backend:', err)
    app.quit()
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && mainWindow === null) {
      // backend already running; just reopen a window on the last known port is
      // out of scope for the spike — quit-and-relaunch is fine here.
    }
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', stopBackend)
app.on('quit', stopBackend)
