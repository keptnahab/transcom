# Round 05 checkpoint — Candidate 5 rejected before freeze

Date: 2026-07-13

## Decision

Candidate 5 was **not frozen** and the sealed v8 holdout remains unopened by
ASR. The first v8 Dev direct runs looked strong, but the simulated live test and
adversarial review found release-blocking safety defects.

## Evidence before rejection

- v8 Dev direct intercom, canonical output: WER `0.11579`, CER `0.06621`,
  command IDs `8/8`, RTF `0.15352`.
- v8 Dev direct clean, canonical output: WER `0.14737`, CER `0.06282`, command
  IDs `8/8`, RTF `0.15334`.
- Initial short simulated-live run: only `7/8` safety command IDs; Silero VAD
  removed the first `0.12 s` of “Not-Aus sofort auslösen”.
- Raising bounded silence-only VAD pre-roll from `0.50 s` to `0.65 s` restored
  the missing onset and produced `8/8` IDs without latency regression.

These early WER/CER values were computed after catalog canonicalization and are
therefore retained only as diagnostic history, not release metrics.

## Review findings that invalidated Candidate 5

1. Negated/opposite phrases could be rewritten as positive commands.
2. Repeated safety events could be suppressed upstream of the safety-aware
   store.
3. WER/CER did not distinguish pre-normalization model text from canonical
   product text.
4. Confirmation lacked actor/time/snapshot audit events.
5. v8 had no spoken negative/OOD command-confusion group.

## Implemented corrections

- Conservative closed-command matching rejects negations, opposite actions,
  prohibition language, ambiguity, low score, and any additional words.
- The true model text is captured before number/domain normalization for every
  segment and is reported separately from canonical product text.
- Safety attempts bypass generic transcript deduplication; the store also
  protects prior safety audit records from normal replacements.
- Raw text, command ID, score, margin, rejection reason, catalog ID/hash,
  confirmation actor/time, and append-only confirmation snapshots persist.
- The UI/LAN view displays changed raw text rather than hiding it in a tooltip.
- Acceptance now checks Clean, Intercom, and simulated-live command IDs plus
  false command activation and fully wrong raw safety text.
- Default silence-only VAD pre-roll is now `0.65 s`.

## Verification

- Full Python suite: `168 passed`.
- Renderer production build: passed.
- v8 build, seal, and isolation QA passed; no v8 holdout ASR result exists.

## Next step

Build and seal v9 before ASR. v9 must add spoken catalog-external negations,
opposite actions, and phonetically similar noncommands to both split designs.
Only v9 Dev may be used for the next candidate countercheck; its holdout remains
closed until a candidate is frozen with code/config/report hashes.

## Continue commands

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q
npm run build:renderer
```

Do not run any v8 or v9 holdout ASR command at this checkpoint.
