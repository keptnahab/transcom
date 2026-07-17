const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  showSaveDialog: (options) => ipcRenderer.invoke('show-save-dialog', options),
  showOpenDialog: (options) => ipcRenderer.invoke('show-open-dialog', options),
  openPath: (path) => ipcRenderer.invoke('open-path', path),
  trashPaths: (paths) => ipcRenderer.invoke('trash-paths', paths),
  onBackendError: (callback) => ipcRenderer.on('backend-error', (_event, msg) => callback(msg)),
  getWebApiBase: () => {
    const host = window.location.hostname || '127.0.0.1'
    const port = process.env.TRANSCOM_WEB_PORT || '8081'
    return `http://${host}:${port}`
  },
  getWebSocketBase: () => {
    const host = window.location.hostname || '127.0.0.1'
    const port = process.env.TRANSCOM_WS_PORT || '8766'
    return `ws://${host}:${port}`
  },
})
