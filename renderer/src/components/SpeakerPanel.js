import store from '../store.js'
import ws from '../ws.js'
import { createUser, deleteUser, isAuthFailure, listUsers, me, setUserPassword } from '../auth.js'

const COLORS = ['#4cc9f0', '#f72585', '#80ed99', '#f9c74f', '#b5179e', '#43aa8b', '#f3722c', '#577590']
const CHECK_IN_SECONDS = 10

let activeCheckIn = null

export function init() {
  const panel = document.getElementById('speaker-panel')
  panel.innerHTML = `
    <section class="panel-section" id="speaker-card"></section>
    <section class="panel-section" id="users-card"></section>
    <section class="panel-section" id="share-card"></section>
  `
  store.subscribe('speakers', renderSpeakers)
  store.subscribe('authUser', renderUsers)
  store.subscribe('betaUsers', renderUsers)
  store.subscribe('generatedPassword', renderUsers)
  store.subscribe('share', renderShare)
}

function renderSpeakers(speakers) {
  const el = document.getElementById('speaker-card')
  if (!el) return
  el.innerHTML = `
    <div class="section-head">
      <span>Speaker Check-in</span>
      <span class="pill">${speakers.length}/8</span>
    </div>
    <div class="speaker-add">
      <input class="form-input" id="speaker-name" placeholder="Name" maxlength="32" />
      <button class="btn primary" id="btn-speaker-add">Add</button>
    </div>
    <div class="speaker-list">
      ${speakers.map((sp, idx) => speakerRow(sp, idx)).join('') || '<div class="empty-note">Add up to 8 people before going live.</div>'}
    </div>
  `
  el.querySelector('#btn-speaker-add').addEventListener('click', () => {
    const input = el.querySelector('#speaker-name')
    ws.send('speaker_create', { name: input.value, color: COLORS[speakers.length % COLORS.length] })
    input.value = ''
  })
  el.querySelectorAll('[data-enroll]').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.speaker-item')
      const speaker = speakers.find(sp => sp.id === btn.dataset.enroll)
      const duration = Number(item.querySelector('[data-duration]').value || CHECK_IN_SECONDS)
      startCheckInDialog({ speaker, duration })
    })
  })
  el.querySelectorAll('[data-speaker-delete]').forEach(btn => {
    btn.addEventListener('click', () => ws.send('speaker_delete', { id: btn.dataset.speakerDelete }))
  })
}

function speakerRow(sp) {
  const quality = Math.round((sp.quality || 0) * 100)
  return `
    <div class="speaker-item">
      <div class="speaker-main">
        <span class="swatch" style="background:${esc(sp.color)}"></span>
        <div>
          <strong>${esc(sp.name)}</strong>
        <span>${sp.usable ? 'audio profile ready' : 'needs live check-in'}</span>
        </div>
        <button class="tiny danger-text" data-speaker-delete="${sp.id}">Delete</button>
      </div>
      <div class="quality"><span style="width:${quality}%"></span></div>
      <div class="enroll-controls">
        <label>sec <input data-duration type="number" min="3" max="20" value="${Math.max(3, Math.round(sp.duration_seconds || CHECK_IN_SECONDS))}" /></label>
        <button class="btn" data-enroll="${sp.id}">Check-in</button>
      </div>
    </div>
  `
}

function renderShare(share) {
  const el = document.getElementById('share-card')
  if (!el) return
  el.innerHTML = `
    <div class="section-head">
      <span>LAN Viewer</span>
      <span class="pill ${share?.enabled ? 'ok' : ''}">${share?.enabled ? 'on' : 'off'}</span>
    </div>
    <div class="share-url">${share?.url ? esc(share.url) : 'No viewer link yet'}</div>
    <div class="button-row">
      <button class="btn ${share?.enabled ? 'danger' : 'primary'}" id="btn-share-toggle">${share?.enabled ? 'Stop Share' : 'Start Share'}</button>
      <button class="btn" id="btn-copy-share" ${share?.url ? '' : 'disabled'}>Copy</button>
    </div>
    <div class="hint">Read-only live transcript with a random token. No export or correction controls.</div>
  `
  el.querySelector('#btn-share-toggle').addEventListener('click', () => ws.send(share?.enabled ? 'share_stop' : 'share_start', {}))
  el.querySelector('#btn-copy-share').addEventListener('click', async () => {
    if (share?.url) await navigator.clipboard.writeText(share.url)
  })
}

