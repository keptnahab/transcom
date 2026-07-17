# Round 01 checkpoint: inventory, valid baseline, and frozen targets

Date: 2026-07-13  
Status: complete; product optimisation is not complete.

## Completed work

- Preserved the two original synthetic WAV variants as immutable, hash-bound raw data.
- Rejected the repository's previous benchmark result because its embedded four-turn reference did not match the overwritten 30-turn fixture.
- Added hash-bound manifests, WER/CER edit counts, latency percentiles, real-time factor, transcript capture, and JSON output to the live-pipeline benchmark.
- Added an oracle-turn benchmark to separate ASR/model errors from streaming/VAD segmentation errors.
- Removed the ineffective capture overlap after tests proved that the VAD input had been delayed by 0.75 seconds while the overlap was discarded before transcription.
- Added a deterministic human FLEURS development subset (12 official dev clips) and a clip-suite benchmark.
- Froze release targets in `evaluation/TARGETS_V1.md` before product optimisation.
- Generated separate, versioned synthetic v2 development and sealed holdout suites. The legacy/raw fixtures were not modified.

## Measured baseline

All error rates below are fractions; 0.20 means 20%.

| Suite / mode | WER | CER | first simulated emit | RTF | Notes |
|---|---:|---:|---:|---:|---|
| Historical four-turn fixture, corrected reference | 0.2333 | 0.1438 | 5.818 s | 0.1198 | Current worktree before capture fix |
| Current 30-turn synthetic fixture, corrected reference | 0.4368 | 0.2433 | 5.801 s | 0.1640 | 56 VAD/ASR jobs for 30 scripted turns |
| Current 30-turn fixture, oracle turn boundaries | 0.2483 | 0.1163 | n/a | 0.0944 | Direct ASR, no VAD/ring/stabiliser |
| Human FLEURS development clips, direct base model | 0.1518 | 0.0439 | n/a | 0.0638 | Official read-speech references; all selected dev labels are MALE |

The gap between the streaming baseline WER (0.4368) and oracle-turn WER (0.2483) is 0.1885 absolute. This is direct evidence that segmentation and per-segment language handling contribute substantially in addition to model and test-audio errors.

## One-factor experiments

| Change | WER | CER | first simulated emit | Decision |
|---|---:|---:|---:|---|
| Capture overlap removed; historical fixture | 0.2333 | 0.1438 | 5.080 s | Accept: same transcript accuracy, 0.738 s lower simulated delay |
| Fixed German; current all-German synthetic dev fixture | 0.3793 | 0.2194 | 4.795 s | Evidence for language-ID errors; do not apply globally to mixed-language channels |
| VAD max segment 8 s, auto language | 0.3701 | 0.2105 | 8.006 s | Reject as default: accuracy gain with unacceptable latency/turn merging |
| VAD max segment 5 s, auto language | 0.4092 | 0.2386 | 6.671 s | Reject as default: small gain and worse latency/turn merging |

## Current causal assessment

1. **Test-data/reference defect:** the active fixture and old embedded reference described different recordings, invalidating the old headline WER. The active macOS TTS fixture also contains excessive exact silence and generator-plus-voice end pauses, creating an unnaturally chopped rhythm.
2. **Segmentation defect:** the 2.5-second VAD ceiling splits 30 scripted turns into 56 ASR jobs. Oracle boundaries recover 18.85 absolute WER points.
3. **Language decision defect:** short German fragments are sometimes classified as English. Fixed German improves the all-German development fixture, but is not safe as a universal setting.
4. **Model limitation:** even with oracle turn boundaries, the base model remains at 0.2483 WER on the synthetic intercom script and fails several very short commands.
5. **Audio format:** the active fixture is already mono PCM16 at 16 kHz, has no clipped samples, and has adequate peak/RMS level. Resampling, channel count, or clipping are therefore not the primary cause for this fixture.

## Open work

- Complete the `small` model comparison on development suites and record the exact model revision.
- Evaluate the new naturalised synthetic v2 development suite without touching its sealed holdout.
- Add deterministic degraded development/holdout derivatives without changing source files or split membership.
- Implement a segmentation strategy that preserves utterance context without the latency regression of a larger VAD maximum.
- Add fixed, predeclared normalization for numbers, dates, timecodes, and abbreviations while retaining raw WER/CER.
- Promote one final candidate, then open the synthetic and human holdouts exactly once for release acceptance.
- Run three warm repetitions, all automated tests, renderer build, and an end-to-end scenario review.

## Exact continuation commands

Run from the repository root.

```bash
PYTHONPYCACHEPREFIX=/tmp/transcom-pycache backend/.venv/bin/python -m pytest -q
npm --prefix renderer run build
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 backend/.venv/bin/python evaluation/benchmark_clip_suite.py evaluation/data/manifests/fleurs_de_dev_v1.json --output evaluation/results/baseline_human_fleurs_de_dev_base_auto_20260713.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 backend/.venv/bin/python evaluation/benchmark_oracle_segments.py evaluation/data/manifests/macos_say_intercom_30turn_v1.json --output evaluation/results/oracle_turns_auto_worktree_synthetic_20260713.json
backend/.venv/bin/python evaluation/synthesis_v2/generate.py verify evaluation/generated/synthetic_v2/dev/synthetic_de_v2-dev-001
backend/.venv/bin/python evaluation/synthesis_v2/generate.py verify evaluation/generated/synthetic_v2/holdout/synthetic_de_v2-holdout-001
```

Measured JSON reports are under `evaluation/results/`. No holdout ASR output exists at this checkpoint.
