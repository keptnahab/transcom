# HANDOFF

## Current status
TransCom exists as a working local/Electron + web beta app with:
- Python backend
- renderer UI
- session management
- audio capture / file feed
- transcription
- transcript persistence
- speaker check-in workflow
- LAN sharing
- beta-user auth with admin login

The project is not finished. It is in an active beta-hardening phase. The biggest unresolved area is production-quality live speaker recognition and transcript grouping quality under real mixed intercom audio.

## Current task
Maintain a fully documented project memory in `BASE`, and continue improving live recognition quality, latency, speaker assignment, and beta-readiness from this documented baseline.

## Next steps
1. Fix transcript segmentation so live output is grouped into sensible utterances instead of many tiny rows.
2. Stabilize speaker matching so one real person does not explode into `Speaker 4/5/6`.
3. Eliminate remaining initial duplicate transcript rows.
4. Enforce German/English-only language behavior in real runs, not just in config intent.
5. Re-run benchmark and live validation after speaker/transcript changes.
6. Keep `BASE/Handoff/*` updated after each meaningful implementation step.

## Risks
- Current MLX benchmark path can crash on some macOS environments with a Metal / MLX device exception.
- Speaker auto-clustering can invent extra speakers.
- Current store-level dedupe is not sufficient to guarantee no duplicate first row in all live cases.
- Password visibility is intentionally stored in plaintext in the auth DB for admin UX; acceptable only for simple beta/testing use, not hardened production.

## Important links
- Local repo: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Git remote: `https://github.com/keptnahab/transcom.git`
- Branch: `main`
- Current pushed commit: `8ea2dcd`
- Existing broad project docs: `DOKUMENTATION.md`
- Earlier sherpa-specific handoff: `HANDOFF_SHERPA_ONNX.md`
