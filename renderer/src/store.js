/**
 * Simple observable client state.
 *
 * Usage:
 *   import store from './store.js'
 *   store.subscribe('channels', (channels) => renderChannels(channels))
 *   store.set('channels', [...])
 */

class Store {
  constructor() {
    this._state = {
      channels: [],         // ChannelInfo[]
      segments: [],         // SegmentInfo[]  (all, chronological)
      devices: [],          // AudioDevice[]
      audioSource: { mode: 'live', path: null, demo_path: null },
      session: null,
      speakers: [],
      share: { enabled: false, url: null, token: null },
      authUser: null,
      betaUsers: [],
      generatedPassword: null,
      status: {},
      engineStatus: { state: 'idle', message: 'Engine idle' },
      searchQuery: '',
      connected: false,
    }
    this._listeners = {}
  }

  get(key) { return this._state[key] }

  set(key, value) {
    this._state[key] = value
    this._emit(key, value)
  }

  subscribe(key, fn) {
    if (!this._listeners[key]) this._listeners[key] = []
    this._listeners[key].push(fn)
    // Immediately call with current value
    fn(this._state[key])
    return () => {
      this._listeners[key] = this._listeners[key].filter(h => h !== fn)
    }
  }

  _emit(key, value) {
    const fns = this._listeners[key] || []
    fns.forEach(fn => fn(value))
  }

  // Helpers for common mutations
  addSegment(seg) {
    const existing = this._state.segments.findIndex(s => s.segment_id === seg.segment_id)
    if (existing === -1) {
      this._state.segments = [...this._state.segments, seg]
    } else {
      this._state.segments = this._state.segments.map(s => s.segment_id === seg.segment_id ? seg : s)
    }
    this._emit('segments', this._state.segments)
  }

  upsertChannel(ch) {
    const existing = this._state.channels.findIndex(c => c.id === ch.id)
    if (existing === -1) {
      this._state.channels = [...this._state.channels, ch]
    } else {
      this._state.channels = this._state.channels.map(c => c.id === ch.id ? ch : c)
    }
    this._emit('channels', this._state.channels)
  }

  removeChannel(id) {
    this._state.channels = this._state.channels.filter(c => c.id !== id)
    this._emit('channels', this._state.channels)
  }

  setSegments(segments) {
    this._state.segments = segments
    this._emit('segments', this._state.segments)
  }

  upsertSegment(seg) {
    this._state.segments = this._state.segments.map(s => s.segment_id === seg.segment_id ? seg : s)
    this._emit('segments', this._state.segments)
  }
}

export default new Store()
