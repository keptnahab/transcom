# TODO

|Status|Priority|Task|
|---|---|---|
|open|P0|Fix live transcript grouping so phrases are merged into coherent utterances instead of many tiny word fragments|
|open|P0|Stabilize speaker matching and prevent arbitrary auto-speaker proliferation such as `Speaker 4/5/6` for the same person|
|open|P0|Eliminate the remaining initial duplicate row at the beginning of a live transcript|
|open|P0|Enforce German/English-only recognition behavior consistently in real runtime output|
|open|P0|Re-run the live benchmark after transcript/speaker fixes and capture fresh latency and quality metrics|
|open|P1|Investigate and fix the MLX / Metal crash during `scripts/benchmark_live_pipeline.py --warmup` on this machine|
|open|P1|Add utterance-level update logic so the backend can update an in-progress segment instead of inserting a new row for every stabilized chunk|
|open|P1|Tighten speaker matching windowing and confidence rules, especially for short accepted word windows|
|open|P1|Decide whether auto-speaker creation should be delayed, smoothed, or disabled for low-confidence snippets|
|open|P1|Validate real beta web flow end-to-end with login, websocket auth state, transcript stream, and user admin UI|
|done|P1|Implement beta-user auth with email login and generated passwords|
|done|P1|Allow admin to view, edit, and regenerate user passwords|
|done|P1|Push current codebase to GitHub on `origin/main`|
|done|P2|Document project history, decisions, setup, and status in `BASE`|
