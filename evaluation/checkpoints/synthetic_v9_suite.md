# Synthetic v9 closed-command and negative-OOD suite

## QA decision

**FORMAL QA GO for v9 Dev only. Holdout ASR remains strictly forbidden until a
candidate is frozen from Dev and regression evidence.**

No ASR, model loading, hypothesis inspection, or ASR-based selection occurred
while creating or validating this suite. The holdout was immediately sealed.

## Frozen protocol and composition

- The safety catalog is unchanged from v8:
  `evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json`, SHA-256
  `70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190`.
- Each split contains 24 clips: eight positive closed commands, six short
  out-of-catalog safety negatives, four short alphanumeric open-dictation
  clips, three medium open-dictation clips, and three long open-dictation clips.
- Negative coverage is fixed at two negations, two counter-commands, and two
  acoustic near-misses. Matching case IDs and negative types make the splits
  semantically comparable, while their exact texts are disjoint.
- Every negative carries `safety_negative_ood` and an explicit null
  `expected_command_id` in the parent build and every Clip, Stream, and
  Short-Latency adapter. Positive clips retain their expected command ID.
- IDs, speakers, voices, rates, non-positive texts, and all generated audio
  hashes are split-disjoint. Positive command phrases are intentionally shared
  because they are the complete pre-frozen allow-list.
- Human / Synthetic / Degraded grouping remains unchanged and is hash-bound by
  `evaluation/data/manifests/evaluation_v9_groups_v1.json`, SHA-256
  `414f68fcba76206e3314758beabc869f664afd53b25ffdd7876c09f6157e76e4`.

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| Frozen closed-command catalog | `70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190` |
| `evaluation/synthesis_v2/specs/dev_v9.json` | `139d41b2b681d6192f3e836ab745ea19eeba48ed277bf33cecf8a0223987cde7` |
| `evaluation/synthesis_v2/specs/holdout_v9.json` | `68003965ea3c619bf4ec5853ddea4e43aa4f473eed2af95f4d443719d28a1f69` |
| Dev build manifest | `aa0aad92d3ce8345f9c0920cd5fc8db78da725a83c855ad55af46b0b30aea555` |
| Holdout build manifest | `1278968b6b26b416a4eba2aa598629c0bb53663b2077a9f570916499ae0ccb8e` |
| Holdout seal | `312485b4f4ffc8ab5d82d14ddfc342f2b4235710ff032b4cdf85e269716bfd24` |
| Dev combined clean audio | `94163d872ab3f7db272f4db0c7f614ee9e4079f7c0451f1f1c6a765a71e05172` |
| Dev combined intercom audio | `1dad45d54a2416ab20b941bbc645122d0af1f2ae1518350005815150d5c8c1c0` |
| Holdout combined clean audio | `d822a39d59377f8b27beca0c1ceb8c142c788dcb0e3f2975413cfd50c4c5f67c` |
| Holdout combined intercom audio | `05fae10a0dd9ef39947a8606d5d5d2c56bb3def73e1791890303fd4483250cc6` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v9_dev_clean_v1.json` | `4726ebe0819c4d2b7ce42424ab39859859bab47565b3c86cdd9183ee1920322b` |
| `synthetic_v9_dev_intercom_v1.json` | `7b3976c62f1a2e5c76ab62c6de34a623a8b95cd300321a61233bb15a3802a03a` |
| `synthetic_v9_dev_intercom_stream_v1.json` | `88befc35f2b073d331d73acca2d95a187bdfb68401250ca664b744a25a64c358` |
| `synthetic_v9_short_latency_dev_v1.json` | `6089f324914e5755ad102c98068e6353f64b0cf2b9459dd9330743ba5cb541b0` |
| `synthetic_v9_holdout_clean_v1.json` | `3069cdcbffea4cda5c47c32364d809ba29e3978abafefce74f13d903c470f43a` |
| `synthetic_v9_holdout_intercom_v1.json` | `2bb27da90952aeee39de3c38498b316a5a17d8b2e11ab31d0fffd59d12aa4b83` |
| `synthetic_v9_holdout_intercom_stream_v1.json` | `42345e9ccf0f77e831f539b99e5c6448d9ac7d09a7849cab5f6bbd739c002177` |
| `synthetic_v9_short_latency_holdout_v1.json` | `7c4a9aed307a3d0a26aaf4de57d9447ba1dae56e3ab1ea35a164b7676305a2a7` |

## Objective QA

- Build verification and immutable holdout-seal verification passed.
- 96 per-utterance clean/intercom WAV files are mono 16 kHz PCM16, finite,
  non-empty, sample-count-identical between variants, and unclipped.
- Peak range: -13.6435 to -0.8404 dBFS. RMS range: -29.0481 to -16.7641
  dBFS. Utterance duration range: 1.11 to 6.43 seconds.
- All combined gaps contain exactly 10,400 frames of digital silence. Every
  clean ending passes the active-final-frame trim check.
- Longest internal exact-zero run: 0.142563 seconds. Longest internal sub--50
  dBFS frame run: 0.19 seconds.
- Catalog, negative-null, semantic-pairing, open-text, voice, rate, audio-hash,
  Clip, Stream, Short-Latency, group, and seal tests passed. Re-exporting all
  adapters was byte-identical.
- Final relevant selection: 64 passed. Warnings are limited to the known
  LibreSSL and WebSockets deprecations.

## Authorized Dev-only benchmarks

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_clip_suite.py \
evaluation/data/manifests/synthetic_v9_dev_clean_v1.json --language de \
--output evaluation/results/v9_dev_clean.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_clip_suite.py \
evaluation/data/manifests/synthetic_v9_dev_intercom_v1.json --language de \
--output evaluation/results/v9_dev_intercom.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python scripts/benchmark_live_pipeline.py \
evaluation/generated/synthetic_v2/dev/synthetic_de_v9-dev-001/audio/intercom.wav \
--warmup \
--reference-manifest evaluation/data/manifests/synthetic_v9_dev_intercom_stream_v1.json \
--db /tmp/transcom-v9-dev.db \
--output evaluation/results/v9_dev_live_pipeline.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_streaming_latency.py \
evaluation/data/manifests/synthetic_v9_short_latency_dev_v1.json --language de \
--output evaluation/results/v9_dev_short_latency.json
```

Acceptance must require exact positive command IDs and zero false command
activations on `safety_negative_ood`. Do not run v9 holdout ASR before a formal
candidate freeze.
