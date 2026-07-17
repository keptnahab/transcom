import store from '../store.js'
import ws from '../ws.js'

const pane = document.getElementById('transcript-pane')
const banner = document.getElementById('activity-banner')
const countEl = document.getElementById('activity-count')

let unseenCount = 0
let searchQuery = ''

function renderEmptyState() {
  pane.innerHTML = `
    <div class="transcript-empty">
      <div class="empty-wave" aria-hidden="true">
        ${[18, 32, 54, 28, 68, 42, 82, 46, 62, 30, 48, 24].map(height => `<span style="height:${height}%"></span>`).join('')}
      </div>
      <strong>Bereit für das erste Wort</strong>
      <span>Audioquelle wählen und links die Transkription starten.</span>
    </div>
  `
}

function isAtBottom() {
  return pane.scrollHeight - pane.scrollTop - pane.clientHeight < 60
}

function scrollToBottom() {
  pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' })
  unseenCount = 0
  banner.classList.add('hidden')
}

banner.addEventListener('click', scrollToBottom)

function formatTs(epoch) {
  const d = new Date(epoch * 1000)
  return d.toTimeString().slice(0, 8)
}

function channelColor(channelId) {
  const ch = store.get('channels').find(c => c.id === channelId)
  return ch?.color || '#7070a0'
}

function channelLabel(channelId) {
  const ch = store.get('channels').find(c => c.id === channelId)
  return ch?.label || channelId.slice(0, 4).toUpperCase()
}

function matchesSearch(text) {
  if (!searchQuery) return false
  return text.toLowerCase().includes(searchQuery.toLowerCase())
}

function renderRow(seg) {
  const row = document.createElement('div')
  row.className = 'transcript-row'
  if (seg.requires_confirmation && !seg.confirmation_acknowledged) row.classList.add('requires-confirmation')
  row.dataset.segmentId = seg.segment_id
  row.dataset.channelId = seg.channel_id

  const color = seg.speaker_color || channelColor(seg.channel_id)
  const speakerName = seg.corrected_speaker_name || seg.speaker_name || channelLabel(seg.channel_id)
  const confidence = Math.round((seg.speaker_confidence || 0) * 100)
  const commandBadge = seg.safety_command_id
    ? `<span class="command-badge" title="${escapeHtml(seg.safety_command_id)}">BEFEHL</span>`
    : ''
  const rawAudit = seg.raw_text && seg.raw_text !== seg.text
    ? ` title="Roh erkannt: ${escapeHtml(seg.raw_text)}"`
    : ''
  const rawAuditLine = seg.raw_text && seg.raw_text !== seg.text
    ? `<small class="raw-audit">Roh erkannt: ${escapeHtml(seg.raw_text)}</small>`
    : ''
  const safetyConfirmationLine = seg.safety_confirmation_used
    ? `<small class="raw-audit">Zweitprüfung (${escapeHtml(seg.safety_confirmation_model || 'unbekannt')}): ${escapeHtml(seg.safety_confirmation_raw_text || '')}</small>`
    : ''
  row.style.borderLeftColor = color
  if (matchesSearch(seg.text)) row.classList.add('highlighted')

  row.innerHTML = `
    <span class="row-ts">${formatTs(seg.timestamp)}</span>
    <span class="row-label" style="color:${color}" title="Speaker confidence ${confidence}%">${escapeHtml(speakerName)}</span>
    <span class="row-text"${rawAudit}>${seg.requires_confirmation ? `<span class="confirm-badge ${seg.confirmation_acknowledged ? 'acknowledged' : ''}">${seg.confirmation_acknowledged ? 'BESTÄTIGT' : 'PRÜFEN'}</span>` : ''}${commandBadge}${escapeHtml(seg.text)}${seg.requires_confirmation && !seg.confirmation_acknowledged ? '<button class="confirm-action" type="button">Bestätigen</button>' : ''}${rawAuditLine}${safetyConfirmationLine}</span>
    <select class="speaker-correct" title="Correct speaker">
      <option value="">Speaker</option>
      ${(store.get('speakers') || []).map(sp => `<option value="${sp.id}">${escapeHtml(sp.name)}</option>`).join('')}
      <option value="unknown">Unknown</option>
    </select>
  `
  row.querySelector('.speaker-correct').addEventListener('change', e => {
    const value = e.target.value
    if (!value) return
    const speaker = (store.get('speakers') || []).find(sp => sp.id === value)
    ws.send('segment_correct_speaker', {
      segment_id: seg.segment_id,
      speaker_id: speaker?.id || null,
      speaker_name: speaker?.name || 'Unknown',
    })
  })
  row.querySelector('.confirm-action')?.addEventListener('click', () => {
    ws.send('segment_acknowledge_confirmation', { segment_id: seg.segment_id })
  })
  return row
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char])
}

function highlightSearch(query) {
  searchQuery = query
  pane.querySelectorAll('.transcript-row').forEach(row => {
    const textEl = row.querySelector('.row-text')
    if (!textEl) return
    if (query && textEl.textContent.toLowerCase().includes(query.toLowerCase())) {
      row.classList.add('highlighted')
    } else {
      row.classList.remove('highlighted')
    }
  })
}

// Full re-render (on init)
function renderAll(segments) {
  pane.innerHTML = ''
  if (!segments.length) {
    renderEmptyState()
    return
  }
  segments.forEach(seg => pane.appendChild(renderRow(seg)))
  scrollToBottom()
}

// Incremental append (on new transcript_segment)
function appendSegment(seg) {
  const atBottom = isAtBottom()
  pane.querySelector('.transcript-empty')?.remove()
  const existing = pane.querySelector(`[data-segment-id="${CSS.escape(seg.segment_id)}"]`)
  const row = renderRow(seg)
  if (existing) {
    existing.replaceWith(row)
  } else {
    pane.appendChild(row)
  }
  if (atBottom) {
    scrollToBottom()
  } else if (!existing) {
    unseenCount++
    countEl.textContent = unseenCount
    banner.classList.remove('hidden')
  }
}

export function init() {
  renderEmptyState()
  // Re-render when search query changes
  store.subscribe('searchQuery', q => highlightSearch(q))

  // Full render on init_state
  store.subscribe('segments', segments => {
    // Only do full render on the initial load (when pane is empty)
    if (!pane.querySelector('.transcript-row') && segments.length > 0) {
      renderAll(segments)
    }
  })
}

export { appendSegment, renderAll, highlightSearch }
