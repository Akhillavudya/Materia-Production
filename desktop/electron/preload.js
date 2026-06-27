// Runs before the SPA loads, in an isolated context. Its only job is to hand the
// renderer the absolute backend base URL (the backend listens on a dynamic local
// port chosen at launch), which the SPA's api/client.js reads as window.__MATERIA_API__.
//
// The port arrives via an additionalArguments entry ("--materia-port=NNNNN") set by
// the main process when it creates the BrowserWindow.

const { contextBridge } = require('electron')

const portArg = process.argv.find((a) => a.startsWith('--materia-port='))
const port = portArg ? portArg.split('=')[1] : ''
const apiBase = port ? `http://127.0.0.1:${port}/api` : ''

contextBridge.exposeInMainWorld('__MATERIA_API__', apiBase)
