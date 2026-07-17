# TransCom Base Memory

`BASE/` is the persistent handoff folder for this repo. It should always describe the real state of the project, not the hoped-for state.

Use this folder when opening a new chat window or resuming work after context loss.

Current reality as of 2026-07-01:
- The app runs locally as Electron or as a web beta UI.
- Local auth-bypass test mode exists and is useful for UI iteration.
- Demo WAV selection in the UI works again.
- The ASR pipeline is improved versus the older `base + auto` baseline on the fixture benchmark.
- The product is still not good enough in real use: recognition is too weak, first output is too slow, and the first duplicate row still appears.
- File-feed playback is processed by the backend, but there is currently no audible monitoring path in the UI.

Current ASR runtime facts as of 2026-07-13:
- Apple Silicon uses pinned MLX Turbo for original audio up to 3.0 seconds and
  pinned MLX Full for longer audio.
- Pinned faster-whisper Small is the guarded fallback and optional Safety
  confirmation model; its CPU-thread default is 12.
- The MLX capture chunk default is 0.15 seconds. Eligible short inputs receive
  0.35 seconds of missing quiet edge context without changing duration routing.
- Safety Mode is off by default and requires explicit activation.
- `scripts/setup.sh` installs all three snapshots and verifies them offline.

Recommended reading order for a fresh coding session:
1. `BASE/CLAUDE.md`
2. `BASE/CLAUDE.local.md`
3. `BASE/Handoff/HANDOFF.md`
4. `BASE/Handoff/00_PROJECT_STATUS.md`
5. `BASE/Handoff/02_TODO.md`
6. `BASE/Handoff/06_SESSION_SUMMARY.md`
7. `BASE/Handoff/07_KNOWN_ISSUES.md`

Project facts:
- Repo: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Remote: `https://github.com/keptnahab/transcom.git`
- Branch: `main`

Maintenance rule:
- After meaningful implementation, verification, or product-direction changes, update the relevant `BASE` files in the same work session.
