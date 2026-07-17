# Decisions

| Date | Decision | Reason |
| --- | --- | --- |
| 2026-07-01 | Keep TransCom local-first and offline-first | Intercom audio is sensitive and the user explicitly wants the core pipeline local |
| 2026-07-01 | Do not use GPT/OpenAI transcript cleanup in this implementation wave | The user asked for local pipeline fixes first |
| 2026-07-01 | Keep German and English as the only intended recognition languages | The user treats other-language drift as a bug |
| 2026-07-01 | Use sherpa-onnx VAD with fallback instead of raw chunk submission | Non-speech windows were a known quality problem |
| 2026-07-01 | Historical: change `TRANSCOM_MODEL` to `Systran/faster-whisper-base` (superseded by the pinned Small decision below) | The older naked `base` default was not acceptable |
| 2026-07-01 | Keep `TRANSCOM_LANG=auto` with `TRANSCOM_ALLOWED_LANGS=de,en` | Auto detection is useful, but must stay inside supported languages |
| 2026-07-01 | Keep Apple Silicon runtime default backend as `mlx`, but use `faster-whisper` as the current benchmark reference path | The runtime and the most reliable quality measurement path are not identical right now |
| 2026-07-01 | Add `TRANSCOM_AUTH_DISABLED=1` test mode | UI testing should not be blocked by login while iterating locally |
| 2026-07-01 | Persist only final transcript rows in this wave; no new preview event contract yet | The user asked for pipeline correctness before UI contract expansion |
| 2026-07-01 | Keep session controls and feed controls separate for now, but document the confusion as a real issue | The behavior is implemented, but the UX still needs work |
| 2026-07-13 | Supersede the earlier single-model/base defaults with three immutable snapshots: MLX Turbo `<= 3.0 s`, MLX Full `> 3.0 s`, and faster-whisper Small for guarded fallback/Safety confirmation | Duration routing improves short commands without weakening longer transcription, while exact revisions and offline-only runtime resolution make deployment reproducible |
| 2026-07-13 | Keep Safety Mode disabled by default and require `TRANSCOM_SAFETY_COMMAND_MODE=1` | Safety interpretation must be an explicit operator deployment choice and still never executes machine actions |
