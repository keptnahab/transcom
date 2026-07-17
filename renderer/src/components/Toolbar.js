import store from '../store.js'
import ws from '../ws.js'
import { highlightSearch } from './TranscriptPane.js'
import { editionState } from '../edition.mjs'

let searchTimer = null
let recordingStartedAt = null

export function init() {
  const toolbar = document.getElementById('toolbar')
  toolbar.innerHTML = `
    <div class="live-title">
      <strong>Live-Transkript</strong>
      <span id="toolbar-session">Noch nicht gestartet</span>
    </div>
    <input id="search-input" type="search" placeholder="Transkript durchsuchen" />
  `

  const sidebarActions = document.getElementById('sidebar-actions')
  sidebarActions.innerHTML = `
    <div class="export-menu">
      <button class="btn sidebar-action" id="export-trigger" type="button" disabled>Exportieren · Full</button>
      <div class="export-dropdown">
        <button id="export-txt">Als TXT</button>
        <button id="export-csv">Als CSV</button>
      </div>
    </div>
    <button class="btn sidebar-action" id="btn-options" type="button">Optionen</button>
  `

  document.getElementById('search-input').addEventListener('input', e => {
    clearTimeout(searchTimer)
    const q = e.target.value
    searchTimer = setTimeout(() => {
      store.set('searchQuery', q)
      highlightSearch(q)
    }, 200)
  })

  document.getElementById('export-txt').addEventListener('click', () => doExport('txt'))
  document.getElementById('export-csv').addEventListener('click', () => doExport('csv'))
  document.getElementById('btn-options').addEventListener('click', () => {
    document.getElementById('speaker-panel')?.classList.add('open')
    document.getElementById('utility-scrim')?.classList.add('open')
  })

  store.subscribe('session', session => {
    const el = document.getElementById('toolbar-session')
    if (el) el.textContent = session?.name || 'Noch nicht gestartet'
  })
  store.subscribe('status', status => {
    const modelEl = document.getElementById('status-model')
    const channelsEl = document.getElementById('status-channels')
    const backend = status?.backend || 'whisper'
    const model = shortModelName(status?.model || 'base')
    const device = status?.device || 'cpu'
    if (modelEl) modelEl.textContent = `${backend} ${model} · ${device}`
    if (channelsEl) {
      const active = Number(status?.active_channels || 0)
      channelsEl.textContent = active ? 'Transkription läuft' : 'Bereit'
    }
    renderEditionControls(status)
  })
  store.subscribe('channels', channels => {
    const isActive = (channels || []).some(channel => channel.is_active)
    if (isActive && recordingStartedAt === null) recordingStartedAt = Date.now()
    if (!isActive) recordingStartedAt = null
    const el = document.getElementById('status-channels')
    if (el) el.textContent = isActive ? 'Transkription läuft' : 'Bereit'
  })
  store.subscribe('engineStatus', status => {
    const el = document.getElementById('status-engine')
    if (el) el.textContent = status?.message || ''
  })

  setInterval(() => {
    const elapsed = recordingStartedAt === null ? 0 : Math.floor((Date.now() - recordingStartedAt) / 1000)
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
  if (!editionState(store.get('status')).exportAllowed) {
    window.alert('Export ist in TransCom Starter gesperrt. TransCom Full enthält TXT- und CSV-Export.')
    return
  }
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

function renderEditionControls(status) {
  const edition = editionState(status)
  const trigger = document.getElementById('export-trigger')
  const menu = trigger?.closest('.export-menu')
  if (!trigger || !menu) return
  trigger.disabled = !edition.exportAllowed
  trigger.textContent = edition.exportAllowed ? 'Exportieren' : 'Exportieren · Full'
  trigger.title = edition.exportAllowed
    ? 'Transkript exportieren'
    : 'Export ist ausschließlich in TransCom Full verfügbar.'
  menu.classList.toggle('edition-locked', !edition.exportAllowed)
}
