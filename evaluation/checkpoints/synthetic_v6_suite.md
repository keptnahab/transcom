# Synthetic v6 safety-command suite

## Scope and isolation

- Created without ASR, model loading, or hypothesis inspection.
- Sixteen development and sixteen separately sealed holdout utterances.
- Each split has exactly six short safety commands, four short alphanumeric
  messages, three medium controls, and three long controls.
- Four German macOS voices and at least eight speech rates per split.
- All 32 exact texts are unique, Dev/Holdout-disjoint, and have zero exact
  overlap with every v3, v4, or v5 text.
- Audio follows the established method: mono 16 kHz PCM16, clean and intercom
  variants, exact 0.65-second / 10,400-frame digital pauses, 10 ms / -50 dBFS
  trailing trim, and no added trailing guard.

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| `evaluation/synthesis_v2/specs/dev_v6.json` | `f32cb8c469eefcea8750e6af11a710d39e83e2570f2e0a196c514a38a2ab0c39` |
| `evaluation/synthesis_v2/specs/holdout_v6.json` | `7facfc3e8cfc7dfe78864471bc03acd99e687fd54f494e09e7bbc21abe6c318a` |
| Dev build manifest | `2e61898559763dded4555cee87fd3f5b3dd04f5ef17da4f98b9c567c113dc84e` |
| Holdout build manifest | `9be633e508ed749a961c99635a2dc6ca9ff583d4f049b9fa2c111a976091f7c5` |
| Holdout seal | `f3a6cb4f893c45efa3dc1f258fb78a0202aa5763138f9e3dc50407512aa7543d` |
| Dev combined clean audio | `50045b6d13414814d6c8bb1395a931bf95854d22ae57509ed30e966b0da4f741` |
| Dev combined intercom audio | `b14d923711c00feb6a7a9e7449d887de78250305d8c487352c836e866b24871a` |
| Holdout combined clean audio | `3562b4b9b4905643367f59a2270c0244cc3c29755410cadaf67e892dd9f8ed7e` |
| Holdout combined intercom audio | `504e5dcb2e21babaaba1fa343141c60f2573dd175ddabb744de7ab9344effcb4` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v6_dev_clean_v1.json` | `7b7fba3f8fb3e1b8913e6bb11dc4a2b8af42cd1b6180108bb8506963cbeeb2d3` |
| `synthetic_v6_dev_intercom_v1.json` | `b350951427293860e8768935117ce03e1dd510fececf43f409e4073c05cd37e3` |
| `synthetic_v6_dev_intercom_stream_v1.json` | `cf3d095c60f3a995265678727db8ea2768c2118ffc4e670afcae994ed525f45d` |
| `synthetic_v6_short_latency_dev_v1.json` | `00196186f09ba33074b4f45016fa2246527caf287db67124cde2aabd0b3de30e` |
| `synthetic_v6_holdout_clean_v1.json` | `28a150221567b9719c30e1e376a32d13c6e8148cd78e8d699878986c9a2268c3` |
| `synthetic_v6_holdout_intercom_v1.json` | `6656b1f2f8a7dcb838e353e45aa718d96a3bb8719817fef59e123bd8e8dc8be4` |
| `synthetic_v6_holdout_intercom_stream_v1.json` | `7181ef850312f9c5bbf8d75e768e5d77053de5c198ce9a0bb7a8ee5a60db6075` |
| `synthetic_v6_short_latency_holdout_v1.json` | `ddc9a285091db668bcfed4797319174c4ca9a25de40529fcd72ed729dcf6b257` |

## Objective QA

- Build verifiers and the immutable holdout-seal verifier passed.
- 64 per-utterance clean/intercom WAV files were mono 16 kHz PCM16, finite,
  non-empty, and sample-count-identical between variants.
- Peak range: -12.0116 to -0.9969 dBFS.
- RMS range: -29.4895 to -17.3067 dBFS.
- Maximum clipped-sample fraction: 0.0.
- Utterance duration range: 1.26 to 8.78 seconds.
- All combined inter-turn gaps are exact 10,400-frame digital silence; clean
  endings pass the active-final-frame trim check.
- Clip, stream, and Short-Latency validators passed. Stream IDs, references,
  second boundaries, and frame boundaries exactly match their parent builds.
  Each Short-Latency suite contains the exact ten metadata-selected short clips.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q \
  evaluation/synthesis_v2/tests

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/dev/synthetic_de_v6-dev-001

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/holdout/synthetic_de_v6-holdout-001
```

The generated artifacts are bound to their recorded hashes. The holdout is
additionally immutable under its seal. Cross-machine byte identity is not
claimed because macOS voice output can change between platform versions.
