import store from '../store.js'
import ws from '../ws.js'
import { token } from '../auth.js'
import { editionState } from '../edition.mjs'

const CHANNEL_COLOR = '#2f6f9e'
let fileMonitor = null
let fileMonitorStartRequested = false

export function init() {
  const panel = document.getElementById('setup-panel')
  panel.innerHTML = `
    <div class="alpine-landscape" aria-hidden="true">
      <i class="alpine-ridge alpine-ridge-1"></i>
      <i class="alpine-ridge alpine-ridge-2"></i>
      <i class="alpine-ridge alpine-ridge-3"></i>
      <i class="alpine-ridge alpine-ridge-4"></i>
      <i class="alpine-ridge alpine-ridge-5"></i>
    </div>
    <div class="panel-title">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true"></span>
        <div class="brand-copy">
          <strong>TransCom</strong>
          <div class="brand-tagline">
            <span>Live-Transkription</span>
            <em>Offline</em>
          </div>
        </div>
      </div>
    </div>
    <nav class="panel-actions" id="sidebar-actions" aria-label="Transkript-Aktionen"></nav>

    <section class="panel-section project-section" id="session-card"></section>
    <section class="panel-section audio-section" id="audio-card"></section>
    <section class="panel-section technical-section" id="model-card"></section>
  `

  store.subscribe('session', renderSession)
  store.subscribe('devices', renderAudio)
  store.subscribe('channels', renderAudio)
  store.subscribe('audioSource', renderAudio)
  store.subscribe('audioSourceMode', renderAudio)
  store.subscribe('status', renderModels)
}

function renderSession(session) {
  const el = document.getElementById('session-card')
  if (!el) return
  const isLive = session?.status === 'live'
  el.innerHTML = `
    <div class="section-head">
      <span>Transkript</span>
      <span class="pill ${isLive ? 'ok' : ''}">${isLive ? 'läuft' : 'bereit'}</span>
    </div>
    <label class="field-label" for="session-name">Name</label>
    <input class="form-input project-name" id="session-name" aria-label="Name des Transkripts" placeholder="z. B. Probe 14. Juli" value="${esc(session?.name || '')}" ${isLive ? 'disabled' : ''} />
    <details class="inline-details" ${session?.root_dir ? '' : ''}>
      <summary>Speicherort</summary>
      <input class="form-input" id="session-root" aria-label="Speicherordner" placeholder="Standardordner verwenden" value="${esc(session?.root_dir || '')}" ${isLive ? 'disabled' : ''} />
      ${session?.session_dir ? `<div class="small-path">${esc(session.session_dir)}</div>` : '<div class="hint">Ohne Auswahl verwendet TransCom den Standardordner.</div>'}
    </details>
  `
}

export function stopForSessionChange(session = store.get('session')) {
  const isCapturing = (store.get('channels') || []).some(channel => channel.is_active)
  stopFileMonitor()
  if (isCapturing) ws.send('stop_all', {})
  if (session?.status === 'live') ws.send('session_stop', {})
}

