# Context

Product context:
- TransCom is for live intercom / production communication where operators need fast, readable transcript output from one mixed audio feed.
- The product is intentionally local-first and offline-first.
- LAN sharing is acceptable; cloud dependence is not the default direction.

User expectations that are now explicit:
- German and English only. Other-language drift is a product bug.
- The transcript must feel live, not delayed and lumpy.
- The first line must not duplicate.
- Audio-file mode should be straightforward to use for testing.
- The user expects file mode controls to appear when `Audio File` is selected.
- The user expects to understand whether a session must be created, started, and why.

Current user pain from real testing on 2026-07-01:
- File/demo selection is now visible, but the user cannot hear the test audio.
- Recognition quality is still judged very poor.
- Recognition is still too slow.
- The duplicate first row still exists.
- The UI separation between session state and feed state is confusing.

Development constraints:
- No OpenAI/GPT transcript refinement in this phase.
- No cloud ASR fallback in this phase.
- Fix the local pipeline before trying larger product changes.

Operational context:
- Main development machine is macOS on Apple Silicon.
- The runtime default ASR backend on this machine is the pinned MLX hybrid:
  Turbo through 3.0 seconds and Full above 3.0 seconds.
- Pinned faster-whisper Small supplies guarded fallback and, only when Safety
  Mode is explicitly enabled, an independent confirmation pass.
- Safety Mode is off by default.
- For current quality checks, the `faster-whisper` benchmark is the more reliable measurement path.
