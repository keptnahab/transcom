# Setup

Install:
- From the repo root: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Run: `./scripts/setup.sh`
- Notes:
  - expects Python 3.11+ if available, otherwise `python3`
  - installs `portaudio` via Homebrew if missing
  - creates `backend/.venv`
  - installs Python requirements
  - installs Node dependencies
  - pre-downloads the default `faster-whisper` model

Run:
- Renderer only: `npm run dev:renderer`
- Backend only:
  `PYTHONUNBUFFERED=1 PYTHONPATH="$PWD" backend/.venv/bin/python backend/main.py`
- Electron dev: `npm run dev`
- Beta web helper: `./scripts/beta_server.sh`

Build:
- Renderer: `npm run build:renderer`
- Full desktop package: `npm run build`

Test:
- Unit/integration tests: `backend/.venv/bin/python -m pytest`
- Benchmark: `backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup`

Important environment/config:
- Web app port: `TRANSCOM_WEB_PORT` default `8080`
- WebSocket port: fixed `8765`
- Share port: `TRANSCOM_SHARE_PORT` default `8787`
- Default ASR backend:
  - `mlx` on macOS arm64
  - `faster-whisper` elsewhere
- Intended language controls:
  - `TRANSCOM_LANG`
  - `TRANSCOM_ALLOWED_LANGS` default `de,en`
  - `TRANSCOM_DEFAULT_LANG` default `de`

Current verification state on 2026-07-01:
- `pytest` passes: `43 passed, 1 warning`
- renderer build passes
- benchmark currently crashes on this machine with MLX/Metal

Git:
- Repo path: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Remote: `origin -> https://github.com/keptnahab/transcom.git`
- Branch: `main`
- Pushed commit: `8ea2dcd`
