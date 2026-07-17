# Reviewed Human FLEURS Dev live-evidence builder

## Purpose and current decision

`evaluation/build_human_live_dev.py` creates deterministic Human live-pipeline
evidence from exactly 12 reviewed German FLEURS Dev clips. It performs no ASR
and cannot read holdout input.

The current `evaluation/data/manifests/fleurs_de_dev_v1.json` is explicitly
`official_fleurs_metadata_not_manually_reviewed`. Its single authorized builder
attempt was rejected at clip 1 before any audio path was resolved or output was
written. It must not be used for live scoring or relabeled without a genuine
manual audio/reference review.

## Required reviewed source

The input is a project-local, non-symlink JSON manifest with:

- `dataset_name: "FLEURS"`, a FLEURS `dataset_id`, development usage and Dev
  official split, and `is_holdout: false`;
- exactly 12 unique raw Human WAV clips;
- for each clip: unique `audio_id`, safe project-relative `data_path`, SHA-256,
  reference text and a positive status containing `manually_reviewed`;
- per-clip `review_provenance` containing a non-empty pseudonymous
  `reviewer_id`, an ISO-8601 `reviewed_at_utc` with UTC offset, method
  `manual_audio_reference_review`, and SHA-256 of the exact UTF-8 reference
  text.

Missing, pending, unreviewed and `*_not_manually_reviewed` statuses are rejected
before audio access. Every WAV must be a non-empty, uncompressed mono 16 kHz
PCM16 file under a raw Human project directory, and its exact file SHA-256 must
match. Duplicate IDs or audio hashes are rejected.

## Deterministic outputs

After all 12 clips pass validation, the builder copies their PCM frame bytes in
manifest order. It performs no decoding transformation, normalization or
resampling. Between adjacent clips it inserts exactly 10,400 zero-valued PCM16
frames, i.e. exactly 0.65 seconds at 16 kHz. There is no leading or trailing
pause.

The reference manifest binds:

- source-manifest path and SHA-256;
- combined audio path, SHA-256, format and exact frame count;
- fixed composition policy and pause geometry;
- every turn's source audio SHA-256, frame/time boundaries, reference status,
  reviewer provenance and reference-text hash.

It contains the top-level `audio_sha256` and non-empty `turns[].text` required
by `scripts/benchmark_live_pipeline.py --reference-manifest`.

## Build command after manual review

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/build_human_live_dev.py \
  evaluation/data/manifests/<reviewed-fleurs-dev>.json \
  evaluation/generated/human_live_dev/fleurs_de_dev_reviewed_live_v1.wav \
  evaluation/data/manifests/fleurs_de_dev_reviewed_live_v1.json
```

Only after this builder succeeds may the resulting Dev audio/reference pair be
passed to the live benchmark. The builder summary supplies both output hashes
for candidate binding.

## Verification

- Unit tests confirm byte-identical rebuilds, source-frame preservation,
  exactly 11 pauses of 10,400 zero frames, mono 16 kHz PCM16 output, reference
  hash binding and compatibility with `load_reference`.
- Negative tests cover missing/unreviewed status, review-text provenance,
  audio-hash mismatch and invalid sample rate without partial outputs.
- The real unreviewed FLEURS Dev manifest produced the expected exit status 2
  and left no output files.
- No model was loaded and no ASR was run.

