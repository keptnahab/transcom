const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const fs = require('fs')

const IS_DEV = process.env.NODE_ENV === 'development' || !app.isPackaged
const LOCAL_WEB_PORT = process.env.TRANSCOM_WEB_PORT || '8081'
const LOCAL_WS_PORT = process.env.TRANSCOM_WS_PORT || '8766'

let mainWindow = null
let backendProcess = null

function releaseEdition() {
  if (!app.isPackaged) return process.env.TRANSCOM_EDITION === 'full' ? 'full' : 'starter'
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(process.resourcesPath, 'edition.json'), 'utf8'))
    return manifest.edition === 'full' ? 'full' : 'starter'
  } catch (error) {
    console.error('Edition manifest missing or invalid; using Beta:', error.message)
    return 'starter'
  }
}

function appRoot() {
  if (app.isPackaged) return process.resourcesPath
  return path.join(__dirname, '..')
}

function rendererEntry() {
  // app.getAppPath() points at Resources/app.asar in a normal packaged build
  // and at the repository root in development. Electron's fs/loadFile support
  // ASAR paths transparently, so this remains valid in both layouts.
  return path.join(app.getAppPath(), 'renderer', 'dist', 'index.html')
}

// ---------------------------------------------------------------------------
// Python backend
// ---------------------------------------------------------------------------

function findPython() {
  if (app.isPackaged) {
    const bundledBackend = path.join(process.resourcesPath, 'backend-runtime', 'transcom-backend')
    if (fs.existsSync(bundledBackend)) return { command: bundledBackend, args: [] }
    throw new Error('Bundled backend runtime is missing')
  }
  const venv = path.join(appRoot(), 'backend', '.venv', 'bin', 'python')
  if (fs.existsSync(venv)) return { command: venv, args: [path.join(appRoot(), 'backend', 'main.py')] }
  // Fallback: system Python
  return { command: 'python3', args: [path.join(appRoot(), 'backend', 'main.py')] }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const backend = findPython()
    const cwd = appRoot()
    const userData = app.getPath('userData')
    const dataRoot = path.join(userData, 'data')
    fs.mkdirSync(path.join(dataRoot, 'sessions'), { recursive: true })

    backendProcess = spawn(backend.command, backend.args, {
      cwd,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: cwd,
        // The desktop app is local-first and should never require issued beta
        // credentials. Set TRANSCOM_AUTH_DISABLED=0 explicitly when the
        // authenticated Electron flow needs to be tested.
        TRANSCOM_AUTH_DISABLED: process.env.TRANSCOM_AUTH_DISABLED || '1',
        TRANSCOM_WEB_PORT: LOCAL_WEB_PORT,
        TRANSCOM_WS_PORT: LOCAL_WS_PORT,
        TRANSCOM_RESOURCE_ROOT: cwd,
        TRANSCOM_SESSION_ROOT: path.join(dataRoot, 'sessions'),
        TRANSCOM_DB: path.join(dataRoot, 'transcom_session.db'),
        TRANSCOM_AUTH_DB: path.join(dataRoot, 'transcom_auth.db'),
        TRANSCOM_MODEL_DIR: path.join(cwd, 'models'),
        HF_HOME: app.isPackaged ? path.join(cwd, 'model-cache') : (process.env.HF_HOME || ''),
        HF_HUB_OFFLINE: app.isPackaged ? '1' : (process.env.HF_HUB_OFFLINE || ''),
        TRANSFORMERS_OFFLINE: app.isPackaged ? '1' : (process.env.TRANSFORMERS_OFFLINE || ''),
        // Packaged builds never trust a caller-provided edition override. The
        // separately produced Beta/Full artifact carries this manifest.
        TRANSCOM_EDITION: releaseEdition(),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    backendProcess.stdout.on('data', (data) => {
      const line = data.toString().trim()
      console.log('[backend]', line)
      if (line.includes('READY')) {
        resolve()
      }
    })

    backendProcess.stderr.on('data', (data) => {
      process.stderr.write('[backend] ' + data.toString())
    })

    backendProcess.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`)
      if (code !== 0 && mainWindow) {
        mainWindow.webContents.send('backend-error', `Backend exited with code ${code}`)
      }
    })

    // Timeout if backend doesn't signal READY
    setTimeout(() => reject(new Error('Backend did not signal READY within 30s')), 30_000)
  })
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill('SIGTERM')
    backendProcess = null
  }
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 980,
    minHeight: 600,
    title: 'TransCom',
    backgroundColor: '#1a1a2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (IS_DEV) {
    const port = process.env.TRANSCOM_RENDERER_PORT || '5747'
    mainWindow.loadURL(`http://localhost:${port}`)
    if (process.env.TRANSCOM_OPEN_DEVTOOLS === '1') mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(rendererEntry())
  }

  mainWindow.on('closed', () => { mainWindow = null })
}

// ---------------------------------------------------------------------------
// IPC — only used for native OS dialogs
// ---------------------------------------------------------------------------

ipcMain.handle('show-save-dialog', async (_event, options) => {
  const result = await dialog.showSaveDialog(mainWindow, options)
  return result
})

ipcMain.handle('show-open-dialog', async (_event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, options)
  return result
})

ipcMain.handle('open-path', async (_event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') return 'Ungültiger Speicherort'
  return shell.openPath(targetPath)
})

ipcMain.handle('trash-paths', async (_event, targetPaths) => {
  const result = { trashed: [], errors: [] }
  const uniquePaths = [...new Set(Array.isArray(targetPaths) ? targetPaths : [])]
  for (const targetPath of uniquePaths) {
    try {
      if (!targetPath || typeof targetPath !== 'string') throw new Error('Ungültiger Speicherort')
      const resolvedPath = path.resolve(targetPath)
      const metadataPath = path.join(resolvedPath, 'session.json')
      if (!fs.existsSync(metadataPath)) throw new Error('Kein TransCom-Transkriptordner')
      const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'))
      if (path.resolve(metadata.session_dir || '') !== resolvedPath) throw new Error('Transkriptordner konnte nicht bestätigt werden')
      await shell.trashItem(resolvedPath)
      result.trashed.push(targetPath)
    } catch (error) {
      result.errors.push({ path: targetPath, message: error.message || String(error) })
    }
  }
  return result
})

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  try {
    await startBackend()
  } catch (err) {
    console.error('Backend startup failed:', err.message)
    // Open window anyway so user sees an error state
  }
  createWindow()
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  stopBackend()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
