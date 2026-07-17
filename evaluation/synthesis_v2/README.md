# Synthetic German evaluation data v2

This directory defines a safe, versioned supplement to the TransCom evaluation
suite. Synthetic speech is not a substitute for the human holdout set.

## Safety properties

- Existing files are never overwritten. There is deliberately no `--force` flag.
- Output is restricted to `evaluation/generated/synthetic_v2/<split>/<build-id>`.
- `evaluation/data/raw` and `fixtures/audio` are protected roots.
- No code path copies output to the app demo fixture.
- Original `say` AIFF files, untrimmed PCM parts, trimmed clean parts, and filtered
  intercom parts are retained separately.
- Voice-provided trailing silence is trimmed. The combined files insert one
  sample-exact digital pause between adjacent utterances.
- Dev and holdout use disjoint utterance IDs, text, speakers, and voices.
- A generated holdout gets `HOLDOUT_SEAL.json`. The seal covers the manifest and
  every artifact. Any change or added file fails verification. Repairing a
  sealed build in place is forbidden; create a new dataset version instead.

The generator records the source spec and generator hashes, every artifact hash,
the selected voice metadata, Python/macOS details, and the exact FFmpeg version
and filter. macOS speech synthesis can still change across OS or installed voice
versions, so byte-identical regeneration is not promised across machines.

## Corpus design

The UTF-8 specs are in `specs/dev.json` and `specs/holdout.json`. They contain
real umlauts and `ß`, short and long utterances, disjoint voices, names with
diacritics, dates, times, decimals, safety calls, abbreviations, alphanumeric
cues, and production vocabulary.

The original files remain the explicit `v2` specification. Additive `v3` specs
live in `specs/dev_v3.json` and `specs/holdout_v3.json`. They retain the exact
split-disjoint scripts, speakers, voices, and rates from v2, but use one 0.65 s
(10,400-frame) intercom turn pause and no added TTS trailing-silence guard. Select
v3 explicitly with `--spec-version v3`; omitting the option preserves v2 behavior.

The additive `v4` specs in `specs/dev_v4.json` and `specs/holdout_v4.json`
contain new, mutually isolated production messages for short commands, safety,
alphanumeric identifiers, numbers, technical status, and longer controls. They
are text-disjoint from all v3 utterances and retain the v3 pause and trim policy.
Select them explicitly with `--spec-version v4` and a new v4 build ID.

The additive `v5` specs in `specs/dev_v5.json` and `specs/holdout_v5.json`
expand that coverage to twelve utterances per split, emphasizing short safety
commands and alphanumeric cues alongside numeric, medium, and long theater and
technical messages. Their texts are disjoint from v3, v4, and each other. They
use the same 0.65-second pause and zero-guard trim policy.

The additive `v6` specs in `specs/dev_v6.json` and `specs/holdout_v6.json`
contain sixteen utterances per split. Each has six short safety commands, four
short alphanumeric status messages, and six medium/long production controls.
Their texts are disjoint from v3 through v5 and between splits, while retaining
the same 0.65-second pause and zero-guard trim policy.

The additive `v7` specs in `specs/dev_v7.json` and `specs/holdout_v7.json`
bind every safety utterance to a known allowed intent in
`catalogs/safety_commands_v1.json`. The catalog is frozen before evaluation and
contains intent identifiers and meanings, but deliberately no phrases, audio,
voices, or rates. Dev and holdout are disjoint in exact text, speaker, voice,
rate, and audio hashes; the holdout phrases remain unknown before candidate
freeze. The v6 holdout is burned diagnostic data and must not be reused for
acceptance decisions; see
`evaluation/checkpoints/synthetic_v6_holdout_burned_diagnostic.md`.

