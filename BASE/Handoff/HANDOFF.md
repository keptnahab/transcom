# HANDOFF

## Current status
TransCom is a working local desktop/web beta app with:
- Python backend
- Vite/Electron UI
- session creation and storage
- live input and file-feed ingestion
- transcript persistence
- speaker check-in workflow
- beta-user auth
- token-gated LAN viewer

The app is runnable, but the core live transcript experience is still below target.

## What improved today
- Demo WAV/file mode is visible and usable again in the UI.
- File-source selection no longer snaps back to live mode on ordinary state refreshes.
- Auth can be disabled for local testing with `TRANSCOM_AUTH_DISABLED=1`.
- The local fixture benchmark improved versus the old `base + auto` baseline.
- Apple Silicon now uses the pinned hybrid MLX path: Turbo for original audio
  `<= 3.0 s`, Full for longer audio, and faster-whisper Small as the independently
  pinned guarded fallback/Safety-confirmation model.
- Beta launcher language now defaults to `auto`, matching the mixed German/English benchmark instead of forcing German.
- Faster-whisper word timestamps are surfaced to the timed stabilizer path.
- Re-broadcast transcript updates now replace existing UI rows instead of appending a duplicate DOM row.
- File/demo mode now has browser audio monitoring when `Start Feed` is pressed, plus visible audio controls in file mode.

## What is still broken enough to matter
- Real recognition quality is still poor.
- First usable output is still too slow for the intended live feel.
- Duplicate first-row handling has a targeted UI fix, but it still needs a fresh real UI run against the updated backend.
- Session vs feed controls are confusing for operators.

## Immediate next steps
1. Focus the next chat on real UI verification of ASR quality, latency, and duplicate-first-line removal.
2. Treat real UI behavior as the release gate, not just the fixture benchmark.
3. Clarify or simplify the session/start/feed UX.
4. Keep `BASE` updated after each meaningful fix.

## Fast resume facts
- New MacBook/Dropbox project root after move:
  `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom`
- Main repo after move:
  `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom`
- Old repo path before move:
  `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- MacBook handoff:
  `BASE/Handoff/09_MACBOOK.md`
- Recommended local test URL: `http://localhost:5747/`
- Backend auth-bypass mode:
  `TRANSCOM_WEB_PORT=8081 TRANSCOM_AUTH_DISABLED=1 backend/.venv/bin/python backend/main.py`
- Hybrid defaults: 0.15-s MLX chunks, 0.35-s edge padding for eligible short
  utterances, and 12 CPU threads for faster-whisper Small.
- Safety Mode is off by default. Enable it explicitly with
  `TRANSCOM_SAFETY_COMMAND_MODE=1`; it never executes a machine action.
- Offline model verification:
  `HF_HUB_OFFLINE=1 backend/.venv/bin/python scripts/download_models.py --verify-only`

## Latest verification
- `backend/.venv/bin/python -m pytest` -> `203 passed, 3 warnings`
- Strict offline verification found all three pinned model snapshots locally.
- `bash -n scripts/setup.sh` -> success
- `npm run build:renderer` -> success
- Browser `/api/audio-file` range request -> `206 Partial Content`, `audio/x-wav`
- `TRANSCOM_ASR_BACKEND=faster-whisper backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup`
  - WER `0.2667`
  - first emit `3.59s`
  - languages only `de/en`

Those numbers are better than before, but still not good enough for the user's live-quality expectation.
