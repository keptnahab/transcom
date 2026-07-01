# Project Status

Goal:
- Deliver a very good local-first TransCom beta for intercom / production audio with strong German and English transcription, practical low-latency live output, useful speaker recognition, operator correction workflow, and network-accessible beta login for testers.

Progress:
- Core app exists and runs.
- Renderer build is working.
- Backend tests currently pass.
- Authentication and beta-user management are implemented, including admin bootstrap, user creation, login, delete, and visible/editable passwords.
- Session, transcript storage, LAN viewer, audio source selection, speaker check-in UI, and live transcription pipeline are present.
- Sherpa-based VAD / speaker embedding integration path exists, with fallback logic when models are missing or unavailable.
- Real quality issues remain in speaker assignment, segmentation granularity, duplicate suppression, and language discipline.

Milestone:
- Milestone reached: first pushed beta codebase on GitHub (`8ea2dcd` on `main`).
- Current phase: stabilization and quality improvement, not greenfield development.

Verified on 2026-07-01:
- `backend/.venv/bin/python -m pytest` -> `43 passed, 1 warning`
- `npm run build:renderer` -> success
- `backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup` -> failed with MLX / Metal crash (`NSRangeException` in `libmlx.dylib`), so benchmark status is currently red on this machine/runtime
