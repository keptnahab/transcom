# Safety adversarial Dev v1 — pending manual audio review

## State

- Dev only; no holdout artifact was read, changed, generated, or scored.
- No ASR was run while building or technically validating this suite.
- Both source manifests set `scoring_authorized: false`.
- Reference status is `synthetic_source_pending_manual_audio_review` for all
  16 audio files. These manifests are not valid scoring inputs.
- Focused QA: 18 passed, 1 environment warning.
- Full project suite: 240 passed, 3 environment/deprecation warnings.

## Coverage

Eight unique negative utterances change the action of a closed Safety command:
`fallen`, `auslassen`, `sterben`, `lösen`, `verbinden`, `betreten`,
`freigeben`, and `starten`. Every source has `expected_command_id: null`.

The same eight source utterances were rendered with eight locally installed
German voices at eight rates from 150 to 206 words per minute. Clean is the
manual parent profile; intercom is its deterministic, hash-bound inherited
profile.

## Technical QA

- 16 individual WAV files
- PCM signed 16-bit little-endian, mono, 16 kHz
- duration range: 1.28–1.87 seconds
- clean peak range: 13,658–29,520 PCM16
- intercom peak range: 7,390–11,810 PCM16
- all files non-empty, non-silent, finite-length, and below clipping
- all file hashes, source hashes, QA fields, paths, categories, split flags,
  and null command expectations verified
- pending manifests are actively rejected by the clip scoring validator

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| Source specification | `166470739bbfe972dac7c4981d9fe588a43dceaae3f292e618a6ec73fd669037` |
| Build script | `032d5d59eacf89726c112665a828df0ca4e182dd4bca1f728a8af8c49a4e839f` |
| Clean pending manifest | `e52c374d605059ef01d8df6123895dcdbff126660f8cc22da438fd44a0128ce3` |
| Intercom pending manifest | `d2d75e6a301136024c072e8a7179679e54a06dfb73f9e294e10a0c7bd6fcaae8` |

Per-file audio hashes are stored in their respective manifests.

## Manual review handoff

Use the existing hash-bound manual-review application with the manual parent
profile `safety_adversarial_clean_dev_v1`. Listen to every clean file and
compare it with the displayed source text. Mark PASS only when pronunciation
and wording match and there are no clipped phonemes, truncated endings,
artificial gaps, or broken transitions.

Export the clean reviewed manifest first. Then export
`safety_adversarial_intercom_dev_v1`; the exporter verifies the current parent
PASS log, parent output, intercom manifest and every derived audio hash before
inheriting the reference approval. It refuses missing, stale or altered
evidence. Both pending sources remain unchanged, and only the reviewed outputs
receive `scoring_authorized: true`.

Do not run ASR before both reviewed outputs have been generated successfully.

## Exact continuation commands

```bash
backend/.venv/bin/python -m evaluation.manual_review.review_server \
  --profile safety_adversarial_clean_dev_v1

backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_clean_dev_v1

backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_intercom_dev_v1

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_safety_adversarial_suite.py \
  tests/test_manual_reference_review.py \
  tests/test_clip_suite_benchmark.py
```

The two exporter commands must be run only after all eight clean clips have a
current manual PASS. ASR remains prohibited until both reviewed outputs exist.
