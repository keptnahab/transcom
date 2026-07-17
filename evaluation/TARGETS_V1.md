# TransCom ASR acceptance targets v1

Frozen on 2026-07-13 before any ASR/pipeline optimization in this evaluation round.

## Release gates

- The original current-worktree baseline and the historical Git fixture baseline are reproducible.
- Raw audio is immutable; generated derivatives live outside `data/raw` and carry provenance.
- Development and holdout manifests contain disjoint audio IDs and source files.
- Synthetic, human, and intentionally degraded groups are reported separately.
- Every scored file has a reviewed reference. A mismatched reference invalidates the run.
- WER and CER are each at least 20% lower relative to the valid baseline on the untouched aggregate holdout.
- No required holdout subgroup regresses by more than 0.05 absolute WER.
- Clean human holdout WER is at most 0.20 and CER at most 0.12.
- Clean synthetic holdout WER is at most 0.20 and CER at most 0.12.
- Intentionally degraded holdout WER is at most 0.40 and CER at most 0.25.
- Critical short commands have zero meaning-changing errors in the reviewed scenario set.
- Simulated first usable emit is at most 3.50 seconds for utterances that end within 3 seconds.
- Total ASR inference real-time factor is at most 0.50 on the reference MacBook after warmup.
- Three repeated warm runs produce identical transcript metrics; median latency must vary by at most 15%.
- All Python tests and the renderer build pass.

## Promotion rule

A change is promoted only when it improves the untouched aggregate holdout, satisfies the subgroup regression rule, and passes the automated suite. Development-set-only gains do not qualify.

## Current limitations of the target set

At freeze time the repository contained only synthetic fixtures. The human and degraded holdout groups must therefore be added before final release acceptance; until then those gates remain untested, not waived.
