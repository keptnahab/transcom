# Decisions
|Date|Decision|Reason|
|---|---|---|
|2026-07-01|Keep TransCom local-first and offline-oriented by default|The product is about sensitive live intercom audio; local operation is a core expectation|
|2026-07-01|Use a Python backend plus Electron/Vite frontend|This split fits audio/ML work on the backend and keeps the operator UI flexible|
|2026-07-01|Support a lightweight beta web app in parallel to Electron|The user wants external beta testers to access the app over the network without full packaging first|
|2026-07-01|Default to `mlx-whisper` on macOS arm64, otherwise `faster-whisper`|Apple Silicon should have a faster local path, while keeping a more portable fallback|
|2026-07-01|Prepare sherpa-onnx integration for VAD and speaker embedding|Speaker recognition must be real local inference, not only heuristic placeholders|
|2026-07-01|Keep a fallback speaker path when sherpa models are missing|Development and UI workflows must remain runnable before model assets are fully in place|
|2026-07-01|Allow only German and English as intended supported languages|This was explicitly requested; other-language output is considered a product bug|
|2026-07-01|Store visible beta-user passwords in the auth DB for admin editing|The user explicitly needs to see and edit passwords for testers; this is acceptable for beta but not hardened production|
|2026-07-01|Do not invalidate all sessions when an admin changes a password|This avoids locking out the current admin during user management operations|
|2026-07-01|Use `BASE/Handoff/*` as mandatory persistent working memory|The user wants future context windows to continue immediately without reconstruction|
