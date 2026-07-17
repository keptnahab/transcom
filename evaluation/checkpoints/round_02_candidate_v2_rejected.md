# Round 02 checkpoint — candidate v2 rejected

Date: 2026-07-13

## Completed

- Preserved candidate v1 as a failed historical candidate after its v3 short-command/token-loop holdout failure.
- Added deterministic MLX decoding and a general transcript-pathology guard with a separately pinned faster-whisper-small fallback.
- Verified the guard on the already-burned v3 diagnostic split: catastrophic WER 2.8367 became 0.1939; the remaining errors were ordinary recognition errors, not token loops.
- Built a disjoint synthetic v4 Dev/Holdout suite. The v4 holdout was sealed before ASR and had zero exact text overlap with v3 or v4 Dev.
- Selected 500 ms VAD pre-roll on Dev only. On v4 Dev live audio, WER improved 0.2206 → 0.1912 and CER 0.1567 → 0.1198 with unchanged jobs/duplicate count and essentially unchanged RTF.
- Froze candidate v2 before any v4 holdout ASR: `evaluation/CANDIDATE_V2.json`, SHA-256 `8d907dcef74bf21abb2b5a79e8cb39223b07c51d399543b20c1743262c18f262`.
- Opened the v4 holdout only after the freeze and ran Base versus candidate v2.

## Holdout result

| v4 synthetic group | Base WER | v2 WER | Relative WER reduction | Base CER | v2 CER | Gate |
|---|---:|---:|---:|---:|---:|---|
| Clean | 0.7250 | 0.3250 | 55.17% | 0.2778 | 0.1508 | FAIL absolute ≤0.20/≤0.12 |
| Intercom | 0.6625 | 0.3000 | 54.72% | 0.2698 | 0.1468 | FAIL absolute ≤0.20/≤0.12 |

Candidate v2 is rejected despite the large relative improvement. It must not be modified or re-labelled as passing.

## Failure analysis

- Long v4 Intercom clips were mostly 0.11–0.20 WER.
- Short clips dominated the failure (short-group WER 0.625).
- The domain prompt contaminated one short safety result with its literal word `Fachbegriffe`.
- Removing the prompt on the burned v4 diagnostic split improved aggregate WER/CER from 0.3000/0.1468 to 0.2625/0.1151, but still failed the raw-WER gate.
- Number/alphanumeric formatting explains part, not all, of the residual raw WER. Meaning errors remain in short artificial voices.

## Open work / next step

1. Generate and seal a new disjoint v5 holdout; run no ASR on it before candidate v3 is frozen.
2. On Dev and already-burned v4 diagnostics only, test a pinned full Whisper-large-v3 4-bit MLX model and short-audio prompt suppression.
3. Recheck human and degraded Dev, latency, RTF, and live VAD before freezing candidate v3.
4. Run the v5 holdout exactly once for initial acceptance, followed only by reproducibility repeats if it passes.

## Reproduce the decisive v2 results

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 backend/.venv/bin/python evaluation/benchmark_clip_suite.py evaluation/data/manifests/synthetic_v4_holdout_clean_v1.json --language de --output evaluation/results/holdout_candidate_v2_synthetic_v4_clean_20260713.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 backend/.venv/bin/python evaluation/benchmark_clip_suite.py evaluation/data/manifests/synthetic_v4_holdout_intercom_v1.json --language de --output evaluation/results/holdout_candidate_v2_synthetic_v4_intercom_20260713.json
```
