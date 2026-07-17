# CLAUDE.md

# TransCom working rules

Always read first:
1. `BASE/Handoff/HANDOFF.md`
2. `BASE/Handoff/00_PROJECT_STATUS.md`
3. `BASE/Handoff/02_TODO.md`
4. `BASE/Handoff/06_SESSION_SUMMARY.md`
5. `BASE/Handoff/07_KNOWN_ISSUES.md`

Project intent:
- `TransCom` is a local-first transcription tool for mixed intercom / production audio.
- The practical target is strong German/English live transcription, low enough latency for operators, and usable speaker attribution.
- No cloud transcription or GPT clean-up path is part of the intended first product.

Current product truth:
- The app is feature-rich enough to run end to end.
- The core quality problem is not solved yet.
- Real user feedback on 2026-07-01 is still negative on recognition quality, latency, and duplicate opening lines.

Documentation rules:
- Do not keep critical state only in chat.
- Record facts, measurements, and observed failures.
- If a feature works only partially, document both the win and the limit.
- Keep `BASE/Handoff/02_TODO.md`, `06_SESSION_SUMMARY.md`, and `07_KNOWN_ISSUES.md` synchronized.

Engineering rules:
- Inspect before changing.
- Prefer targeted fixes over broad rewrites.
- Preserve the local/offline design unless the user explicitly changes the product direction.
- Keep the benchmark and real UI behavior separate in your reasoning: fixture gains do not prove real usability.
- When quality work is discussed, verify both with tests and with the fixture benchmark.

Important repo facts:
- Local path: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Remote: `https://github.com/keptnahab/transcom.git`
- Branch: `main`

Immediate priorities:
1. Improve real ASR quality and responsiveness.
2. Eliminate the duplicate first transcript row.
3. Reduce session/feed UX confusion.
4. Keep the handoff files trustworthy.
