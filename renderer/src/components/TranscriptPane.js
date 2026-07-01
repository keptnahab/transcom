import store from '../store.js'
import ws from '../ws.js'

const pane = document.getElementById('transcript-pane')
const banner = document.getElementById('activity-banner')
const countEl = document.getElementById('activity-count')

let unseenCount = 0
let searchQuery = ''

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
  row.dataset.segmentId = seg.segment_id
  row.dataset.channelId = seg.channel_id

  const color = seg.speaker_color || channelColor(seg.channel_id)
  const speakerName = seg.corrected_speaker_name || seg.speaker_name || channelLabel(seg.channel_id)
  const confidence = Math.round((seg.speaker_confidence || 0) * 100)
  row.style.borderLeftColor = color
  if (matchesSearch(seg.text)) row.classList.add('highlighted')

  row.innerHTML = `
    <span class="row-ts">${formatTs(seg.timestamp)}</span>
    <span class="row-label" style="color:${color}" title="Speaker confidence ${confidence}%">${escapeHtml(speakerName)}</span>
    <span class="row-text">${escapeHtml(seg.text)}</span>
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
  return row
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
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
  segments.forEach(seg => pane.appendChild(renderRow(seg)))
  scrollToBottom()
}

// Incremental append (on new transcript_segment)
function appendSegment(seg) {
  const atBottom = isAtBottom()
  pane.appendChild(renderRow(seg))
  if (atBottom) {
    scrollToBottom()
  } else {
    unseenCount++
    countEl.textContent = unseenCount
    banner.classList.remove('hidden')
  }
}

export function init() {
  // Re-render when search query changes
  store.subscribe('searchQuery', q => highlightSearch(q))

  // Full render on init_state
  store.subscribe('segments', segments => {
    // Only do full render on the initial load (when pane is empty)
    if (pane.children.length === 0 && segments.length > 0) {
      renderAll(segments)
    }
  })
}

export { appendSegment, renderAll, highlightSearch }
