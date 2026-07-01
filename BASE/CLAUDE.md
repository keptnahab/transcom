# CLAUDE.md

# TransCom project rules

Always start by reading:
1. `BASE/Handoff/HANDOFF.md`
2. `BASE/Handoff/00_PROJECT_STATUS.md`
3. `BASE/Handoff/02_TODO.md`
4. `BASE/Handoff/06_SESSION_SUMMARY.md`
5. `BASE/Handoff/07_KNOWN_ISSUES.md`

Project intent:
- `TransCom` is a local-first transcription tool for intercom / production audio.
- Primary target is very good German and English live transcription with practical operator UX.
- Speaker recognition must become reliable enough for real beta use.
- Target latency remains about 1-2 seconds where feasible.
- Beta access is intended over the network with lightweight user management.

Documentation rules:
- Never keep important knowledge only in chat.
- After meaningful work, update the relevant files in `BASE/Handoff/`.
- Record facts, not hopes. If something is broken, document it as broken.
- Keep decisions, risks, test status, and next steps synchronized.

Engineering rules:
- Prefer improving existing code over duplicate implementations.
- Before implementing: inspect -> reason -> implement -> test -> document.
- Preserve local-first design unless the user explicitly changes direction.
- No hardcoded secrets in code or docs.
- Record temporary workarounds and why they exist.

Current repository facts:
- Local path: `/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom`
- Git remote: `https://github.com/keptnahab/transcom.git`
- Branch: `main`
- First pushed commit: `8ea2dcd`
