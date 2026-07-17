# Manual audio/reference review

This local workflow records real human decisions. It never runs ASR, never
preselects PASS, and never edits a source manifest.

## Review policy

Only canonical source audio is listened to manually:

- `synthetic_clean_dev_v9`
- `synthetic_clean_holdout_v9`
- `human_dev_v1`
- `human_holdout_v2`
- `safety_adversarial_clean_dev_v1`

Derived audio is kept in separate profiles and may only inherit a passed parent
review:

- `synthetic_intercom_dev_v9` from `synthetic_clean_dev_v9`
- `synthetic_intercom_holdout_v9` from `synthetic_clean_holdout_v9`
- `degraded_dev_v1` from `human_dev_v1`
- `degraded_holdout_v2` from `human_holdout_v2`
- `safety_adversarial_intercom_dev_v1` from `safety_adversarial_clean_dev_v1`

The inheritance exporter refuses to proceed unless the canonical parent has a
complete current PASS decision for every clip, the parent reviewed manifest is
exactly reproducible, references are unchanged, parent audio hashes agree, the
derived audio hashes agree, and the transformation manifest and required
holdout seal are hash-bound. A required tree seal is fully revalidated: every
listed file hash and size must agree and no file may have been added or removed.

## Manual review

Start exactly one explicit profile at a time from the repository root:

```bash
backend/.venv/bin/python -m evaluation.manual_review.review_server \
  --profile synthetic_clean_dev_v9
```

The server accepts loopback binding only. Open `http://127.0.0.1:8765`, enter a stable reviewer identifier, listen to the
whole item, compare it to the displayed reference, then record PASS or FAIL. A
FAIL requires a note. Buttons remain disabled until playback finishes; this is a
review aid, not a claim that the browser can prove human attention.

Each decision is appended to the profile's JSONL log under
`evaluation/manual_review/logs/`. The server supplies the UTC time. Every event
binds the source-manifest hash, complete original clip record, reference hash,
declared and verified audio hash, reviewer, note, decision, and preceding event
hash. A later decision does not erase history; it becomes the current decision
for that clip.

Review logs are evidence. Preserve and version them with the reviewed manifests.
Do not edit, reformat, concatenate, or truncate them. If a source manifest
legitimately changes, begin a new versioned profile and log instead.

## Generate reviewed manifests

After every current decision in a manual profile is PASS:

```bash
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile synthetic_clean_dev_v9
```

The deterministic exporter writes the profile's filename ending in
`_reviewed_v1.json` under `evaluation/data/reviewed_manifests/`. This separate
location is required so that an output never changes a sealed holdout tree.
Existing source files are never overwritten. Repeating the same export is
idempotent; a different existing output is not overwritten.

Only after the canonical parent export exists, create its derived manifest:

```bash
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile synthetic_intercom_dev_v9
```

Manual outputs set `reference_status=manually_audio_reviewed`. Inherited outputs
set `reference_status=manually_audio_reviewed_parent_inherited`. All outputs add
the review-log hash. Inherited clips also record the exact parent audio hash,
parent manifest hash, parent review-log hash, transformation-manifest hash, and
seal path/hash when a seal is required. Audio, reference text, audio hashes, and
existing provenance remain unchanged.

## Holdout discipline

Selecting a holdout profile is a deliberate review action. The server does not
print reference text or audio content to the terminal or review log. Reference
text is returned only to the local browser session for the explicitly selected
profile. Automated tests use temporary fixture manifests only and do not open
real holdout contents.

## Verification

```bash
env PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
  backend/.venv/bin/python -m pytest -q tests/test_manual_reference_review.py
node --check evaluation/manual_review/static/app.js
```

The tests cover incomplete reviews, FAIL correction without history loss,
reviewer and note validation, manifest/audio/log tampering, deterministic
output, parent inheritance, transformation/seal binding, profile separation,
and the absence of a default UI decision.
