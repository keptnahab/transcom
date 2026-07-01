# CODING local configuration

Project:
- TransCom
- Local-first live transcription and speaker workflow app for intercom / production audio

Build:
- `npm run build:renderer`
- `npm run build`

Run:
- Renderer dev only: `npm run dev:renderer`
- Electron dev: `npm run dev`
- Backend only: `PYTHONUNBUFFERED=1 PYTHONPATH="$PWD" backend/.venv/bin/python backend/main.py`
- Beta web app helper: `./scripts/beta_server.sh`

Test:
- `backend/.venv/bin/python -m pytest`
- `backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup`

Tech Stack:
- Electron
- Vite
- Vanilla JS renderer
- Python backend
- WebSocket transport
- SQLite
- `faster-whisper`
- `mlx-whisper` on Apple Silicon by default
- `sherpa-onnx` for VAD / speaker embedding when models are present
- `sounddevice`, `soundfile`, `numpy`

Special Rules:
- Supported languages are intended to be German and English only.
- Audio should remain local; cloud APIs are not part of the intended product.
- Keep beta-user auth simple but functional.
- Document real runtime URLs, credentials strategy, and operational caveats in `BASE/Handoff/`.