function renderAudio() {
  const el = document.getElementById('audio-card')
  if (!el) return
  const devices = store.get('devices') || []
  const channels = store.get('channels') || []
  const audioSource = store.get('audioSource') || { mode: 'live', path: null }
  const sourceMode = store.get('audioSourceMode') || (audioSource.mode === 'file' ? 'file' : 'live')
  const feed = channels[0]
  const isActive = channels.some(channel => channel.is_active)
  const selectedDevice = feed?.device_index ?? devices.find(device => device.is_default)?.index ?? devices[0]?.index ?? 0
  const sourcePath = audioSource.path || ''
  const demoPath = audioSource.demo_path || ''
  const isDemo = sourceMode === 'file' && Boolean(sourcePath) && sourcePath === demoPath
  const isOwnFile = sourceMode === 'file' && Boolean(sourcePath) && !isDemo
  const sourceLabel = sourcePath ? sourcePath.split('/').pop() : ''
  const selectedDeviceName = devices.find(device => device.index === selectedDevice)?.name || 'Audioeingang'
  const startDisabled = sourceMode === 'file' && !sourcePath
  const edition = editionState(store.get('status'))

  el.innerHTML = `
    <div class="section-head">
      <span>Was soll transkribiert werden?</span>
    </div>
    <div class="source-switch source-switch-three" role="group" aria-label="Audioquelle auswählen">
      <button class="source-option ${sourceMode === 'live' ? 'selected' : ''}" id="source-live" type="button" ${isActive ? 'disabled' : ''}>
        <span class="source-icon live-icon" aria-hidden="true"></span>
        <strong>Live</strong>
        <span>Eingang hören</span>
      </button>
      <button class="source-option ${isDemo ? 'selected' : ''}" id="source-demo" type="button" ${isActive || !demoPath ? 'disabled' : ''}>
        <span class="source-icon demo-icon" aria-hidden="true"></span>
        <strong>Demo</strong>
        <span>Testaufnahme</span>
      </button>
      <button class="source-option ${isOwnFile ? 'selected' : ''}" id="source-file" type="button" ${isActive ? 'disabled' : ''}>
        <span class="source-icon file-icon" aria-hidden="true"></span>
        <strong>Datei</strong>
        <span>Eigene Aufnahme</span>
      </button>
    </div>

    ${sourceMode === 'live' ? `
      <div class="source-detail">
        <label class="field-label" for="feed-device">Audioeingang</label>
        <select class="form-select" id="feed-device" ${isActive ? 'disabled' : ''}>
          ${devices.length ? devices.map(device => `<option value="${device.index}" ${device.index === selectedDevice ? 'selected' : ''}>${esc(device.name)}${device.is_default ? ' (Standard)' : ''}</option>`).join('') : '<option>Kein Eingang gefunden</option>'}
        </select>
        <button class="subtle-action" id="btn-devices" type="button" ${isActive ? 'disabled' : ''}>Eingänge neu laden</button>
      </div>
    ` : `
      <div class="source-detail file-summary">
        <span class="file-kicker">${isDemo ? 'TransCom-Testaufnahme' : 'Ausgewählte Datei'}</span>
        <strong class="file-path" title="${esc(sourcePath)}">${esc(sourceLabel || 'Noch keine Datei gewählt')}</strong>
        <span>${isDemo ? 'Startet zusammen mit der Transkription und zeigt den vollständigen Ablauf.' : 'Die Wiedergabe startet zusammen mit der Transkription.'}</span>
      </div>
    `}

    <div class="go-area ${isActive ? 'active' : ''}">
      <button class="go-button ${isActive ? 'stop' : ''}" id="btn-transcription-toggle" type="button" ${startDisabled ? 'disabled' : ''}>
        <span class="go-symbol" aria-hidden="true"></span>
        <span>${isActive ? 'Transkription beenden' : 'Transkription starten'}</span>
      </button>
      <p>${isActive ? 'Audio wird gerade erkannt und live mitgeschrieben.' : sourceMode === 'live' ? `Bereit · ${esc(selectedDeviceName)}` : sourcePath ? 'Bereit · Wiedergabe und Transkript starten gemeinsam' : 'Bitte zuerst eine Audiodatei auswählen'}</p>
    </div>
    <div class="edition-note ${edition.edition}">
      <strong>TransCom ${edition.label}</strong>
      <span>${edition.edition === 'starter'
        ? `Neue Transkriptionen enden automatisch nach exakt ${edition.sessionLimitSeconds} Sekunden. Gespeicherte Transkripte bleiben lesbar und bearbeitbar; Export ist gesperrt.`
        : 'Unbegrenzte Transkriptionsdauer · TXT- und CSV-Export enthalten.'}</span>
    </div>
  `

  if (!isActive && !fileMonitorStartRequested) stopFileMonitor()

  el.querySelector('#source-live')?.addEventListener('click', () => {
    if (isActive) return
    store.set('audioSourceMode', 'live')
    updateAudioSource({ mode: 'live', path: null })
  })
  el.querySelector('#source-demo')?.addEventListener('click', () => {
    if (isActive || !demoPath) return
    store.set('audioSourceMode', 'file')
    updateAudioSource({ mode: 'file', path: demoPath })
  })
  el.querySelector('#source-file')?.addEventListener('click', () => {
    if (!isActive) chooseAudioFile()
  })
  el.querySelector('#btn-devices')?.addEventListener('click', () => ws.send('list_devices', {}))
  el.querySelector('#btn-transcription-toggle').addEventListener('click', () => {
    if (isActive) {
      stopTranscription()
      return
    }
    startTranscription({ feed, sourceMode, sourcePath, selectedDevice })
  })
}

function startTranscription({ feed, sourceMode, sourcePath, selectedDevice }) {
  if (sourceMode === 'file') {
    if (!sourcePath) return
    updateAudioSource({ mode: 'file', path: sourcePath })
    startFileMonitor(sourcePath)
  }

  const session = store.get('session')
  const requestedSession = sessionPayload()
  const needsNewSession = !session
    || (requestedSession.name.trim() && requestedSession.name.trim() !== session.name)
    || (requestedSession.root_dir.trim() && requestedSession.root_dir.trim() !== session.root_dir)
  if (needsNewSession) ws.send('session_create', requestedSession)
  if (needsNewSession || session?.status !== 'live') ws.send('session_start', {})

  if (feed) {
    ws.send('update_channel', {
      id: feed.id,
      name: feed.name || 'Intercom Mix',
      device_index: Number(document.getElementById('feed-device')?.value ?? feed.device_index ?? selectedDevice ?? 0),
      color: feed.color || CHANNEL_COLOR,
      label: 'MIX',
    })
    ws.send('start_capture', { id: feed.id })
    return
  }

  ws.send('add_channel', {
    name: 'Intercom Mix',
    device_index: Number(document.getElementById('feed-device')?.value ?? selectedDevice ?? 0),
    color: CHANNEL_COLOR,
    label: 'MIX',
    start: true,
  })
}

