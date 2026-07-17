# Local Development Notes

Project:
- TransCom
- Local-first live transcription for intercom / production audio

Setup:
- Repo root: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Install dependencies: `./scripts/setup.sh`

Useful run commands:
- Renderer only: `npm run dev:renderer`
- Backend only:
  `PYTHONUNBUFFERED=1 PYTHONPATH="$PWD" backend/.venv/bin/python backend/main.py`
- Local web testing with auth disabled:
  `TRANSCOM_WEB_PORT=8081 TRANSCOM_AUTH_DISABLED=1 backend/.venv/bin/python backend/main.py`
- Electron dev: `npm run dev`

Typical local web setup:
- Vite UI: `http://localhost:5747/`
- Backend web API in local test mode: `http://127.0.0.1:8081/`
- Vite proxies `/api` to the backend web port
- `TRANSCOM_AUTH_DISABLED=1` auto-allows a fake admin user for UI testing

Tests:
- `backend/.venv/bin/python -m pytest`
- `TRANSCOM_ASR_BACKEND=faster-whisper backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup`

Latest verified results on 2026-07-01:
- `pytest`: `51 passed, 1 warning`
- Benchmark, `faster-whisper` path:
  - WER `0.2667`
  - `languages_used = ["de", "en"]`
  - `first_emit_seconds = 3.54`
  - `avg_infer_seconds = 0.52`

Current caveats:
- Apple Silicon runtime still defaults to `mlx`, but the more trustworthy quality benchmark today is the `faster-whisper` path.
- Demo WAV/file mode is selectable in the UI again.
- File mode currently does not provide audible playback monitoring.
- The session controls and feed controls are separate, which has confused real users.
