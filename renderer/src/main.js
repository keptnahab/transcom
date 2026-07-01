import ws from './ws.js'
import store from './store.js'
import { clearAuth, currentUser, isAuthFailure, login, me, token, listUsers } from './auth.js'
import { init as initChannelPanel } from './components/ChannelPanel.js'
import { init as initSpeakerPanel } from './components/SpeakerPanel.js'
import { init as initTranscriptPane, appendSegment, renderAll } from './components/TranscriptPane.js'
import { init as initToolbar } from './components/Toolbar.js'

// ------------------------------------------------------------------
// Bootstrap
// ------------------------------------------------------------------
initChannelPanel()
initSpeakerPanel()
initTranscriptPane()
initToolbar()

const overlay = document.getElementById('connection-overlay')
const authOverlay = document.getElementById('auth-overlay')
const loginForm = document.getElementById('login-form')
const loginError = document.getElementById('login-error')

// ------------------------------------------------------------------
// Connection state
// ------------------------------------------------------------------
ws.onConnect(() => {
  store.set('connected', true)
  overlay.classList.add('hidden')
})

ws.onDisconnect(() => {
  store.set('connected', false)
  overlay.classList.remove('hidden')
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
ws.on('init_state', ({ devices, channels, segments, session, speakers, share, audio_source, status }) => {
  store.set('devices', devices || [])
  store.set('channels', channels || [])
  store.setSegments(segments || [])
  store.set('session', session || null)
  store.set('speakers', speakers || [])
  store.set('share', share || { enabled: false, url: null })
  store.set('audioSource', audio_source || status?.audio_source || { mode: 'live', path: null })
  store.set('status', status || {})
  if (segments?.length) renderAll(segments)
})

ws.on('device_list', ({ devices }) => {
  store.set('devices', devices || [])
})

ws.on('audio_source_state', (source) => {
  store.set('audioSource', source || { mode: 'live', path: null })
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
  document.getElementById('transcript-pane').innerHTML = ''
})

ws.on('segment_updated', ({ segment }) => {
  store.upsertSegment(segment)
  renderAll(store.get('segments') || [])
})

ws.on('session_state', ({ session }) => {
  store.set('session', session || null)
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
  if (status?.audio_source) store.set('audioSource', status.audio_source)
})

ws.on('engine_status', (status) => {
  store.set('engineStatus', status || {})
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
  const existing = token()
  if (!existing) {
    authOverlay.classList.remove('hidden')
    overlay.classList.add('hidden')
    return
  }
  try {
    await finishAuth(await me())
  } catch {
    resetAuth()
  }
}

async function finishAuth(user) {
  store.set('authUser', user || currentUser())
  authOverlay.classList.add('hidden')
  overlay.classList.remove('hidden')
  ws.connect(token())
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
