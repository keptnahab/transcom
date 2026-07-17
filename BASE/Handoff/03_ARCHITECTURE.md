# Architecture

Top-level runtime:
- Electron desktop shell
- Vite-built renderer
- Python backend
- WebSocket control/data channel
- SQLite persistence
- HTTP server for beta login/web app
- Separate token-gated LAN viewer

Main runtime flow:
1. Renderer connects to the backend over WebSocket.
2. Backend exposes session state, audio source state, engine status, speakers, and transcript rows.
3. Audio comes either from a live input device or from a file feed.
4. `backend/audio/segmentation.py` turns raw audio into speech segments, using sherpa-onnx VAD when available and RMS fallback otherwise.
5. Final speech segments are sent to the transcription pool.
6. The ASR engine transcribes the segment and returns language plus word timing when available.
7. Speaker matching is attempted on the final speech segment audio.
8. Stabilizer/store logic deduplicates and persists transcript rows.
9. Rows are broadcast to the operator UI and optional LAN viewer.

Important product behavior:
- Session lifecycle and feed lifecycle are separate today.
- `Create` creates the session folder and DB.
- `Start` marks the session active.
- `Start Feed` starts capture or file playback.
- This is technically valid, but it is confusing in the current UX.

Important backend modules:
- `backend/main.py`
  - Wires engine, VAD segmenter, transcription pool, speaker service, session manager, transcript store, web app, and WebSocket server.
- `backend/config.py`
  - Central environment/config source.
- `backend/audio/capture.py`
  - Captures live audio or streams file audio through the same pipeline.
- `backend/audio/segmentation.py`
  - Speech segmenter. Intended to prevent non-speech windows from reaching ASR.
- `backend/transcription/engine.py`
  - ASR wrapper for `mlx-whisper` and `faster-whisper`.
  - Enforces language fallback discipline around `de/en`.
- `backend/transcription/worker_pool.py`
  - Serial transcription queue and result dispatch.
- `backend/transcript/stabilizer.py`
  - Timed-word stabilizer and fallback text stabilizer.
- `backend/transcript/store.py`
  - Transcript persistence and recent duplicate suppression.
- `backend/speaker/service.py`
  - Speaker enrollment and matching.
- `backend/auth/service.py`
  - Beta auth plus local auth-disabled behavior.
- `backend/web/server.py`
  - Beta web server and `/api/*` routes.
- `backend/server/ws_server.py`
  - Main websocket protocol surface.

Frontend structure:
- `renderer/src/main.js`
  - Receives `init_state`, `audio_source_state`, and `backend_status`.
- `renderer/src/store.js`
  - Holds current UI state including `audioSourceMode`.
- `renderer/src/components/ChannelPanel.js`
  - Renders live/file controls, demo WAV, and start/stop feed actions.
- `renderer/src/auth.js`
  - Uses `/api/*` and can auto-bootstrap via `me()` in auth-disabled test mode.

Current architectural weak points:
- The file-feed testing path works, but there is no playback monitoring output for the user to hear.
- The stabilizer/store boundary still does not fully prevent the duplicate opening row.
- Benchmark improvements do not yet translate cleanly to user-perceived quality in the main UI.
