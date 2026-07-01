import store from '../store.js'
import ws from '../ws.js'

const COLORS = ['#4cc9f0', '#f72585', '#80ed99', '#f9c74f', '#b5179e', '#43aa8b', '#f3722c', '#577590']

export function init() {
  const panel = document.getElementById('setup-panel')
  panel.innerHTML = `
    <div class="panel-title">
      <strong>TransCom</strong>
      <span>v1 local</span>
    </div>

    <section class="panel-section" id="session-card"></section>
    <section class="panel-section" id="audio-card"></section>
    <section class="panel-section" id="model-card"></section>
  `

  store.subscribe('session', renderSession)
  store.subscribe('devices', renderAudio)
  store.subscribe('channels', renderAudio)
  store.subscribe('audioSource', renderAudio)
  store.subscribe('status', renderModels)
}

function renderSession(session) {
  const el = document.getElementById('session-card')
  if (!el) return
  const status = session?.status || 'setup'
  el.innerHTML = `
    <div class="section-head">
      <span>Session</span>
      <span class="pill ${status === 'live' ? 'ok' : ''}">${status}</span>
    </div>
    <input class="form-input" id="session-name" placeholder="Session name" value="${esc(session?.name || '')}" />
    <input class="form-input" id="session-root" placeholder="Storage folder (optional)" value="${esc(session?.root_dir || '')}" />
    <div class="button-row">
      <button class="btn primary" id="btn-session-create">Create</button>
      <button class="btn ${status === 'live' ? 'danger' : 'primary'}" id="btn-session-toggle">${status === 'live' ? 'Stop' : 'Start'}</button>
    </div>
    ${session?.session_dir ? `<div class="small-path">${esc(session.session_dir)}</div>` : ''}
  `
  el.querySelector('#btn-session-create').addEventListener('click', () => {
    ws.send('session_create', {
      name: el.querySelector('#session-name').value,
      root_dir: el.querySelector('#session-root').value,
    })
  })
  el.querySelector('#btn-session-toggle').addEventListener('click', () => {
    ws.send(status === 'live' ? 'session_stop' : 'session_start', {})
  })
}

function renderAudio() {
  const el = document.getElementById('audio-card')
  if (!el) return
  const devices = store.get('devices') || []
  const channels = store.get('channels') || []
  const audioSource = store.get('audioSource') || { mode: 'live', path: null }
  const feed = channels[0]
  const active = channels.filter(ch => ch.is_active).length
  const selectedDevice = feed?.device_index ?? devices.find(d => d.is_default)?.index ?? devices[0]?.index ?? 0
  const sourceMode = audioSource.mode === 'file' ? 'file' : 'live'
  const sourcePath = audioSource.path || ''
  const sourceLabel = sourcePath ? sourcePath.split('/').pop() : 'No audio file selected'

  el.innerHTML = `
    <div class="section-head">
      <span>Audio Feed</span>
      <span class="pill ${active ? 'ok' : ''}">${active ? 'capturing' : 'idle'}</span>
    </div>
    <select class="form-select" id="source-mode">
      <option value="live" ${sourceMode === 'live' ? 'selected' : ''}>Live Input / Loopback</option>
      <option value="file" ${sourceMode === 'file' ? 'selected' : ''}>Audio File (WAV test feed)</option>
    </select>
    ${sourceMode === 'live' ? `
      <select class="form-select" id="feed-device">
        ${devices.length ? devices.map(d => `<option value="${d.index}" ${d.index === selectedDevice ? 'selected' : ''}>${esc(d.name)}${d.is_default ? ' (default)' : ''}</option>`).join('') : '<option>No input devices</option>'}
      </select>
      <div class="hint">For REAPER or a player app, route its output to a virtual input such as BlackHole and select that input here.</div>
    ` : `
      <div class="file-source">
        <div class="file-path" title="${esc(sourcePath)}">${esc(sourceLabel)}</div>
        <div class="button-row">
          <button class="btn" id="btn-choose-file">Choose File</button>
          <button class="btn" id="btn-demo-file">Use Demo WAV</button>
        </div>
      </div>
    `}
    <input class="form-input" id="feed-name" value="${esc(feed?.name || 'Intercom Mix')}" maxlength="32" />
    <div class="button-row">
      <button class="btn" id="btn-devices">Refresh</button>
      <button class="btn ${feed?.is_active ? 'danger' : 'primary'}" id="btn-feed-toggle" ${sourceMode === 'file' && !sourcePath ? 'disabled' : ''}>${feed?.is_active ? 'Stop Feed' : 'Start Feed'}</button>
    </div>
    <div class="channel-list-compact">
      ${channels.map(ch => `
        <div class="compact-channel">
          <span class="swatch" style="background:${esc(ch.color)}"></span>
          <span>${esc(ch.name)}</span>
          <button class="tiny" data-remove="${ch.id}">Remove</button>
        </div>
      `).join('') || '<div class="empty-note">One mixed local input for v1.</div>'}
    </div>
  `

  el.querySelector('#btn-devices').addEventListener('click', () => ws.send('list_devices', {}))
  el.querySelector('#source-mode').addEventListener('change', (event) => {
    const mode = event.target.value
    if (mode === 'file') {
      if (sourcePath) {
        ws.send('set_audio_source', { mode: 'file', path: sourcePath })
      } else {
        chooseAudioFile()
      }
      return
    }
    ws.send('set_audio_source', { mode: 'live' })
  })
  el.querySelector('#btn-choose-file')?.addEventListener('click', chooseAudioFile)
  el.querySelector('#btn-demo-file')?.addEventListener('click', () => {
    if (!audioSource.demo_path) return
    ws.send('set_audio_source', { mode: 'file', path: audioSource.demo_path })
  })
  el.querySelector('#btn-feed-toggle').addEventListener('click', () => {
    if (feed?.is_active) {
      ws.send('stop_capture', { id: feed.id })
      return
    }
    if (feed) {
      ws.send('update_channel', {
        id: feed.id,
        name: el.querySelector('#feed-name').value,
        device_index: Number(el.querySelector('#feed-device')?.value || feed.device_index || 0),
        color: feed.color,
        label: 'MIX',
      })
      ws.send('start_capture', { id: feed.id })
      return
    }
    ws.send('add_channel', {
      name: el.querySelector('#feed-name').value || 'Intercom Mix',
      device_index: Number(el.querySelector('#feed-device')?.value || 0),
      color: COLORS[0],
      label: 'MIX',
      start: true,
    })
  })
  el.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => ws.send('remove_channel', { id: btn.dataset.remove }))
  })
}