function stopTranscription() {
  stopFileMonitor()
  ws.send('stop_all', {})
  if (store.get('session')?.status === 'live') ws.send('session_stop', {})
}

function sessionPayload() {
  return {
    name: document.getElementById('session-name')?.value || '',
    root_dir: document.getElementById('session-root')?.value || '',
  }
}

async function chooseAudioFile() {
  let path = ''
  if (window.electronAPI?.showOpenDialog) {
    const result = await window.electronAPI.showOpenDialog({
      title: 'Audioaufnahme auswählen',
      properties: ['openFile'],
      filters: [
        { name: 'Audiodateien', extensions: ['wav', 'wave', 'aiff', 'aif', 'mp3', 'm4a'] },
        { name: 'Alle Dateien', extensions: ['*'] },
      ],
    })
    if (result.canceled || !result.filePaths?.length) return
    path = result.filePaths[0]
  } else {
    path = window.prompt('Pfad zur Audiodatei') || ''
  }
  if (!path.trim()) return
  store.set('audioSourceMode', 'file')
  updateAudioSource({ mode: 'file', path: path.trim() })
}

function updateAudioSource(nextSource) {
  const current = store.get('audioSource') || { mode: 'live', path: null, demo_path: null }
  const merged = { ...current, ...nextSource }
  store.set('audioSource', merged)
  if (merged.mode === 'file') {
    ws.send('set_audio_source', { mode: 'file', path: merged.path })
    return
  }
  stopFileMonitor()
  ws.send('set_audio_source', { mode: 'live' })
}

function startFileMonitor(path) {
  fileMonitorStartRequested = true
  fileMonitor = new Audio(audioFileUrl(path))
  fileMonitor.volume = 1
  fileMonitor.play().catch(error => {
    console.warn('[audio monitor] playback failed', error)
  })
}

function stopFileMonitor() {
  fileMonitorStartRequested = false
  if (!fileMonitor) return
  fileMonitor.pause()
  try {
    fileMonitor.currentTime = 0
  } catch {
    // Metadata may not be ready yet.
  }
  fileMonitor = null
}

function audioFileUrl(path) {
  const params = new URLSearchParams({ path })
  const currentToken = token()
  if (currentToken) params.set('token', currentToken)
  const apiBase = window.electronAPI?.getWebApiBase?.() || ''
  return `${apiBase}/api/audio-file?${params.toString()}`
}

function renderModels(status) {
  const el = document.getElementById('model-card')
  if (!el) return
  const vad = modelStatus(status?.vad, 'wird geladen')
  const speaker = modelStatus(status?.speaker_model, 'wird geladen')
  const lang = status?.language === 'en' ? 'en' : status?.language === 'auto' ? 'auto' : 'de'
  // Edition changes also affect the recording card and its explanatory lock.
  renderAudio()
  el.innerHTML = `
    <details class="utility-details compact-details">
      <summary><span>Sprache & Technik</span><small>optional</small></summary>
      <div class="details-body">
        <label class="model-row"><span>Sprache</span><select class="mini-select" id="language-select">
          <option value="auto" ${lang === 'auto' ? 'selected' : ''}>Deutsch + Englisch</option>
          <option value="de" ${lang === 'de' ? 'selected' : ''}>Deutsch</option>
          <option value="en" ${lang === 'en' ? 'selected' : ''}>Englisch</option>
        </select></label>
        <div class="model-row"><span>Modell</span><strong>${esc(status?.model || 'base')}</strong></div>
        <div class="model-row"><span>Spracherkennung</span><strong>${esc(vad)}</strong></div>
        <div class="model-row"><span>Stimmenmodell</span><strong>${esc(speaker)}</strong></div>
      </div>
    </details>
  `
  el.querySelector('#language-select').addEventListener('change', event => {
    ws.send('set_language', { language: event.target.value })
  })
}

function modelStatus(value, fallback) {
  if (!value) return fallback
  if (typeof value === 'string') return value
  const engine = value.engine || fallback
  return value.ready ? engine : `${engine} (Ersatzmodus)`
}

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
