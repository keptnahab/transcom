# Deterministic degradation suite v1

This module derives controlled robustness variants from an already manifested
clip suite. It never modifies parent audio or manifests and writes only to:

```text
evaluation/generated/degraded_v1/<derived-dataset-id>/
```

The derived ID binds the parent dataset ID to the degradation configuration
hash. Existing output is never overwritten and there is no force option.

## Profiles

Each parent clip produces five independent 16 kHz mono PCM variants:

- deterministic broadband Gaussian noise at 15 dB active-speech SNR;
- deterministic ambient-colored noise with 50/100/250 Hz components at 12 dB;
- 300–3400 Hz telephone band, an actual 8 kHz decimation, then a deterministic
  return to 16 kHz;
- bounded, cautious overdrive/clipping with measured gain and clipped fraction;
- low gain at exactly −18 dB.

Noise uses a fixed base seed and a per-profile seed derived from the parent clip
SHA-256. The manifest records requested and measured SNR, seeds, all processing
parameters, parent and output hashes, Python/NumPy/SoundFile/libsndfile versions,
and the generator/configuration hashes.

## Parent and split safety

- Every selected parent clip must match the SHA-256 in its parent manifest.
- The derived manifest binds the exact parent-manifest SHA-256 and clip hashes.
- `split`, `usage`, `official_split`, and holdout status are inherited; the CLI
  has no split-changing option.
- Holdout parents must have a valid seal. Holdout derivation additionally needs
  `--confirm-holdout-derivation`; the derived dataset is immediately sealed.
- Verification is read-only and idempotent. It checks all derived hashes, the
  current parent-manifest hash, and the derived holdout seal when applicable.

This module creates audio conditions only. It does not run ASR, inspect
hypotheses, or evaluate human holdout results.

## Plan without writing

For the development set:

```bash
backend/.venv/bin/python evaluation/degradation_v1/generate.py plan \
  evaluation/data/manifests/fleurs_de_dev_v1.json
```

For synthesis-v2 manifests, select the desired parent variant if needed:

```bash
backend/.venv/bin/python evaluation/degradation_v1/generate.py plan \
  evaluation/generated/synthetic_v2/dev/<build-id>/manifest.json \
  --variant clean
```

## Build and verify

```bash
backend/.venv/bin/python evaluation/degradation_v1/generate.py build \
  evaluation/data/manifests/fleurs_de_dev_v1.json
```

```bash
backend/.venv/bin/python evaluation/degradation_v1/generate.py verify \
  evaluation/generated/degraded_v1/<derived-dataset-id>
```

Tests use only tiny temporary WAV files:

```bash
backend/.venv/bin/python -m pytest -q evaluation/degradation_v1/tests
```
