import ws from './ws.js'
import store from './store.js'
import { clearAuth, currentUser, isAuthFailure, login, me, token, listUsers } from './auth.js'
import { init as initChannelPanel } from './components/ChannelPanel.js'
import { init as initSpeakerPanel } from './components/SpeakerPanel.js'
import { init as initTranscriptPane, appendSegment, renderAll } from './components/TranscriptPane.js'
import { init as initTranscriptLibrary } from './components/TranscriptLibrary.js'
import { init as initToolbar } from './components/Toolbar.js'
import { editionLimitMessage } from './edition.mjs'

// ------------------------------------------------------------------
// Bootstrap
// ------------------------------------------------------------------
initChannelPanel()
initSpeakerPanel()
initTranscriptPane()
initTranscriptLibrary()
initToolbar()

const overlay = document.getElementById('connection-overlay')
const authOverlay = document.getElementById('auth-overlay')
const loginForm = document.getElementById('login-form')
const loginError = document.getElementById('login-error')
let connectionTimer = null

// ------------------------------------------------------------------
// Connection state
// ------------------------------------------------------------------
ws.onConnect(() => {
  store.set('connected', true)
  if (connectionTimer) {
    clearTimeout(connectionTimer)
    connectionTimer = null
  }
  overlay.classList.add('hidden')
})

ws.onDisconnect(() => {
  store.set('connected', false)
  overlay.classList.remove('hidden')
  if (connectionTimer) clearTimeout(connectionTimer)
  connectionTimer = setTimeout(() => {
    if (!store.get('connected')) {
      overlay.querySelector('p').textContent = 'Audio-Engine nicht erreichbar. Bitte Backend und WebSocket prüfen.'
    }
  }, 8000)
})

loginForm.addEventListener('submit', async event => {
  event.preventDefault()
  loginError.textContent = ''
  try {
    const user = await login(
      document.getElementById('login-email').value,
      document.getElementById('login-password').value,
    )
    await finishAuth(user)
  } catch (err) {
    loginError.textContent = err.message || 'Login failed'
  }
})

bootstrapAuth()

// ------------------------------------------------------------------
// Message handlers
// ------------------------------------------------------------------
ws.on('init_state', ({ devices, channels, segments, session, sessions, speakers, share, audio_source, status }) => {
  const source = audio_source || status?.audio_source || { mode: 'live', path: null }
  store.set('devices', devices || [])
  store.set('channels', channels || [])
  store.setSegments(segments || [])
  store.set('session', session || null)
  store.set('sessions', sessions || [])
  store.set('speakers', speakers || [])
  store.set('share', share || { enabled: false, url: null })
  store.set('audioSource', source)
  store.set('audioSourceMode', source.mode === 'file' ? 'file' : 'live')
  store.set('status', status || {})
  if (segments?.length) renderAll(segments)
})

ws.on('device_list', ({ devices }) => {
  store.set('devices', devices || [])
})

ws.on('audio_source_state', (source) => {
  const nextSource = source || { mode: 'live', path: null }
  store.set('audioSource', nextSource)
  store.set('audioSourceMode', nextSource.mode === 'file' ? 'file' : 'live')
})

ws.on('channel_added', ({ channel }) => {
  store.upsertChannel(channel)
})

ws.on('channel_updated', ({ channel }) => {
  store.upsertChannel(channel)
})

ws.on('channels_updated', ({ channels }) => {
  store.set('channels', channels || [])
})

ws.on('channel_removed', ({ id }) => {
  store.removeChannel(id)
})

ws.on('transcript_segment', (seg) => {
  store.addSegment(seg)
  appendSegment(seg)
})

ws.on('transcript_cleared', () => {
  store.setSegments([])
  renderAll([])
})

ws.on('transcript_loaded', ({ segments }) => {
  store.setSegments(segments || [])
  renderAll(segments || [])
})

ws.on('segment_updated', ({ segment }) => {
  store.upsertSegment(segment)
  renderAll(store.get('segments') || [])
})

ws.on('session_state', ({ session }) => {
  store.set('session', session || null)
})

ws.on('session_list', ({ sessions }) => {
  store.set('sessions', sessions || [])
})

ws.on('speaker_update', ({ speakers }) => {
  store.set('speakers', speakers || [])
  renderAll(store.get('segments') || [])
})

ws.on('enrollment_result', ({ message }) => {
  store.set('engineStatus', { state: 'enrollment', message })
})

ws.on('share_state', (share) => {
  store.set('share', share || { enabled: false, url: null })
})

ws.on('backend_status', (status) => {
  store.set('status', status || {})
  if (status?.audio_source) {
    store.set('audioSource', status.audio_source)
    store.set('audioSourceMode', status.audio_source.mode === 'file' ? 'file' : 'live')
  }
})

ws.on('engine_status', (status) => {
  store.set('engineStatus', status || {})
})

ws.on('edition_limit_reached', (payload) => {
  const message = editionLimitMessage(payload)
  store.set('engineStatus', { state: 'edition_limit_reached', message })
  window.alert(message)
})

ws.on('error', ({ message }) => {
  console.error('[backend error]', message)
  store.set('engineStatus', { state: 'error', message })
})

ws.on('auth_required', ({ message }) => {
  resetAuth(message || 'Please log in again.')
})

// Backend crash notification from Electron
window.electronAPI?.onBackendError?.((msg) => {
  overlay.classList.remove('hidden')
  overlay.querySelector('p').textContent = `Backend error: ${msg}`
})

window.addEventListener('transcom-auth-invalid', event => {
  resetAuth(event.detail?.message || 'Please log in again.')
})

async function bootstrapAuth() {
  // Reuse an existing session immediately. The audio engine connection can
  // warm up in parallel with the auth refresh instead of waiting for /api/me.
  const existingToken = token()
  if (existingToken) ws.connect(existingToken)
  try {
    await finishAuth(await me())
  } catch {
    if (!token()) {
      authOverlay.classList.remove('hidden')
      overlay.classList.add('hidden')
      return
    }
    resetAuth()
  }
}

async function finishAuth(user) {
  store.set('authUser', user || currentUser())
  authOverlay.classList.add('hidden')
  ws.connect(token())
  // A saved local session may already have opened the socket while /api/me
  // was still being refreshed. Do not put the loading screen back on top of
  // an already connected app.
  overlay.classList.toggle('hidden', ws.connected)
  await refreshUsers()
}

export async function refreshUsers() {
  const user = store.get('authUser')
  if (!user?.is_admin) return
  try {
    store.set('betaUsers', await listUsers())
  } catch (err) {
    if (isAuthFailure(err)) {
      await reconcileAuthFailure(err)
      return
    }
    store.set('betaUsers', [])
  }
}

async function reconcileAuthFailure(err) {
  if (err.status === 401) {
    resetAuth('Session expired. Please log in again.')
    return
  }
  try {
    const user = await me()
    store.set('authUser', user)
    if (!user?.is_admin) {
      store.set('betaUsers', [])
      store.set('generatedPassword', null)
    }
  } catch {
    resetAuth('Session expired. Please log in again.')
  }
}

function resetAuth(message = '') {
  ws.close()
  clearAuth()
  store.set('connected', false)
  store.set('authUser', null)
  store.set('betaUsers', [])
  store.set('generatedPassword', null)
  authOverlay.classList.remove('hidden')
  overlay.classList.add('hidden')
  loginError.textContent = message
}
