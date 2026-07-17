import store from '../store.js'
import ws from '../ws.js'
import { stopForSessionChange } from './ChannelPanel.js'

const selectedIds = new Set()
let selectionMode = false
let revealedId = null
let contextId = null
let pendingTrash = null
let trashInProgress = false

export function init() {
  store.subscribe('sessions', render)
  store.subscribe('session', render)
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest?.('.library-context-menu, [data-more-session]')) closeContextMenu()
  })
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeContextMenu()
  })
}

function render() {
  const panel = document.getElementById('transcript-library')
  if (!panel) return
  const sessions = store.get('sessions') || []
  const current = store.get('session')
  const knownIds = new Set(sessions.map(item => item.id))
  for (const id of selectedIds) {
    if (!knownIds.has(id)) selectedIds.delete(id)
  }

  panel.innerHTML = `
    <div class="library-header">
      <div>
        <span>Transkriptverwaltung</span>
        <strong>Transkripte</strong>
      </div>
      <div class="library-header-actions">
        <span class="library-count">${sessions.length}</span>
        <button class="library-select-mode ${selectionMode ? 'active' : ''}" id="library-select-mode" type="button">${selectionMode ? 'Fertig' : 'Auswählen'}</button>
      </div>
    </div>
    <button class="library-new" id="library-new" type="button">
      <span aria-hidden="true">+</span>
      <span><strong>Neues Transkript</strong><small>Leeres Fenster öffnen</small></span>
    </button>
    ${selectionMode ? selectionBar(sessions.length) : ''}
    <div class="library-divider"><span>Gespeichert</span></div>
    <div class="library-list">
      ${sessions.length ? sessions.map(item => sessionCard(item, current?.id)).join('') : `
        <div class="library-empty">
          <span class="library-empty-mark" aria-hidden="true"></span>
          <strong>Noch keine Transkripte</strong>
          <span>Neue Transkripte erscheinen automatisch hier.</span>
        </div>
      `}
    </div>
    <p class="library-footnote">Rechtsklick oder nach links wischen für weitere Aktionen.</p>
    <div class="library-context-menu" id="library-context-menu" hidden>
      <button type="button" data-context-action="open">Öffnen</button>
      <button type="button" data-context-action="finder">Im Finder zeigen</button>
      <button type="button" data-context-action="select">Auswählen</button>
      <button class="danger" type="button" data-context-action="delete">Löschen</button>
    </div>
  `

  wirePanel(panel, sessions)
  if (pendingTrash && !trashInProgress && !pendingTrash.some(item => item.id === current?.id)) {
    queueMicrotask(performPendingTrash)
  }
}

function selectionBar(total) {
  const count = selectedIds.size
  return `
    <div class="library-selection-bar">
      <strong>${count} ausgewählt</strong>
      <button id="library-select-all" type="button">${count === total && total ? 'Alle abwählen' : 'Alle auswählen'}</button>
      <button id="library-open-selected" type="button" ${count === 1 ? '' : 'disabled'}>Öffnen</button>
      <button class="danger" id="library-delete-selected" type="button" ${count ? '' : 'disabled'}>Löschen</button>
    </div>
  `
}

