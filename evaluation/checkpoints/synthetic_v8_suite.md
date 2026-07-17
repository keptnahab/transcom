# Synthetic v8 closed-command suite

## QA decision

**Formal QA GO for Dev benchmarks only. v8 holdout ASR is forbidden until a
candidate is frozen from Dev, Human, Degraded, latency, and regression evidence.**

The complete closed safety-command phrase catalog was versioned and hashed
before either v8 specification, all v8 audio, and every v8 ASR run. This suite
was generated and selected without ASR, model loading, or hypothesis inspection.
The v8 holdout was immediately sealed and remains unopened by ASR.

## Frozen protocol

- Catalog: `evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json`
  (SHA-256
  `70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190`).
- Schema v1 root: `catalog_id`, `mode`, `language`, `commands`,
  `evaluation_policy`, `split_policy`, and `freeze_policy`.
- The catalog contains eight unique commands and eight complete allowed
  phrases. `mode=closed_command` and `selection_uses_asr_output=false`.
- Dev and holdout realize the same command IDs, intents, and phrases. Their
  utterance IDs, speakers, voices, rates, and every audio-artifact hash are
  disjoint.
- Every safety clip and stream turn contains its `expected_command_id`.
- Four short alphanumeric, three medium, and three long open-dictation items per
  split remain text-disjoint and are evaluated separately from the eight closed
  safety commands.
- Human / Synthetic / Degraded grouping remains unchanged and is hash-bound in
  `evaluation/data/manifests/evaluation_v8_groups_v1.json` (SHA-256
  `77c6a82fb54c77ad2988266b9b06a6afc2131cf418c587549199c39c866ef805`).

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| Closed-command catalog | `70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190` |
| `evaluation/synthesis_v2/specs/dev_v8.json` | `d266928c2871bd0666c170b7791f2521250de0998df210aef45259e26044bbfe` |
| `evaluation/synthesis_v2/specs/holdout_v8.json` | `c191ad65802d03c7bc8e8529c55b5f5bae7b2aaf56a1b44585229329ebfff3e0` |
| Dev build manifest | `c026563eda49291418d908961af39e4a247f368bb68bd3d3b9dd5150f9c53ac8` |
| Holdout build manifest | `221935fbc7308cbefd57110bcdff4bb82c242df2f8ba773a213a0f94adad7f84` |
| Holdout seal | `b52324d43b0bdab34413e60a80941f1b59c80e105ebedb51aec7e1649ac686a1` |
| Dev combined clean audio | `34a3b6a505b73ea6d46efae07a8458d207ce2c8799856a39fc9240fa32e2751f` |
| Dev combined intercom audio | `bb56c7518ac45765572f732de3e44e9431aef0012f3ddbafaa9083519cb06962` |
| Holdout combined clean audio | `f2b4390058b264e6586070bc0f35fddb3e1d8a1de7bb71ebea1f9a3c31c8fd75` |
| Holdout combined intercom audio | `c0c850aa16b606f9e24c8c879b70601beddd70022d0753617141195feb5d70c4` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v8_dev_clean_v1.json` | `4c36bbe1f3ee569b32d3a5a20dece5a751e1957a7682a5dbc1682e5a4dcd3c97` |
| `synthetic_v8_dev_intercom_v1.json` | `df95603bfd55c9987702b6970dd86cc15b8a60d1d483a87fc24a8fa552d14562` |
| `synthetic_v8_dev_intercom_stream_v1.json` | `22790a823070a22535eb5d38bf0478ad97f45fdce08db59994db51c58189b805` |
| `synthetic_v8_short_latency_dev_v1.json` | `fdf5b9dfeea9866b98c7abc4807d454ca777588872dbe4c25e09c23b53dffae9` |
| `synthetic_v8_holdout_clean_v1.json` | `bd74ef42d5bdf673002f8293795c5670195dcffb3dc1c9e96c1bfc6f92b954f2` |
| `synthetic_v8_holdout_intercom_v1.json` | `4190b2b3c284ee31945fcd571314bd187d15048da75c5ba8421dd10bc645938c` |
| `synthetic_v8_holdout_intercom_stream_v1.json` | `ea571d0e283b7f7f0fd6929433c867538411f04a566b2687b21a3491354c8f99` |
| `synthetic_v8_short_latency_holdout_v1.json` | `7b935d54f3ebf872f0405cd2ef2f526d5b4cb1b7ec5b66fda2ee40a34214962a` |

## Objective QA

- Build verification and immutable holdout-seal verification passed.
- 72 per-utterance clean/intercom WAVs are mono 16 kHz PCM16, finite,
  non-empty, sample-count-identical between variants, and unclipped.
- Peak range: -12.1414 to -0.3898 dBFS. RMS range: -29.0244 to -17.0842
  dBFS. Utterance duration range: 1.06 to 6.46 seconds.
- Every combined inter-turn gap is exactly 10,400 frames of digital silence and
  every clean ending passes the active-final-frame trim check.
- Longest internal exact-zero run: 0.136313 seconds. Longest internal sub--50
  dBFS frame run: 0.23 seconds. These stay below the guards for the chopped-TTS
  failure mode.
- Clip, stream, Short-Latency, group, catalog, isolation, audio, and seal
  bindings passed. Auxiliary manifest regeneration was byte-identical.
- Suite-only selection: 36 passed. With the closed-command benchmark,
  acceptance, and safety-command tests included, the final relevant selection
  is 49 passed. The only warning is the pre-existing urllib3/LibreSSL
  environment warning.

## Dev benchmark commands

These commands are authorized for Dev only and have not been run while creating
the suite:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_clip_suite.py \
evaluation/data/manifests/synthetic_v8_dev_clean_v1.json --language de \
--output evaluation/results/v8_dev_clean.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_clip_suite.py \
evaluation/data/manifests/synthetic_v8_dev_intercom_v1.json --language de \
--output evaluation/results/v8_dev_intercom.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python scripts/benchmark_live_pipeline.py \
evaluation/generated/synthetic_v2/dev/synthetic_de_v8-dev-001/audio/intercom.wav \
--warmup \
--reference-manifest evaluation/data/manifests/synthetic_v8_dev_intercom_stream_v1.json \
--db /tmp/transcom-v8-dev.db \
--output evaluation/results/v8_dev_live_pipeline.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_streaming_latency.py \
evaluation/data/manifests/synthetic_v8_short_latency_dev_v1.json --language de \
--output evaluation/results/v8_dev_short_latency.json
```

The primary closed-safety result is command-ID exact accuracy; normalized phrase
exactness, WER, CER, latency, raw hypothesis, and open-dictation groups remain
separately auditable. Do not execute any v8 holdout command before candidate
freeze.