function renderUsers() {
  const el = document.getElementById('users-card')
  if (!el) return
  const user = store.get('authUser')
  if (!user?.is_admin) {
    el.innerHTML = ''
    return
  }
  const users = store.get('betaUsers') || []
  const generated = store.get('generatedPassword')
  el.innerHTML = `
    <div class="section-head">
      <span>Beta Users</span>
      <span class="pill">${users.length}</span>
    </div>
    <div class="speaker-add">
      <input class="form-input" id="beta-user-email" placeholder="email@example.com" type="email" />
      <button class="btn primary" id="btn-beta-user-add">Add</button>
    </div>
    ${generated ? `<div class="generated-password"><span>${esc(generated.email)}</span><strong>${esc(generated.password)}</strong></div>` : ''}
    <div class="user-list">
      ${users.map(u => `
        <div class="user-row">
          <div class="user-identity">
            <span>${esc(u.email)}${u.is_admin ? ' · admin' : ''}</span>
            <button class="tiny danger-text" data-user-delete="${esc(u.email)}" ${u.email === user.email ? 'disabled' : ''}>Delete</button>
          </div>
          <div class="user-password-row">
            <input class="form-input" type="text" autocomplete="off" spellcheck="false" data-user-password="${esc(u.email)}" value="${esc(u.password || '')}" placeholder="${u.password ? 'Password' : 'Reset required'}" />
            <button class="tiny" data-user-password-save="${esc(u.email)}">Save</button>
            <button class="tiny" data-user-password-generate="${esc(u.email)}">Generate</button>
          </div>
        </div>
      `).join('') || '<div class="empty-note">No beta users yet.</div>'}
    </div>
  `
  el.querySelector('#btn-beta-user-add').addEventListener('click', async () => {
    const input = el.querySelector('#beta-user-email')
    try {
      const created = await createUser(input.value)
      store.set('generatedPassword', { email: input.value, password: created.password })
      store.set('betaUsers', await listUsers())
      input.value = ''
    } catch (err) {
      if (isAuthFailure(err)) {
        await handleUserAdminFailure(err)
        return
      }
      store.set('generatedPassword', { email: 'Error', password: err.message || 'Could not create user' })
    }
  })
  el.querySelectorAll('[data-user-delete]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await deleteUser(btn.dataset.userDelete)
        store.set('betaUsers', await listUsers())
      } catch (err) {
        if (isAuthFailure(err)) {
          await handleUserAdminFailure(err)
          return
        }
        store.set('generatedPassword', { email: 'Error', password: err.message || 'Could not delete user' })
      }
    })
  })
  el.querySelectorAll('[data-user-password-save]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const email = btn.dataset.userPasswordSave
      const input = el.querySelector(`[data-user-password="${cssEscape(email)}"]`)
      await updateUserPassword(email, input?.value || '')
    })
  })
  el.querySelectorAll('[data-user-password-generate]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await updateUserPassword(btn.dataset.userPasswordGenerate, '')
    })
  })
}

async function updateUserPassword(email, password) {
  try {
    const updated = await setUserPassword(email, password)
    store.set('generatedPassword', { email, password: updated.password })
    store.set('betaUsers', await listUsers())
  } catch (err) {
    if (isAuthFailure(err)) {
      await handleUserAdminFailure(err)
      return
    }
    store.set('generatedPassword', { email: 'Error', password: err.message || 'Could not update password' })
  }
}

async function handleUserAdminFailure(err) {
  if (err.status === 401) {
    window.dispatchEvent(new CustomEvent('transcom-auth-invalid', {
      detail: { message: 'Session expired. Please log in again.' },
    }))
    return
  }
  try {
    const user = await me()
    store.set('authUser', user)
    if (!user?.is_admin) {
      store.set('betaUsers', [])
      store.set('generatedPassword', { email: 'Error', password: 'Please log in with an admin account.' })
      return
    }
  } catch {
    window.dispatchEvent(new CustomEvent('transcom-auth-invalid', {
      detail: { message: 'Session expired. Please log in again.' },
    }))
    return
  }
  store.set('generatedPassword', { email: 'Error', password: err.message || 'Forbidden' })
}

function startCheckInDialog({ speaker, duration }) {
  if (!speaker || activeCheckIn) return
  const seconds = Math.max(3, Math.min(Number(duration || CHECK_IN_SECONDS), 20))

  const dialog = document.createElement('div')
  dialog.className = 'checkin-modal'
  dialog.innerHTML = `
    <div class="checkin-dialog" role="dialog" aria-modal="true" aria-labelledby="checkin-title">
      <div class="checkin-head">
          <span class="swatch" style="background:${esc(speaker.color)}"></span>
        <div>
          <strong id="checkin-title">${esc(speaker.name)} Check-in</strong>
          <span>Speak live into the selected feed for ${seconds.toFixed(0)} seconds</span>
        </div>
      </div>
      <div class="checkin-meter">
        <span id="checkin-progress"></span>
      </div>
      <div class="checkin-readout">
        <span id="checkin-remaining">${seconds.toFixed(1)}s</span>
        <span>recording</span>
      </div>
      <button class="btn danger" id="btn-cancel-checkin">Cancel</button>
    </div>
  `
  document.body.appendChild(dialog)
  ws.send('enrollment_start', {
    speaker_id: speaker.id,
    duration_seconds: seconds,
  })

  const progressEl = dialog.querySelector('#checkin-progress')
  const remainingEl = dialog.querySelector('#checkin-remaining')
  const started = performance.now()

  activeCheckIn = {
    dialog,
    timer: window.setInterval(() => {
      const elapsed = Math.min((performance.now() - started) / 1000, seconds)
      const remaining = Math.max(seconds - elapsed, 0)
      progressEl.style.width = `${(elapsed / seconds) * 100}%`
      remainingEl.textContent = `${remaining.toFixed(1)}s`

      if (elapsed >= seconds) {
        finishCheckIn()
      }
    }, 100),
  }

  dialog.querySelector('#btn-cancel-checkin').addEventListener('click', cancelCheckIn)
}

function finishCheckIn() {
  if (!activeCheckIn) return
  const { dialog, timer } = activeCheckIn
  window.clearInterval(timer)
  activeCheckIn = null
  dialog.remove()
}

function cancelCheckIn() {
  if (!activeCheckIn) return
  const { dialog, timer } = activeCheckIn
  window.clearInterval(timer)
  activeCheckIn = null
  dialog.remove()
}

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value)
  return String(value ?? '').replace(/["\\]/g, '\\$&')
}