function sessionCard(item, currentId) {
  const isCurrent = item.id === currentId
  const isSelected = selectedIds.has(item.id)
  const isRevealed = revealedId === item.id
  return `
    <article class="library-card ${isCurrent ? 'current' : ''} ${isSelected ? 'selected' : ''}" data-session-card="${esc(item.id)}">
      <div class="library-swipe-actions" aria-label="Schnellaktionen">
        <button type="button" data-card-action="open" data-session-id="${esc(item.id)}">Öffnen</button>
        <button type="button" data-card-action="finder" data-session-id="${esc(item.id)}">Finder</button>
        <button class="danger" type="button" data-card-action="delete" data-session-id="${esc(item.id)}">Löschen</button>
      </div>
      <div class="library-card-surface ${isRevealed ? 'revealed' : ''}" data-swipe-surface="${esc(item.id)}">
        <button class="library-checkbox ${selectionMode ? 'visible' : ''}" type="button" data-select-session="${esc(item.id)}" aria-label="${esc(item.name)} auswählen" aria-pressed="${isSelected}">
          <span aria-hidden="true">${isSelected ? '✓' : ''}</span>
        </button>
        <button class="library-open" type="button" data-open-session="${esc(item.id)}" ${isCurrent ? 'aria-current="true"' : ''}>
          <span class="library-file-icon" aria-hidden="true"></span>
          <span class="library-card-copy">
            <strong title="${esc(item.name)}">${esc(item.name)}</strong>
            <small>${formatDate(item.created_at)}${isCurrent ? ' · geöffnet' : ''}</small>
          </span>
        </button>
        <button class="library-more" type="button" data-more-session="${esc(item.id)}" aria-label="Weitere Aktionen für ${esc(item.name)}">•••</button>
      </div>
    </article>
  `
}

function wirePanel(panel, sessions) {
  panel.querySelector('#library-new')?.addEventListener('click', createTranscript)
  panel.querySelector('#library-select-mode')?.addEventListener('click', () => {
    selectionMode = !selectionMode
    selectedIds.clear()
    revealedId = null
    render()
  })
  panel.querySelector('#library-select-all')?.addEventListener('click', () => {
    if (selectedIds.size === sessions.length) selectedIds.clear()
    else sessions.forEach(item => selectedIds.add(item.id))
    render()
  })
  panel.querySelector('#library-open-selected')?.addEventListener('click', () => {
    if (selectedIds.size === 1) openTranscript([...selectedIds][0])
  })
  panel.querySelector('#library-delete-selected')?.addEventListener('click', () => {
    queueTrash(sessions.filter(item => selectedIds.has(item.id)))
  })

  panel.querySelectorAll('[data-select-session]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation()
      toggleSelection(button.dataset.selectSession)
    })
  })
  panel.querySelectorAll('[data-open-session]').forEach(button => {
    button.addEventListener('click', () => {
      if (selectionMode) toggleSelection(button.dataset.openSession)
      else openTranscript(button.dataset.openSession)
    })
  })
  panel.querySelectorAll('[data-card-action]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation()
      handleAction(button.dataset.cardAction, button.dataset.sessionId, sessions)
    })
  })
  panel.querySelectorAll('[data-more-session]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation()
      const rect = button.getBoundingClientRect()
      showContextMenu(button.dataset.moreSession, rect.right, rect.bottom + 4)
    })
  })
  panel.querySelectorAll('[data-session-card]').forEach(card => {
    card.addEventListener('contextmenu', event => {
      event.preventDefault()
      showContextMenu(card.dataset.sessionCard, event.clientX, event.clientY)
    })
  })
  panel.querySelectorAll('[data-swipe-surface]').forEach(surface => wireSwipe(surface))
  panel.querySelectorAll('[data-context-action]').forEach(button => {
    button.addEventListener('click', () => {
      handleAction(button.dataset.contextAction, contextId, sessions)
      closeContextMenu()
    })
  })
}

function wireSwipe(surface) {
  let startX = 0
  let startY = 0
  let tracking = false
  const id = surface.dataset.swipeSurface

  surface.addEventListener('pointerdown', event => {
    if (event.button !== 0 || selectionMode || event.target.closest('[data-more-session], [data-select-session]')) return
    startX = event.clientX
    startY = event.clientY
    tracking = true
  })
  surface.addEventListener('pointermove', event => {
    if (!tracking) return
    const dx = event.clientX - startX
    const dy = event.clientY - startY
    if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 8) {
      tracking = false
      return
    }
    if (Math.abs(dx) < 5) return
    if (!surface.hasPointerCapture?.(event.pointerId)) surface.setPointerCapture?.(event.pointerId)
    const base = revealedId === id ? -156 : 0
    const offset = Math.max(-156, Math.min(0, base + dx))
    surface.style.transition = 'none'
    surface.style.transform = `translateX(${offset}px)`
  })
  surface.addEventListener('pointerup', event => {
    if (!tracking) return
    tracking = false
    const dx = event.clientX - startX
    if (dx < -30) revealedId = id
    else if (dx > 30) revealedId = null
    surface.style.removeProperty('transition')
    surface.style.removeProperty('transform')
    if (Math.abs(dx) > 12) {
      event.preventDefault()
      render()
    }
  })
  surface.addEventListener('pointercancel', () => {
    tracking = false
    surface.style.removeProperty('transition')
    surface.style.removeProperty('transform')
  })
}

