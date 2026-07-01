const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const fs = require('fs')

const IS_DEV = process.env.NODE_ENV === 'development' || !app.isPackaged

let mainWindow = null
let backendProcess = null

function appRoot() {
  const packagedBackend = path.join(process.resourcesPath, 'backend')
  if (fs.existsSync(packagedBackend)) return process.resourcesPath
  return path.join(__dirname, '..')
}

function rendererEntry() {
  const packagedRenderer = path.join(process.resourcesPath, 'app', 'renderer', 'dist', 'index.html')
  if (fs.existsSync(packagedRenderer)) return packagedRenderer
  return path.join(__dirname, '..', 'renderer', 'dist', 'index.html')
}

// ---------------------------------------------------------------------------
// Python backend
// ---------------------------------------------------------------------------

function findPython() {
  const venv = path.join(appRoot(), 'backend', '.venv', 'bin', 'python')
  if (fs.existsSync(venv)) return venv
  // Fallback: system Python
  return 'python3'
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const python = findPython()
    const cwd = appRoot()
    const script = path.join(cwd, 'backend', 'main.py')

    backendProcess = spawn(python, [script], {
      cwd,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONPATH: cwd },
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
    minWidth: 800,
    minHeight: 600,
    title: 'TransCom',
    backgroundColor: '#1a1a2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (IS_DEV && !fs.existsSync(rendererEntry())) {
    const port = process.env.TRANSCOM_RENDERER_PORT || '5747'
    mainWindow.loadURL(`http://localhost:${port}`)
    mainWindow.webContents.openDevTools()
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