async function chooseAudioFile() {
  let path = ''
  if (window.electronAPI?.showOpenDialog) {
    const result = await window.electronAPI.showOpenDialog({
      title: 'Choose intercom audio file',
      properties: ['openFile'],
      filters: [
        { name: 'Audio Files', extensions: ['wav', 'wave', 'aiff', 'aif', 'mp3', 'm4a'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    })
    if (result.canceled || !result.filePaths?.length) return
    path = result.filePaths[0]
  } else {
    path = window.prompt('Path to WAV/audio file') || ''
  }
  if (!path.trim()) return
  ws.send('set_audio_source', { mode: 'file', path: path.trim() })
}

function renderModels(status) {
  const el = document.getElementById('model-card')
  if (!el) return
  const vad = modelStatus(status?.vad, 'pending')
  const speaker = modelStatus(status?.speaker_model, 'pending')
  const lang = status?.language === 'en' ? 'en' : status?.language === 'auto' ? 'auto' : 'de'
  el.innerHTML = `
    <div class="section-head">
      <span>Offline Models</span>
      <span class="pill">${esc(status?.backend || status?.device || 'cpu')}</span>
    </div>
    <div class="model-row"><span>Whisper</span><strong>${esc(status?.model || 'base')}</strong></div>
    <div class="model-row"><span>Latency</span><strong>${esc(formatLatency(status))}</strong></div>
    <label class="model-row"><span>Language</span><select class="mini-select" id="language-select">
      <option value="auto" ${lang === 'auto' ? 'selected' : ''}>Deutsch + English</option>
      <option value="de" ${lang === 'de' ? 'selected' : ''}>Deutsch</option>
      <option value="en" ${lang === 'en' ? 'selected' : ''}>English</option>
    </select></label>
    <div class="model-row"><span>VAD</span><strong>${esc(vad)}</strong></div>
    <div class="model-row"><span>Speaker ID</span><strong>${esc(speaker)}</strong></div>
    <div class="hint">Speaker labels require a live audio check-in. Unsupported language detection is disabled; use German by default or set English in backend config.</div>
  `
  el.querySelector('#language-select').addEventListener('change', event => {
    ws.send('set_language', { language: event.target.value })
  })
}

function modelStatus(value, fallback) {
  if (!value) return fallback
  if (typeof value === 'string') return value
  const engine = value.engine || fallback
  return value.ready ? engine : `${engine} fallback`
}

function formatLatency(status) {
  const chunk = Number(status?.chunk_seconds || 0)
  const overlap = Number(status?.overlap_seconds || 0)
  if (!chunk) return 'pending'
  return `${chunk.toFixed(2)}s / ${(chunk + overlap).toFixed(2)}s`
}

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
