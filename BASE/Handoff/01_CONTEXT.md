# Context

Product context:
- TransCom is meant for live intercom / production communication where operators need near-live transcript visibility from a mixed audio feed.
- The product is intentionally local-first and offline-oriented. Audio should stay on the machine. LAN sharing is acceptable; cloud dependence is not the default direction.
- The user has repeatedly emphasized that speaker recognition quality, low latency, and practical usability matter more than superficial feature completeness.

User expectations established so far:
- German and English only. Other languages should not appear as recognition or translation output.
- Speaker recognition should actually work, not just expose placeholder UI.
- Latency should be around 1-2 seconds when realistically possible.
- Duplicate initial transcript rows are not acceptable.
- Beta testers should be able to access the app over the network.
- Admin must be able to see and edit user passwords from the UI.

Current project location:
- Workspace root: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT`
- Actual git project: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Related sherpa source/reference folder outside repo: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/02 sherpa onnx`

Operating assumptions:
- Main development environment is macOS.
- Apple Silicon is an important target, therefore `mlx-whisper` is the default ASR backend on arm64 macOS.
- Beta operation may use the lightweight web server instead of only Electron.

Important product tension:
- The app already includes auth and network beta access, but the core live-quality experience is still not where the user wants it.
- Documentation must reflect both truths: meaningful progress exists, and the central recognition problem is not solved yet.
