# Candidate binding v2 and warm-repeat freeze gate

## Decision

A candidate may be assessed in legacy mode, but it is **not eligible for a
pre-freeze decision** unless `evaluation/check_acceptance.py` verifies a
schema-v2 candidate binding. A metrics-only JSON or a historical schema-v1
candidate can never set `pre_freeze_eligible` to true.

This verification is Dev-only. It hashes sealed holdout manifests as opaque
bytes and validates the seal metadata; it does not parse holdout manifests,
audio, references, or ASR results.

## Candidate schema

All paths are project-relative regular files. Every `sha256` is the SHA-256 of
the exact file bytes. The author must enumerate the complete release-relevant
code and configuration inventory, not only the files changed in the last
experiment.

```json
{
  "schema_version": 2,
  "candidate_id": "transcom-asr-candidate-vN",
  "freeze_state": "pre_freeze",
  "acceptance_binding": {
    "schema_version": 1,
    "code": [
      {"path": "backend/transcription/engine.py", "sha256": "<64 hex>"},
      {"path": "evaluation/check_acceptance.py", "sha256": "<64 hex>"}
    ],
    "configuration": [
      {"path": "evaluation/TARGETS_V1.md", "sha256": "<64 hex>"},
      {"path": "evaluation/MODELS_V1.json", "sha256": "<64 hex>"}
    ],
    "catalogs": [
      {
        "path": "backend/transcription/catalogs/safety_commands_closed_v1.json",
        "sha256": "<64 hex>"
      }
    ],
    "sealed_manifests": [
      {
        "manifest": {"path": "<sealed manifest>", "sha256": "<64 hex>"},
        "seal": {"path": "<seal JSON>", "sha256": "<64 hex>"}
      }
    ],
    "dev_reports": {
      "baseline_clean": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "baseline_intercom": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "candidate_clean": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "candidate_intercom": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "short_latency": {"path": "evaluation/results/<warm-run-1>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "human": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "degraded": {"path": "evaluation/results/<report>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
      "warm_short_latency_runs": [
        {"path": "evaluation/results/<warm-run-1>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
        {"path": "evaluation/results/<warm-run-2>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}},
        {"path": "evaluation/results/<warm-run-3>.json", "sha256": "<64 hex>", "source": {"path": "<Dev manifest>", "sha256": "<64 hex>"}}
      ]
    }
  }
}
```

The verifier rejects missing or unknown report roles, duplicate report files,
unsafe paths, symlinks, stale hashes, non-Dev sources, mismatched report/source
hashes, unverified clip hashes, wrong benchmark types, seals that do not bind
their manifest, and any mismatch between bound paths and command-line paths.
`short_latency` must be byte-identical to warm run 1; warm runs 2 and 3 must be
separate report files.

Every scored `clip_result` must also carry a non-empty reviewed
`reference_status`. Statuses without `reviewed`, or statuses containing a
negative/pending marker such as `not`, `unreviewed`, `pending`, `unchecked` or
`unverified`, are rejected. This gate applies to baseline, candidate, human,
degraded and short-latency reports. For degraded reports, every result must in
addition match the reference text and reviewed status in the hash-bound
degraded source manifest's nested reference record; the derived clip must also
retain its parent-clip binding.

The streaming-latency benchmark now copies `reference_status` from the
hash-validated fixture clip or, when present, its hash-bound source clip. It
supports both direct and nested degraded reference records, rejects text or
status disagreement, and refuses to run when neither bound source supplies a
status. Existing latency manifests without a status therefore remain invalid;
the benchmark does not invent review provenance.

Safety evidence is grouped by audio SHA-256 when available, otherwise by the
stable audio/clip ID. Acceptance reports both `unique_clips` and raw
`occurrences` (plus duplicate count). Every failed or activated occurrence is
retained with its report role, so deduplication cannot hide a disagreement or
regression between clean, intercom and short-latency reports.

## Warm-repeat gates

Exactly three already-warmed short-latency runs are required. Model loading is
not part of the measured repeat. The acceptance checker requires:

- identical aggregate and per-clip WER/CER, canonical WER/CER, counts and
  expected/detected command IDs across all three runs;
- `(max(run medians) - min(run medians)) / median(run medians) <= 0.15`, where
  each run median is calculated from per-clip `end_to_emit_seconds`;
- maximum per-clip `first_usable_emit_seconds <= 3.5` in every run;
- `real_time_factor <= 0.5` in every run.

The transcript signature deliberately excludes timing values, so timing may
vary within the latency gate while recognition results must remain identical.

## Invocation

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python evaluation/check_acceptance.py \
  --candidate-binding evaluation/CANDIDATE_VN.json \
  --baseline-clean evaluation/results/<baseline-clean>.json \
  --baseline-intercom evaluation/results/<baseline-intercom>.json \
  --candidate-clean evaluation/results/<candidate-clean>.json \
  --candidate-intercom evaluation/results/<candidate-intercom>.json \
  --short-latency evaluation/results/<warm-run-1>.json \
  --human evaluation/results/<human>.json \
  --degraded evaluation/results/<degraded>.json \
  --warm-short-latency evaluation/results/<warm-run-1>.json \
  --warm-short-latency evaluation/results/<warm-run-2>.json \
  --warm-short-latency evaluation/results/<warm-run-3>.json \
  --output evaluation/results/<candidate>-acceptance.json
```

Exit status 0 means all metric and warm-repeat gates pass. The generated JSON
is freeze-eligible only when both `passed` and `pre_freeze_eligible` are true
and `candidate_binding.verified` is true. Exit status 1 is a gate failure; exit
status 2 is malformed input or a binding failure.

## Historical candidate V4 audit

`evaluation/CANDIDATE_V4.json` was intentionally left byte-unchanged. Its six
Dev evidence report hashes and all six recorded sealed-v6 input hashes still
match. However, only 6 of its 20 implementation hashes match the current
working tree; 14 are stale after later development. It also uses schema v1 and
contains only one latency run. It remains valid historical evidence but cannot
bind or freeze the current implementation.

## Verification performed

- Focused acceptance tests: 11 passed.
- Acceptance plus clip-suite, streaming-latency and safety-command regression
  tests: 42 passed after the latency-provenance and safety-evidence hardening.
- Python compilation of the checker and tests passed with an isolated cache.
- Candidate-v12's three Dev warm reports pass all five repeat gates. Their
  transcript-metric signature is identical; median end-to-emit is 0.858272,
  0.858899 and 0.941193 seconds (9.654% relative range), maximum first usable
  is 3.078422, 3.078098 and 3.417656 seconds, and RTF is 0.138698, 0.149327
  and 0.192056.
- Candidate-v12 is nevertheless **not freeze-eligible**: all 24 clean, all 24
  intercom, all 12 human and all 60 degraded scored references are explicitly
  marked `*_not_manually_reviewed`; all 18 short-latency results lack
  `reference_status`. These reports may remain diagnostic evidence, but cannot
  satisfy acceptance until references are genuinely reviewed and new
  hash-bound Dev reports are generated.
- No ASR model was loaded and no holdout audio, reference text or ASR result
  was opened. One over-broad metadata inventory surfaced only holdout manifest
  filenames and `reference_status` labels; this scope error was reported to the
  orchestrator and all subsequent checks were restricted to Dev artifacts.