The additive `v8` specs in `specs/dev_v8.json` and `specs/holdout_v8.json`
evaluate safety utterances as a closed command mode. Both splits realize the
same complete, pre-frozen phrase allow-list from
`catalogs/safety_commands_closed_v1.json`; their utterance IDs, speakers,
voices, rates, and generated audio remain disjoint. Every safety manifest clip
contains `expected_command_id`. Alphanumeric and medium/long open-dictation
utterances remain separate categories with split-disjoint text. No ASR output
is used to select any audio or manifest entry.

The additive `v9` specs retain the exact frozen v8 phrase catalog and add an
open-set safety check. Each split has six metadata-paired, text-disjoint
out-of-catalog negatives covering negations, counter-commands, and acoustic
near-misses. They carry category `safety_negative_ood` and an explicit null
`expected_command_id` through the build, clip, stream, and Short-Latency
manifests. Positive catalog commands remain unchanged; open-dictation short,
medium, and long material remains separate.

## Dry-run planning

Planning validates both specs, split isolation, the build ID, and destination.
It does not invoke speech synthesis and does not create files:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py plan \
  --split dev --build-id synthetic_de_v2-dev-001 --spec-version v2
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py plan \
  --split holdout --build-id synthetic_de_v2-holdout-001 --spec-version v2
```

## Generation

Generate development data first:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v2-dev-001 --spec-version v2
```

Holdout generation requires an explicit acknowledgement because the completed
directory is immediately sealed and must never be tuned or repaired in place:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v2-holdout-001 \
  --spec-version v2 --confirm-holdout-seal
```

Generate v3 only into new build IDs:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v3-dev-001 --spec-version v3
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v3-holdout-001 \
  --spec-version v3 --confirm-holdout-seal
```

Generate v4 only into new build IDs:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v4-dev-001 --spec-version v4
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v4-holdout-001 \
  --spec-version v4 --confirm-holdout-seal
```

Generate v5 only into new build IDs:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v5-dev-001 --spec-version v5
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v5-holdout-001 \
  --spec-version v5 --confirm-holdout-seal
```

Generate v6 only into new build IDs:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v6-dev-001 --spec-version v6
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v6-holdout-001 \
  --spec-version v6 --confirm-holdout-seal
```

Generate v7 only into new build IDs after freezing the catalog and target
policy. Generation does not run ASR or select audio from ASR output:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v7-dev-001 --spec-version v7
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v7-holdout-001 \
  --spec-version v7 --confirm-holdout-seal
```

Generate v8 only after the complete closed-command phrase catalog is frozen:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v8-dev-001 --spec-version v8
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v8-holdout-001 \
  --spec-version v8 --confirm-holdout-seal
```

Generate v9 without changing the frozen catalog:

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split dev --build-id synthetic_de_v9-dev-001 --spec-version v9
```

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py build \
  --split holdout --build-id synthetic_de_v9-holdout-001 \
  --spec-version v9 --confirm-holdout-seal
```

Do not generate the holdout until target metrics and evaluation policy have been
frozen. Do not listen to or inspect holdout hypotheses while tuning.

## Verification

```bash
backend/.venv/bin/python evaluation/synthesis_v2/generate.py verify \
  evaluation/generated/synthetic_v2/dev/synthetic_de_v2-dev-001
```

For holdout builds, verification checks both `manifest.json` and
`HOLDOUT_SEAL.json`.

Run the generator tests without creating audio:

```bash
backend/.venv/bin/python -m pytest -q evaluation/synthesis_v2/tests
```

## Generated layout

```text
<build>/
  source_aiff/                 original macOS say output
  parts/clean_untrimmed/       resampled PCM before end trimming
  parts/clean/                 trimmed, otherwise unfiltered PCM
  parts/intercom/              fixed intercom-filtered PCM
  audio/clean.wav              clean concatenated evaluation audio
  audio/intercom.wav           filtered concatenated evaluation audio
  references.jsonl             turn-level UTF-8 references
  reference.txt                ordered plain-text references
  manifest.json                provenance, timeline, metadata, hashes
  HOLDOUT_SEAL.json            holdout only
```
