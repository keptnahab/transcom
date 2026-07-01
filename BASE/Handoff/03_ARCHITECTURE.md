# Architecture

Top-level shape:
- Electron desktop shell
- Vite-built renderer UI
- Python backend
- WebSocket control/data channel
- SQLite persistence
- Separate lightweight HTTP server for beta web UI
- Separate token-gated LAN viewer

Main runtime flow:
1. Renderer or Electron UI connects to the Python backend over WebSocket.
2. Backend manages sessions, audio sources, speaker profiles, transcript storage, and share state.
3. Audio arrives from live input or file feed.
4. Audio is segmented for speech.
5. Segments are transcribed by the ASR engine.
6. Speaker matching is attempted on segment audio.
7. Transcript rows are stored in SQLite and broadcast to clients.
8. Admin/auth for the beta web app is served by a separate HTTP server.

Important backend modules:
- `backend/main.py`
  Wires all subsystems together, loads the ASR engine, starts auth, web app, VAD segmenter, speaker service, transcription pool, channel manager, and WebSocket server.
- `backend/config.py`
  Central runtime config through environment variables.
- `backend/audio/capture.py`
  Captures live audio and feeds the ring buffer.
- `backend/audio/ring_buffer.py`
  Produces overlapping chunks for ASR context handling.
- `backend/audio/segmentation.py`
  Speech segmentation layer intended to keep VAD logic out of low-level capture.
- `backend/transcription/engine.py`
  ASR wrapper. Uses `mlx-whisper` by default on Apple Silicon, otherwise `faster-whisper`.
- `backend/transcription/worker_pool.py`
  Serializes transcription work and emits status/results.
- `backend/transcript/stabilizer.py`
  Contains text dedupe/stabilization and timed-word stabilization.
- `backend/transcript/store.py`
  Stores transcript segments in memory plus SQLite and performs recent-duplicate suppression.
- `backend/speaker/service.py`
  Speaker profile registry, enrollment, matching, sherpa integration, and auto-speaker fallback behavior.
- `backend/auth/service.py`
  Beta-user auth, sessions, bootstrap admin, and visible password management.
- `backend/web/server.py`
  Lightweight HTTP server for the beta web app and auth/user endpoints.
- `backend/share/server.py`
  Read-only LAN viewer with token access.
- `backend/server/ws_server.py`
  Main websocket API surface between UI and backend.

Frontend structure:
- `renderer/index.html`
- `renderer/src/main.js`
- `renderer/src/store.js`
- `renderer/src/ws.js`
- `renderer/src/auth.js`
- `renderer/src/components/ChannelPanel.js`
- `renderer/src/components/Toolbar.js`
- `renderer/src/components/TranscriptPane.js`
- `renderer/src/components/SpeakerPanel.js`
- `renderer/src/styles/app.css`

Persistence:
- Transcript DB default: `transcom_session.db` or per-session DB depending on session manager flow
- Auth DB default: `transcom_auth.db`
- Session root default: `sessions/`

Current architectural weakness:
- Transcript stabilization and transcript row creation are not yet aligned. The timed word stabilizer emits accepted fragments, but the store currently persists them as separate rows instead of maintaining an utterance-in-progress.
- Speaker matching currently works at segment/chunk level and can fall back to auto-cluster creation too eagerly.

Current auth model:
- Admin bootstrap user is created if no users exist.
- Web app exposes `/api/login`, `/api/me`, `/api/users`, `POST /api/users/{email}/password`, and delete routes.
- Password visibility is intentionally stored in `visible_password` for admin UX in beta mode.
