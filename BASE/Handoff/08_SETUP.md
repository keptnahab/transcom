# Setup

## Repo
- Root after MacBook/Dropbox move: `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom`
- Old root before move: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- MacBook continuation notes: `BASE/Handoff/09_MACBOOK.md`

## Install
- Run: `./scripts/setup.sh`

What setup does:
- creates `backend/.venv`
- installs Python dependencies
- installs Node dependencies
- installs `portaudio` via Homebrew if needed
- downloads all three release models at immutable commit revisions
- immediately verifies all three snapshots from the local cache with network
  access disabled

Pinned hybrid model matrix:

| Runtime role | Repository | Commit revision |
| --- | --- | --- |
| MLX Full for original audio longer than 3.0 s | `mlx-community/whisper-large-v3-mlx-4bit` | `d12b5d0043a6fe0c59af321617fba041d4e8e0c8` |
| MLX Turbo for original audio up to and including 3.0 s | `mlx-community/whisper-large-v3-turbo-q4` | `660c343bbf4e52ac257f0b7d952e5388e6f93bef` |
| faster-whisper Small for guarded fallback and Safety confirmation | `Systran/faster-whisper-small` | `536b0662742c02347bc0e980a01041f333bce120` |

`scripts/setup.sh` is the intended networked model-install step. Runtime model
resolution uses `local_files_only=True`; normal transcription must not download
models implicitly.

Offline model check after setup:

```bash
HF_HUB_OFFLINE=1 backend/.venv/bin/python scripts/download_models.py --verify-only
```

This command fails if any snapshot is missing, empty, or resolves to a directory
other than the pinned commit SHA. It does not access the network.

## Run

Renderer only:
```bash
npm run dev:renderer
```

Backend only:
```bash
PYTHONUNBUFFERED=1 PYTHONPATH="$PWD" backend/.venv/bin/python backend/main.py
```

Local browser testing without login:
```bash
TRANSCOM_WEB_PORT=8081 TRANSCOM_AUTH_DISABLED=1 backend/.venv/bin/python backend/main.py
```

Safety-command mode (closed, bundled German command catalog):
```bash
TRANSCOM_SAFETY_COMMAND_MODE=1 backend/.venv/bin/python backend/main.py
```

Safety Mode is disabled by default (`TRANSCOM_SAFETY_COMMAND_MODE=0`). It must
be enabled explicitly with the command above. When enabled, an eligible Turbo
near-match can be independently confirmed by the pinned faster-whisper Small
model; exact allow-list matches do not require that second pass.

This mode only proposes a catalog command for utterances up to three seconds.
Every proposal requires an explicit operator confirmation; it never executes a
machine action. The UI and exports retain the raw model text, match evidence,
catalog identity, confirming user, timestamp, and append-only confirmation
event. Negations, extra words, opposite actions, and ambiguous/low-score text
remain unresolved instead of being rewritten as a command.

Electron dev:
```bash
npm run dev
```

## Typical local test URLs
- Vite UI: `http://localhost:5747/`
- Backend API when overridden: `http://127.0.0.1:8081/`
- LAN viewer default port: `8787`

## Tests

Unit/integration:
```bash
backend/.venv/bin/python -m pytest
```

Current benchmark reference:
```bash
TRANSCOM_ASR_BACKEND=faster-whisper backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup
```

## Important environment variables
- `TRANSCOM_ASR_BACKEND`
- `TRANSCOM_MODEL` default: `Systran/faster-whisper-small`
- `TRANSCOM_MLX_MODEL` default: `mlx-community/whisper-large-v3-mlx-4bit`
- `TRANSCOM_MLX_SHORT_MODEL` default: `mlx-community/whisper-large-v3-turbo-q4`
- `TRANSCOM_CHUNK_SECONDS` default on the Apple-Silicon MLX path: `0.15`
- `TRANSCOM_CPU_THREADS` default: `12`
- `TRANSCOM_ASR_EDGE_PADDING` default: `0.35`
- `TRANSCOM_ASR_EDGE_PADDING_MAX` default: `3.0`
- `TRANSCOM_LANG` default: `de`
- `TRANSCOM_ALLOWED_LANGS` default: `de,en`
- `TRANSCOM_DEFAULT_LANG` default: `de`
- `TRANSCOM_VAD_MIN_SPEECH`
- `TRANSCOM_VAD_MIN_SILENCE`
- `TRANSCOM_VAD_MAX_SEGMENT`
- `TRANSCOM_VAD_PRE_ROLL` default: `0.65`
- `TRANSCOM_SAFETY_COMMAND_MODE` default: `0`
- `TRANSCOM_SAFETY_COMMAND_CATALOG`
- `TRANSCOM_SAFETY_COMMAND_MIN_SCORE` default: `0.82`
- `TRANSCOM_SAFETY_COMMAND_MIN_MARGIN` default: `0.04`
- `TRANSCOM_AUTH_DISABLED`
- `TRANSCOM_WEB_PORT`

## Hybrid routing details

- Routing uses original, unpadded utterance duration: Turbo at `<= 3.0 s`, Full
  at `> 3.0 s`.
- For inputs up to 3.0 s, edge normalization supplies exactly 0.35 s of missing
  quiet context at either edge. This padding does not turn a short utterance
  into a Full-model request and timestamps are mapped back afterward.
- The MLX live path defaults to 0.15-s capture chunks.
- faster-whisper Small uses 12 CPU threads when used as a guarded fallback or
  explicit Safety confirmation.
- Safety Mode remains off unless `TRANSCOM_SAFETY_COMMAND_MODE=1` is explicitly
  present in the launch environment.

## Current setup verification on 2026-07-13

- Strict offline cache verification passed for all three exact repository/commit
  pairs.
- `bash -n scripts/setup.sh` passed.
- Downloader and hybrid-engine tests: `30 passed, 1 warning`.
- Full Python suite: `203 passed, 3 warnings`.
- No model download was run during this verification; only
  `scripts/download_models.py --verify-only` accessed the existing cache.

## Last verified on 2026-07-04
- `backend/.venv/bin/python -m pytest`: `52 passed, 1 warning`
- `npm run build`: passed
- Release test package created:
  - `release/TransCom_Beta_Testpaket_2026-07-03_FINAL.zip`
  - SHA256: `ac087aac266896a9c988685c83326a8265a13c81fa87f09c7f0ec8b4e76c9fd7`
- Current `faster-whisper` benchmark reference:
  - WER `0.2667`
  - first emit `3.54s`
  - avg infer `0.52s`

## Practical testing notes
- File/demo WAV mode is now selectable in the UI again.
- File/demo WAV mode has browser audio monitoring via `/api/audio-file`.
- The UI shows native browser audio controls in file mode so playback can be started manually if autoplay is blocked.
- If the next chat is about quality, start from the `faster-whisper` benchmark path and then verify in the real browser UI.
