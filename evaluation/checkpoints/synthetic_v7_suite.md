# Synthetic v7 catalog-bound safety suite

## Decision

**Dev-only rejected; holdout remains unopened.**

The v7 data build and all objective integrity checks passed, but the first Dev
ASR result was not freeze-worthy: intercom WER was 0.24742 and only 3 of 6
short safety commands were exact. The remaining failures included open-dictation
errors on phonetically similar compounds. No v7 holdout ASR was run and no
holdout hypothesis was inspected. The sealed v7 holdout remains available only
as an unopened build; it is not an acceptance result.

## Protocol and prior-suite status

- v6 is burned diagnostic-only data, documented in
  `evaluation/checkpoints/synthetic_v6_holdout_burned_diagnostic.md` (SHA-256
  `19d14692bc324a7ec3e19d30e2733ddebadc8e933d768f3b8b36e5af0dd263af`).
- v7 was created without ASR, model loading, hypothesis inspection, or selection
  based on recognition output.
- The pre-versioned catalog defines allowed intent identifiers and meanings,
  not phrases: `evaluation/synthesis_v2/catalogs/safety_commands_v1.json`
  (SHA-256
  `9217165522fabb2b8559d7164b96a480085f6c5db3dc5c020dd0c10af3c5cfb8`).
- Dev and holdout contain 16 utterances each and are disjoint in exact phrase,
  speaker, voice, speech rate, and every generated audio-artifact hash.
- The Human / Synthetic / Degraded group structure is preserved and hash-bound
  by `evaluation/data/manifests/evaluation_v7_groups_v1.json` (SHA-256
  `0c424fedc655d9831f603820a7a47bce094a1ad79c9da750a677c13385429087`).

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| `evaluation/synthesis_v2/specs/dev_v7.json` | `17dd40578ec5f4a0c3a1135c09de5206b8bb33f294134519d5ec7169f9417c67` |
| `evaluation/synthesis_v2/specs/holdout_v7.json` | `b56fb0f95e9b5d62310e8f90c1943501bc42f41401f060932c53ad9c27a7f3ac` |
| Dev build manifest | `936a3830713e2a89c2a250519bbcb6df639c076c3e1c100b010b44b3b29ebfa1` |
| Holdout build manifest | `75d6d3ff735ccdc0a9b88bb0be54eec58c0326e3c0210f9f3991b456b225d323` |
| Holdout seal | `7eb812a6e1d71c23e9e2fc184b2ca41fa6db3f34b152ae6921d4ae5eb0cdf84b` |
| Dev combined clean audio | `f80cccc73f4e66e33234a657476a7d58b571482892c98b2c8d7c356d633aa69f` |
| Dev combined intercom audio | `bb649af0f629b944b7e71c5a2d67c0c26f0f27a6e3d2c482ad4944d4c3eb4635` |
| Holdout combined clean audio | `0cbc079a88bfbbdf4f17bcf42658cd6296fe0f4600ed2e3357bd097936f159e4` |
| Holdout combined intercom audio | `c6b6c511d45c9923c0e7baa9a11a9fc4477606dae40bc16549b1ac10ad2bb3fb` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v7_dev_clean_v1.json` | `4561f6c2a175861a147224b557bac19fbca974e0b6d388901ed6930cea14270a` |
| `synthetic_v7_dev_intercom_v1.json` | `2702d31e266f397e756046f367ec8de924d406128d54fc907bc4650f74255749` |
| `synthetic_v7_dev_intercom_stream_v1.json` | `b152e7968962783a10bf1420f0855cdb240b1f3995415da74cab85e641d612c8` |
| `synthetic_v7_short_latency_dev_v1.json` | `24d57be5f0aa9493fab572838312b038650c85ebae39be6f9081b25df6fb21ba` |
| `synthetic_v7_holdout_clean_v1.json` | `8fd067e3b5b4654c402aea3a1a967b37e2a00b1492b272c881118a8df48a1272` |
| `synthetic_v7_holdout_intercom_v1.json` | `feb20d635df49454dbafb06f5801fac9822c2c2b90e16a7554e86bd629b46488` |
| `synthetic_v7_holdout_intercom_stream_v1.json` | `8507e8e8bb007f444665acef23fc805fff783be0237bc187fb2aabab54a4ca58` |
| `synthetic_v7_short_latency_holdout_v1.json` | `f5cf5f4d2e653c80d6f8ee02cfce4072a0bafd6e8db4039ff0366c6496eeebac` |

## Objective QA

- Build and immutable holdout-seal verification passed.
- 64 per-utterance clean/intercom WAVs are mono 16 kHz PCM16, finite,
  non-empty, and sample-count-identical between variants.
- Peak range: -13.2071 to -0.5366 dBFS; RMS range: -29.0149 to -17.5224
  dBFS; maximum clipped-sample fraction: 0.0.
- Utterance duration range: 1.36 to 7.75 seconds.
- Every combined inter-turn gap is exactly 10,400 frames of digital silence.
  Every clean ending passes the active-final-frame trim check.
- The longest internal exact-zero run is 0.169375 seconds and the longest
  internal sub--50 dBFS frame run is 0.19 seconds. No clip has the excessive
  internal silence associated with the previously chopped TTS fixture.
- Clip, stream, Short-Latency, group, catalog, isolation, and seal bindings
  passed. Each split contains six short safety and four short alphanumeric
  clips selected solely from frozen metadata.
- Full relevant test selection: 31 passed. The only warning is the pre-existing
  urllib3/LibreSSL environment warning.

## Reproduction

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q \
  evaluation/synthesis_v2/tests \
  tests/test_synthetic_v2_clip_export.py \
  tests/test_streaming_latency_benchmark.py

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/dev/synthetic_de_v7-dev-001

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/holdout/synthetic_de_v7-holdout-001
```

The next suite must evaluate safety commands as a closed, production-realistic
command mode. Its complete allowed phrase catalog must be frozen before any ASR
run and before holdout generation; open-dictation and alphanumeric groups remain
separate.