function handleAction(action, id, sessions) {
  const item = sessions.find(session => session.id === id)
  if (!item) return
  revealedId = null
  if (action === 'open') openTranscript(id)
  if (action === 'finder') window.electronAPI?.openPath?.(item.session_dir)
  if (action === 'select') {
    selectionMode = true
    selectedIds.add(id)
    render()
  }
  if (action === 'delete') queueTrash([item])
}

function toggleSelection(id) {
  if (!selectionMode) selectionMode = true
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
  render()
}

function showContextMenu(id, x, y) {
  contextId = id
  const menu = document.getElementById('library-context-menu')
  if (!menu) return
  menu.hidden = false
  const width = 164
  const height = 150
  menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - width - 8))}px`
  menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - height - 8))}px`
}

function closeContextMenu() {
  contextId = null
  const menu = document.getElementById('library-context-menu')
  if (menu) menu.hidden = true
}

function createTranscript() {
  const current = store.get('session')
  stopForSessionChange(current)
  ws.send('session_create', { name: '', root_dir: current?.root_dir || '' })
}

function openTranscript(id) {
  const current = store.get('session')
  if (!id || current?.id === id) return
  stopForSessionChange(current)
  selectedIds.clear()
  selectionMode = false
  revealedId = null
  ws.send('session_open', { id })
}

function queueTrash(items) {
  if (!items.length) return
  if (!window.electronAPI?.trashPaths) {
    window.alert('Das Löschen ist nur in der TransCom-Desktop-App verfügbar.')
    return
  }
  const label = items.length === 1 ? `„${items[0].name}“` : `${items.length} Transkripte`
  if (!window.confirm(`${label} in den Papierkorb verschieben?`)) return

  pendingTrash = items
  const current = store.get('session')
  if (items.some(item => item.id === current?.id)) {
    stopForSessionChange(current)
    ws.send('session_create', { name: '', root_dir: current?.root_dir || '' })
    return
  }
  performPendingTrash()
}

async function performPendingTrash() {
  if (!pendingTrash || trashInProgress) return
  const items = pendingTrash
  pendingTrash = null
  trashInProgress = true
  try {
    const result = await window.electronAPI.trashPaths(items.map(item => item.session_dir))
    const trashedPaths = new Set(result?.trashed || [])
    const trashedIds = new Set(items.filter(item => trashedPaths.has(item.session_dir)).map(item => item.id))
    for (const id of trashedIds) selectedIds.delete(id)
    store.set('sessions', (store.get('sessions') || []).filter(item => !trashedIds.has(item.id)))
    if (result?.errors?.length) window.alert(`Nicht alle Transkripte konnten gelöscht werden: ${result.errors[0].message}`)
    ws.send('session_list', {})
  } catch (error) {
    window.alert(`Das Transkript konnte nicht in den Papierkorb verschoben werden: ${error.message || error}`)
  } finally {
    trashInProgress = false
    if (!selectedIds.size) selectionMode = false
    render()
  }
}

function formatDate(value) {
  const timestamp = Number(value) * 1000
  if (!Number.isFinite(timestamp)) return 'Gespeichert'
  return new Intl.DateTimeFormat('de-DE', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(timestamp))
}

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
