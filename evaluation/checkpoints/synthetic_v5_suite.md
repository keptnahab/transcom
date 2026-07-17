# Synthetic v5 theater and technical suite

## Scope and isolation

- Created without loading an ASR model or inspecting any ASR hypothesis.
- Twelve development and twelve separately sealed holdout utterances.
- Four German macOS voices and at least six speech rates per split.
- Both splits cover short, medium, long, safety, alphanumeric, number, and
  technical categories.
- The 24 exact v5 texts are mutually unique, Dev/Holdout-disjoint, and have
  zero exact overlap with every v3 or v4 text.
- Audio follows the established v3/v4 method: mono 16 kHz PCM16, clean and
  intercom variants, 0.65-second / 10,400-frame digital pauses, 10 ms / -50
  dBFS trailing trim, and no added trailing guard.

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| `evaluation/synthesis_v2/specs/dev_v5.json` | `b5d32da0466ccdd63a9ba6852032ac544cdff9a73a4e931f1c6ac99e8874229c` |
| `evaluation/synthesis_v2/specs/holdout_v5.json` | `60ddef0267a36b2f37be25c684f316961f09de2306b8a33aab1ed3feca57b33d` |
| Dev build manifest | `b72836883dcc1c1e49d379a67bb01baf87a9fd69783c14f185303f684b07592b` |
| Holdout build manifest | `22678d9a19262e5dfe3abb7aa8d19ec31b9bcc2b092c63885eed5596ea464746` |
| Holdout seal | `9df81ef912d63d9d0f8880fac71e15a0dcec50fa26051f64852c5ba4da790916` |
| Dev combined clean audio | `c7b022348e76e378e04adff3ec614375dbd47e73379283db7f93c6c0340e3696` |
| Dev combined intercom audio | `beb07fa58f442859c2d6e9a93a2550241c77543e60656af8b02b051454ffb7e6` |
| Holdout combined clean audio | `0a0353a5d4e4ad6cdb295c8c2780886d024e44175c8a7c4f05bffb69f6dc2494` |
| Holdout combined intercom audio | `232576d3dd4a5be00503881208254792942287fcce3381b17cc35f80bb3cbf24` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v5_dev_clean_v1.json` | `12084fb4bc5fecab2a91dfa866eec874e4688c2df5a449d01aaf481e1cea8944` |
| `synthetic_v5_dev_intercom_v1.json` | `e7deeae0ef3cf1acf77c08102a12d96be3097858e32796536362f04c0b4e533c` |
| `synthetic_v5_dev_intercom_stream_v1.json` | `26a3e72601545a950e028ee18de0a69c6de41d21038ea61fd9213355ae9dc122` |
| `synthetic_v5_short_latency_dev_v1.json` | `3fdafb2506e04be04d7faa3bc6da92c5c861d78b5a36c629ce814a77d744cd92` |
| `synthetic_v5_holdout_clean_v1.json` | `6b362cabef04c8c2959eee7eac7b422d714577aca978cbe6f7af19dce40891cb` |
| `synthetic_v5_holdout_intercom_v1.json` | `001a8f98ed7c710130a87863e851a3fbdf46455cebd8e1dcd111fa944ba45aa5` |
| `synthetic_v5_holdout_intercom_stream_v1.json` | `d5da917339adf1681a015e5374fe7f153a79b5846526c0f6d83fa5e1a12ff734` |
| `synthetic_v5_short_latency_holdout_v1.json` | `af3b0c30a67023f78ab51b1a1a6aaf247ea266c9be5b584bba2aa46bab06ae59` |

## Objective audio and manifest checks

- Both build verifiers and the immutable holdout-seal verifier passed.
- 48 per-utterance clean/intercom WAV files were checked as mono 16 kHz PCM16,
  finite, non-empty, and sample-count-identical between variants.
- Peak range: -13.0140 to -0.4426 dBFS.
- RMS range: -28.7103 to -17.4540 dBFS.
- Maximum clipped-sample fraction: 0.0.
- Utterance duration range: 0.82 to 8.81 seconds.
- All inter-turn gaps in both combined variants are exact 10,400-frame digital
  silence, and clean endings pass the active-final-frame trim check.
- All four 12-clip manifests passed the Clip Benchmark validator. Both
  12-turn stream manifests match parent IDs, references, second boundaries,
  and frame boundaries. Both Short-Latency manifests passed the Streaming
  Latency validator with four metadata-selected clips each.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q \
  evaluation/synthesis_v2/tests

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/dev/synthetic_de_v5-dev-001

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/holdout/synthetic_de_v5-holdout-001
```

macOS `say` output can differ across operating-system or installed-voice
versions. The generated artifacts are bound to their recorded hashes, and the
holdout is additionally immutable under its seal.
