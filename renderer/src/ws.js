/**
 * WebSocket singleton with automatic reconnect.
 *
 * Usage:
 *   import ws from './ws.js'
 *   ws.on('transcript_segment', handler)
 *   ws.send('add_channel', { name: 'Mic 1', device_index: 0, color: '#3498db' })
 */

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.hostname || '127.0.0.1'}:8765`
const BACKOFF = [500, 1000, 2000, 4000, 8000]

class WSClient {
  constructor() {
    this._socket = null
    this._handlers = {}        // type → [fn, ...]
    this._connectHandlers = []
    this._disconnectHandlers = []
    this._retryCount = 0
    this._intentionalClose = false
    this._token = null
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  send(type, payload = {}, id = null) {
    if (!this._socket || this._socket.readyState !== WebSocket.OPEN) {
      console.warn('[ws] Cannot send — not connected', type)
      return
    }
    this._socket.send(JSON.stringify({ type, id, payload }))
  }

  on(type, fn) {
    if (!this._handlers[type]) this._handlers[type] = []
    this._handlers[type].push(fn)
    return () => this.off(type, fn)
  }

  off(type, fn) {
    if (!this._handlers[type]) return
    this._handlers[type] = this._handlers[type].filter(h => h !== fn)
  }

  onConnect(fn) { this._connectHandlers.push(fn); return () => { this._connectHandlers = this._connectHandlers.filter(h => h !== fn) } }
  onDisconnect(fn) { this._disconnectHandlers.push(fn); return () => { this._disconnectHandlers = this._disconnectHandlers.filter(h => h !== fn) } }

  get connected() { return this._socket?.readyState === WebSocket.OPEN }

  connect(token) {
    this._token = token
    if (!this._token) return
    if (this.connected) return
    this._connect()
  }

  close() {
    this._intentionalClose = true
    this._socket?.close()
    this._socket = null
  }

  // ------------------------------------------------------------------
  // Internal
  // ------------------------------------------------------------------

  _connect() {
    this._intentionalClose = false
    if (!this._token) return
    try {
      this._socket = new WebSocket(`${WS_URL}?token=${encodeURIComponent(this._token)}`)
    } catch (e) {
      this._scheduleReconnect()
      return
    }

    this._socket.onopen = () => {
      this._retryCount = 0
      this._connectHandlers.forEach(fn => fn())
      // Request initial state
      this.send('init')
    }

    this._socket.onmessage = (event) => {
      let msg
      try { msg = JSON.parse(event.data) } catch { return }
      const fns = this._handlers[msg.type] || []
      fns.forEach(fn => fn(msg.payload, msg.id))
    }

    this._socket.onclose = (event) => {
      this._disconnectHandlers.forEach(fn => fn())
      if (event.code === 4401) {
        this._intentionalClose = true
        this._socket = null
        window.dispatchEvent(new CustomEvent('transcom-auth-invalid', {
          detail: { message: 'Session expired. Please log in again.' },
        }))
        return
      }
      if (!this._intentionalClose) this._scheduleReconnect()
    }

    this._socket.onerror = () => {
      // onclose fires after onerror; just let reconnect handle it
    }
  }

  _scheduleReconnect() {
    const delay = BACKOFF[Math.min(this._retryCount, BACKOFF.length - 1)]
    this._retryCount++
    setTimeout(() => this._connect(), delay)
  }
}

export default new WSClient()
