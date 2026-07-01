import store from '../store.js'
import ws from '../ws.js'
import { highlightSearch } from './TranscriptPane.js'

let searchTimer = null

export function init() {
  const toolbar = document.getElementById('toolbar')
  toolbar.innerHTML = `
    <div class="live-title">
      <strong>Live Transcript</strong>
      <span id="toolbar-session">No session</span>
    </div>
    <input id="search-input" type="search" placeholder="Search transcript" />
    <button class="btn" id="btn-stop-all">Stop All</button>
    <div class="export-menu">
      <button class="btn">Export</button>
      <div class="export-dropdown">
        <button id="export-txt">TXT</button>
        <button id="export-csv">CSV</button>
      </div>
    </div>
    <button class="btn danger" id="btn-clear">Clear</button>
  `

  document.getElementById('search-input').addEventListener('input', e => {
    clearTimeout(searchTimer)
    const q = e.target.value
    searchTimer = setTimeout(() => {
      store.set('searchQuery', q)
      highlightSearch(q)
    }, 200)
  })

  document.getElementById('btn-stop-all').addEventListener('click', () => ws.send('stop_all', {}))
  document.getElementById('export-txt').addEventListener('click', () => doExport('txt'))
  document.getElementById('export-csv').addEventListener('click', () => doExport('csv'))
  document.getElementById('btn-clear').addEventListener('click', () => {
    if (confirm('Clear this session transcript?')) ws.send('clear_transcript', {})
  })

  store.subscribe('session', session => {
    const el = document.getElementById('toolbar-session')
    if (el) el.textContent = session?.name || 'No session'
  })
  store.subscribe('status', status => {
    const modelEl = document.getElementById('status-model')
    const backend = status?.backend || 'whisper'
    const model = shortModelName(status?.model || 'base')
    const device = status?.device || 'cpu'
    if (modelEl) modelEl.textContent = `${backend} ${model} · ${device}`
  })
  store.subscribe('engineStatus', status => {
    const el = document.getElementById('status-engine')
    if (el) el.textContent = status?.message || ''
  })

  const start = Date.now()
  setInterval(() => {
    const elapsed = Math.floor((Date.now() - start) / 1000)
    const m = String(Math.floor(elapsed / 60)).padStart(2, '0')
    const s = String(elapsed % 60).padStart(2, '0')
    const el = document.getElementById('status-timer')
    if (el) el.textContent = `${m}:${s}`
  }, 1000)
}

function shortModelName(model) {
  return String(model).split('/').pop()
}

async function doExport(fmt) {
  let path = `transcom_export.${fmt}`
  if (window.electronAPI?.showSaveDialog) {
    const result = await window.electronAPI.showSaveDialog({
      defaultPath: path,
      filters: fmt === 'csv'
        ? [{ name: 'CSV', extensions: ['csv'] }]
        : [{ name: 'Text', extensions: ['txt'] }],
    })
    if (result.canceled || !result.filePath) return
    path = result.filePath
  }
  ws.send('export_transcript', { format: fmt, path })
}
