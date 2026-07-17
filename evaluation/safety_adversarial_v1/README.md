# Dev-only adversarial Safety suite v1

This suite contains only synthetic negative utterances whose final action verb
changes the meaning of a closed Safety command. Every clip has
`expected_command_id: null`.

The source manifests deliberately set `scoring_authorized: false` and every
reference is `synthetic_source_pending_manual_audio_review`. Do not run ASR on
either manifest. Technical WAV QA is not a substitute for listening review.

Build once, without overwriting existing artifacts:

```bash
backend/.venv/bin/python evaluation/safety_adversarial_v1/build.py build
backend/.venv/bin/python evaluation/safety_adversarial_v1/build.py verify
```

Manual review uses the existing hash-bound UI. Start it with the manual parent
profile `safety_adversarial_clean_dev_v1`, listen to every clean file, and
record `PASS` only when the spoken audio matches the displayed source text
without clipping, truncation, artificial gaps, or wrong transitions. The
intercom profile is a deterministic, hash-bound derivative of those same
sources. Its reference approval is inherited only after the complete clean
review; its independent signal QA remains enforced by the suite tests.

After all clean clips pass, generate the clean reviewed manifest first and the
intercom inherited manifest second; source manifests are never overwritten:

```bash
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_clean_dev_v1
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_intercom_dev_v1
```

The second command refuses to run unless the clean reviewed output is present,
current, and reproducible. Only the resulting `*_reviewed_v1.json` manifests
become score-authorized.
