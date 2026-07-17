# Project Status

Goal:
- Deliver a local-first TransCom beta that can transcribe mixed intercom audio in German and English with practical live latency, coherent utterance grouping, and useful speaker assignment.

Current phase:
- Stabilization and quality improvement.
- The product is beyond prototype stage, but not ready for confident beta use on recognition quality.
- As of 2026-07-04, the work is being moved to Dropbox for about six weeks of MacBook-only continuation.

Current MacBook path after move:
- `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom`

Implemented:
- Electron/Vite frontend and Python backend
- session creation and local storage
- live input and audio-file feed modes
- sherpa-based VAD path with fallback
- local speaker service and check-in UI
- transcript persistence and export
- LAN read-only viewer
- beta web auth and admin user management
- auth-bypass local test mode

Verified on 2026-07-04:
- `backend/.venv/bin/python -m pytest` -> `52 passed, 1 warning`
- `npm run build` -> passed

Latest benchmark reference from 2026-07-01:
- `backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup`
  - WER: `0.2667`
  - first emit: `3.59s`
  - avg infer: `0.56s`
  - languages used: `de`, `en`

What is working well enough:
- The app starts and can be tested locally in browser mode.
- Demo WAV selection is present in the UI again.
- The backend honors file-source mode correctly.
- Auth-disabled testing unblocks UI work.
- The fixture benchmark is materially better than the old `0.4167` baseline.
- Default Apple-Silicon launch uses the pinned MLX hybrid: Turbo for original
  audio `<= 3.0 s`, Full above 3.0 s, with pinned faster-whisper Small available
  for guarded fallback and explicitly enabled Safety confirmation.
- Updated transcript rows are replaced in the UI instead of appended when the backend reuses a segment ID.
- File/demo mode has browser audio monitoring and visible native audio controls.

What is not good enough:
- Real transcript quality is still described by the user as "katastrophal schlecht".
- Real latency still feels too slow.
- The duplicate opening line needs a fresh UI run against the updated backend to confirm the targeted fix.
- Session lifecycle and feed lifecycle are still hard to understand from the UI.

Release reality:
- The current bottleneck is not missing features.
- The current bottleneck is transcript quality and operator confidence.
