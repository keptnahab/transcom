# Progress Log

## 2026-07-04

- Prepared the project for six weeks of MacBook-only work.
- Added `BASE/Handoff/09_MACBOOK.md` with the new Dropbox path, quickstart commands, package location, verification status, and next priorities.
- Updated the handoff index and setup notes so a fresh chat starts from the MacBook/Dropbox location.
- Current intended moved project folder:
  - `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom`
- Current intended main repo after move:
  - `/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom`
- Created the beta test package:
  - `release/TransCom_Beta_Testpaket_2026-07-03_FINAL.zip`
  - SHA256: `ac087aac266896a9c988685c83326a8265a13c81fa87f09c7f0ec8b4e76c9fd7`
- Verified the package-related code state:
  - `backend/.venv/bin/python -m pytest`
  - result: `52 passed, 1 warning`
  - `npm run build`
  - result: passed

## 2026-07-01

- Confirmed the real repo location and Git remote.
- Added and updated the persistent `BASE` handoff structure.
- Implemented the local pipeline changes around VAD wiring, language fallback, worker metadata, and benchmark reporting.
- Updated the frontend so file/demo audio mode remains visible and usable instead of snapping back to live mode.
- Added local auth-bypass behavior for browser testing with `TRANSCOM_AUTH_DISABLED=1`.
- Verified the current automated suite:
  - `backend/.venv/bin/python -m pytest`
  - result: `51 passed, 1 warning`
- Re-ran the fixture benchmark on the `faster-whisper` path:
  - WER: `0.2667`
  - first emit: `3.54s`
  - avg infer: `0.52s`
  - only `de/en` languages used
- Aligned the normal app defaults with the verified benchmark path:
  - default ASR backend is now `faster-whisper`, with `mlx` still available via `TRANSCOM_ASR_BACKEND=mlx`
  - beta launcher default language is now `auto` instead of German-only
  - faster-whisper word timestamps now feed the timed stabilizer path
- Added a targeted transcript-pane replacement path so backend replacement broadcasts update an existing row instead of appending a duplicate row.
- Verified the updated automated suite:
  - `backend/.venv/bin/python -m pytest`
  - result: `52 passed, 1 warning`
- Re-ran the default fixture benchmark:
  - WER: `0.2667`
  - first emit: `3.59s`
  - avg infer: `0.56s`
  - only `de/en` languages used
- Tested tuning alternatives:
  - smaller chunks and lower VAD silence did not improve first emit and increased fragmentation
  - beam size `3`/`5` improved WER to `0.2500`/`0.2167`, but increased first emit
  - `Systran/faster-whisper-small` improved WER to `0.1667`, but first emit rose to about `5s`
  - `Systran/faster-distil-whisper-large-v3` was stopped after taking too long for a fast local default
- Added browser audio monitoring for demo/file mode:
  - backend serves selected local audio via authenticated `/api/audio-file`
  - range requests return `206 Partial Content` for browser audio playback
  - frontend starts monitoring audio when `Start Feed` is pressed in file mode and stops it with feed stop/no active feed
  - file mode also shows native browser audio controls so playback can be started manually if browser autoplay is blocked
  - direct range check returned WAV bytes from the demo file

Observed from real UI testing on the same day:
- Demo WAV control is back and usable.
- File mode playback monitoring has been added and started successfully in the browser without playback warnings.
- Recognition is still judged too weak and too slow.
- The duplicate first transcript line has a targeted UI fix but still needs a fresh run against the updated backend.
- The session/feed interaction is still confusing.

Interpretation:
- The codebase improved materially.
- The user-facing quality problem is still unresolved.
