# Round 04 checkpoint — manual reference review required

Date: 2026-07-13 (America/New_York)

## Decision state

- **No candidate is frozen.** Candidate 12 was rejected by the critical
  pre-freeze review. Candidate 13 is only a diagnostic name and is not bound or
  frozen.
- **No v9, FLEURS-v2, or degraded-v2 holdout ASR has been run.**
- The next ASR holdout evaluation remains forbidden until reviewed manifests,
  a renewed Dev countercheck, a critical GO, and a schema-v2 candidate freeze
  all exist.
- The platform refused to start the loopback review server because the current
  approval/usage limit was exhausted. Do not bypass that restriction. A human
  may start the documented local-only server explicitly.

## Completed work

### ASR and live pipeline

- Hybrid Apple-Silicon routing uses original unpadded duration:
  - `<= 3.0 s`: pinned MLX Turbo, `word_timestamps=false`;
  - `> 3.0 s`: pinned MLX Full, word timestamps retained.
- Both MLX models are cached as separate float16 objects. A module-wide lock
  switches the global mlx-whisper `ModelHolder` atomically without reloading.
- Exact edge context remains 0.35 s for inputs up to 3.0 s; routing is decided
  before padding.
- Selective faster-whisper Small confirmation is pinned and audited.
- Safety confirmation is now independent of the closed-command prompt and may
  only reconcile one acoustically similar non-action token. Primary and
  secondary must choose the same candidate; the final action token must be
  exact in both.
- Reproduced counterexamples are blocked:
  - `Last sicher fallen`;
  - `Not-Aus sofort auslassen`;
  - `Bühne sofort sterben`.
- Legitimate `Lass` / `Lasst sicher halten` still resolves to
  `safety_load_hold`, with both raw texts retained.

### Evaluation hardening

- Schema-v2 candidate binding verifies hashes of release code, configuration,
  catalogs, sealed inputs, Dev reports and report source manifests.
- Exactly three warm latency reports are required. Transcript signatures must
  match, every run must remain below 3.5 s first usable output and RTF 0.5, and
  median end-to-emit variation must be at most 15%.
- Acceptance now rejects every scored clip with missing, pending, unreviewed or
  explicitly not-manually-reviewed reference provenance.
- Degraded references must bind exactly to their reviewed parent clip.
- Safety evidence is deduplicated by audio hash (with stable ID fallback), while
  every failing occurrence and report role remains visible.
- Historical v7-v9 fixtures remain structurally verifiable, but a real scoring
  run with unreviewed references stops before model loading.

### Test data and reproducibility

- A Dev-only adversarial Safety suite contains eight distinct changed-action
  negatives, eight German voices/rates, and separate Clean/Intercom PCM16 mono
  16-kHz files. All expected command IDs are null. ASR remains locked pending
  manual review.
- A local review UI records real append-only PASS/FAIL decisions with reviewer,
  server UTC time, audio/reference/manifest hashes and a SHA-chained log. It has
  no default decision and disables decisions until playback completes.
- Reviewed outputs are new files under
  `evaluation/data/reviewed_manifests/`; source and sealed manifests are never
  overwritten.
- Intercom and degraded manifests may inherit review only from a complete
  hash-bound reviewed parent and verified transformation/seal.
- A deterministic Human-Dev stream builder requires 12 reviewed raw FLEURS Dev
  clips, preserves PCM frames, inserts exactly 0.65 s silence, and produces a
  live-pipeline-compatible bound reference manifest.
- Setup downloads and offline-verifies exactly three immutable model snapshots.
- `evaluation/MODELS_V1.json` records both MLX routes and the Small fallback.

## Current diagnostic evidence (not freeze-eligible)

| Evidence | Result |
| --- | --- |
| Original v9 Clean baseline | product WER 0.6000, CER 0.22555 |
| Original v9 Intercom baseline | product WER 0.5600, CER 0.19817 |
| Safety-hardened v13 Clean diagnostic | product WER 0.1440, CER 0.04954, RTF 0.13174 |
| Safety-hardened positive commands | 8/8 exact IDs |
| Safety-hardened negative activation | 0 false activations in v9 diagnostic |
| C12 Human Dev diagnostic | WER 0.04464, CER 0.00863, RTF 0.05817 |
| C12 Degraded Dev diagnostic | WER 0.05625, CER 0.01443, RTF 0.06325 |
| C12 synthetic live diagnostic | WER 0.1360, CER 0.04563, RTF 0.11979, first output 2.19494 s |
| C12 warm latency diagnostics | identical metrics; medians 0.85827/0.85890/0.94119 s; max first 3.07842/3.07810/3.41766 s; RTF 0.13870/0.14933/0.19206 |
| Current Python suite | 240 passed, 3 known dependency/deprecation warnings |
| Current renderer build | passed |

The old reports above are diagnostically useful but intentionally fail the new
reference-provenance gate. They must not be reused as final acceptance evidence.

## Only current blocker

True auditory reference review cannot be performed by the coding agent. A human
must listen to the canonical source audio and compare it with the displayed
reference. No PASS values, logs or reviewed manifests have been fabricated.

Manual Dev profiles still required:

1. `safety_adversarial_clean_dev_v1` — 8 clips;
2. `synthetic_clean_dev_v9` — 24 clips;
3. `human_dev_v1` — 12 clips.

Safety Intercom, synthetic Intercom and degraded Dev inherit only after their
respective parent profile passes. Holdout review is deliberately deferred until
the renewed Dev candidate is otherwise ready; it remains a separate deliberate
review action with no ASR.

## Exact continuation commands

Run from the repository root. Start one review profile at a time, open
`http://127.0.0.1:8765`, enter a stable reviewer ID, listen to every clip to the
end, and record PASS only when speech and reference truly agree. Stop the server
with Ctrl-C before starting the next profile.

```bash
backend/.venv/bin/python -m evaluation.manual_review.review_server \
  --profile safety_adversarial_clean_dev_v1
```

After eight genuine current PASS decisions:

```bash
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_clean_dev_v1
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile safety_adversarial_intercom_dev_v1
```

Then repeat the manual server/export cycle for:

```bash
backend/.venv/bin/python -m evaluation.manual_review.review_server \
  --profile synthetic_clean_dev_v9
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile synthetic_clean_dev_v9
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile synthetic_intercom_dev_v9

backend/.venv/bin/python -m evaluation.manual_review.review_server \
  --profile human_dev_v1
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile human_dev_v1
backend/.venv/bin/python -m evaluation.manual_review.generate_reviewed_manifest \
  --profile degraded_dev_v1
```

After these reviewed Dev outputs exist, continue in this order:

1. create reviewed, hash-bound v9 Short-Latency and Stream adapters from the
   reviewed Intercom parent (do not edit old fixtures);
2. build the reviewed Human-Dev live stream with
   `evaluation/build_human_live_dev.py`;
3. rerun Clean, Intercom, adversarial Safety, Human, Degraded, three warm
   Short-Latency runs, synthetic live and Human live;
4. rerun all tests and the desktop build;
5. obtain a fresh critical pre-freeze GO;
6. manually review only the two canonical holdout parent profiles, export their
   inherited derivatives, and bind them without ASR;
7. create and verify schema-v2 Candidate 13;
8. freeze it in a separate immutable freeze record;
9. only then run the v9, Human-v2 and Degraded-v2 holdouts once.

## Verification commands

```bash
backend/.venv/bin/python -m pytest -q
npm run build:renderer
HF_HUB_OFFLINE=1 backend/.venv/bin/python scripts/download_models.py --verify-only
```

