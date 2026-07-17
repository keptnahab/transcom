# Synthetic v4 production-message suite

## Scope and policy

- Created without ASR output, model loading, or hypothesis inspection.
- Eight development and eight separately sealed holdout utterances.
- Four German macOS voices and at least four speech rates per split.
- Each split covers `short`, `safety`, `alphanumeric`, `number`, and
  `technical`; both also contain longer control statements.
- Dev and holdout have disjoint IDs, speaker names, voices, and exact texts.
- All 16 exact v4 texts are disjoint from all exact v3 texts. No v3 holdout
  speaker name is reused in v4 metadata or reference text.
- Audio uses the v3 policy: mono 16 kHz PCM16, 0.65 s / 10,400-frame digital
  pauses, 10 ms / -50 dBFS trailing trim, and no added trailing guard.

## Source and build hashes

| Artifact | SHA-256 |
|---|---|
| `evaluation/synthesis_v2/specs/dev_v4.json` | `3982db9b9bc10ad6e7d2d0bfba8aa8fafdabc531dc70cccd281582505d98bf13` |
| `evaluation/synthesis_v2/specs/holdout_v4.json` | `adc3e034cf10d936e1f507da3ca99b23a036d9bddcac1796ff4f7b9758d31b70` |
| Dev build manifest | `6b39f661b6d8b4e9753af5a3e3711b312281e201d1981b7a65c71f13a61f5ad2` |
| Holdout build manifest | `fe2932486a37f0cbee0a96b8d50dd9cf871f9ba8460eb234641de874cc144c3e` |
| Holdout seal | `db6c7523d47d4ff8ed5dbd78289044e693953b1cdb08105b92aa62264d89fad5` |
| Dev combined clean audio | `c011c5eae82f76042df0f08f8f01aa41b2d331b22ce7fb6315269fd13390a3c4` |
| Dev combined intercom audio | `37bf053172ecc8ffc37aa40d4ea0a93b75c4f9bcd10c7fc9d81074fbbe505364` |
| Holdout combined clean audio | `08fc4e48898f3543f2bbf97eaf921d4e1ddfb30d8987f16e2dcb9fcc03ff0e28` |
| Holdout combined intercom audio | `89d9bdf81c8fe17ef8d5e53eeee7b217bbbe78c1f10a48f7477441951ef998f4` |

## Evaluation-manifest hashes

| Manifest | SHA-256 |
|---|---|
| `synthetic_v4_dev_clean_v1.json` | `c821060715aa44a1035b4910f7180487dd3eb075c086defb6664d9cdb76db245` |
| `synthetic_v4_dev_intercom_v1.json` | `52e017103dad5ba8e9d3ab899167b183aef5b045e290fad3e0c35cec1ddba47e` |
| `synthetic_v4_dev_intercom_stream_v1.json` | `dc1dd7fb820cbcdb97faf9e5022cc619489d7c8dcb04f0531794382f0c2eb5ac` |
| `synthetic_v4_short_latency_dev_v1.json` | `6531edaed6192c0d5128b885a49cbeb440677152481033413960b96b884ddf23` |
| `synthetic_v4_holdout_clean_v1.json` | `fdfacb47634bd0f233bd4d44796edc498bd77db6c2f5a7fa36dbb33681d3d8f5` |
| `synthetic_v4_holdout_intercom_v1.json` | `6f62351938e615c9a0c00b04a0de06212479dbc6c556f86c9a174cbf04b0472c` |
| `synthetic_v4_holdout_intercom_stream_v1.json` | `ef680aafcd6adbaa85e61e9418f44bc52cac581213b6215a10ef8c7b0f7e9778` |
| `synthetic_v4_short_latency_holdout_v1.json` | `e6ced366ae3e07e90179100497b277ad454ad50f660d702e88cafb21b1c25844` |

## Objective audio checks

- Both build verifiers and the holdout-seal verifier passed.
- 32 per-utterance clean/intercom WAV files were checked: mono, 16 kHz,
  PCM16, finite, non-empty, and sample-count-identical between variants.
- Peak range: -12.6154 to -0.7382 dBFS.
- RMS range: -29.0283 to -17.7908 dBFS.
- Maximum clipped-sample fraction: 0.0.
- Utterance duration range: 1.42 to 9.63 seconds.
- All 14 inter-turn gaps per combined variant are exact 10,400-frame digital
  silence; clean part endings pass the v4 active-final-frame trim check.
- Clip manifests passed the Clip Benchmark validator. Streaming turns match
  parent IDs, text, seconds, and frames. Short-Latency manifests passed the
  Streaming Latency validator with three Dev and four sealed Holdout clips.

## Reproduction and verification

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q \
  evaluation/synthesis_v2/tests

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/dev/synthetic_de_v4-dev-001

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/holdout/synthetic_de_v4-holdout-001
```

macOS `say` output can differ across operating-system or installed-voice
versions. The checked builds are therefore bound by their manifests and, for
holdout, by the immutable seal; cross-machine byte-identical synthesis is not
claimed.
