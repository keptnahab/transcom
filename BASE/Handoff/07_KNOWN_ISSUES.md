# Known Issues

1. Live transcript grouping is still too granular.
The current timed stabilizer can emit fragments that are stored as separate rows, producing many short lines instead of a coherent utterance.

2. Speaker recognition is not production-stable yet.
Real-user tests showed cases where one real speaker became `Speaker 4`, `Speaker 5`, `Speaker 6`, or remained `Unknown`.

3. Initial duplicate transcript rows can still appear.
Store-level duplicate suppression helps, but has not fully eliminated the issue in real runs.

4. Unsupported-language drift still occurs in practice.
The product intent is German and English only, but live output has still shown other languages according to user testing.

5. Benchmarking on this machine is currently unreliable with the default MLX path.
`backend/.venv/bin/python scripts/benchmark_live_pipeline.py --warmup` crashed on 2026-07-01 with a Metal / MLX exception:
- `NSRangeException`
- stack in `libmlx.dylib`
- likely environment/runtime/device selection issue

6. Password visibility is a deliberate beta compromise.
`backend/auth/service.py` stores `visible_password` so the admin UI can show and edit tester passwords. This is useful for beta ops but not suitable for hardened production security.

7. Older existing users may have no recoverable visible password.
If a user existed before `visible_password` was introduced, their plaintext password cannot be reconstructed. Admin must set or generate a new one.
