# Human FLEURS holdout v2 and degraded counterpart

## Decision

The required source data was already available locally; no network access or
new download was needed. A new Human Holdout v2 and its deterministic degraded
counterpart were created and independently sealed before candidate freeze.
Neither suite has been used for ASR, selection, tuning, or hypothesis review.

## Local official sources and license

- Official German FLEURS test archive:
  `/private/tmp/fleurs_de_test.tar.gz`, SHA-256
  `e86b42dfcdef749926cd92135045f87c25966c09e50d01c401adb04ee7d8628f`.
- Official German test TSV: `/private/tmp/fleurs_de_test.tsv`, SHA-256
  `82fab72c58a347345675c238f2492bb997105a4ab45d69e2a2b34ed29082fa97`.
- Both hashes exactly match the source hashes recorded by the prior official
  test manifest; the TSV contains 862 structurally valid rows after the same
  four documented official quote-shape repairs.
- Reuse is recorded under `CC-BY-4.0` with attribution in
  `evaluation/data/LICENSES/FLEURS.md`, SHA-256
  `50b475051a1b22d9d694e542c8918c10313ac5d664dc7edeb4e2ae5f44e41cd4`.
  This establishes the local license and attribution basis. It does not make a
  new claim about individual participant consent beyond the official FLEURS
  dataset provenance.

## Selection and isolation

- Dataset: `fleurs_de_test_holdout_v2`, 12 unmodified official test WAVs.
- Metadata-only selection chose four short, four medium, and four long rows by
  numeric sentence ID and filename after excluding every `audio_id`, filename,
  FLEURS sentence ID, and audio SHA-256 already used by:
  - `fleurs_de_dev_v1.json`, SHA-256
    `dadfac0ee4be3470eb817e1841a3779a900a94561390cf07a3cd613e469b9052`;
  - burned `fleurs_de_test_holdout_v1.json`, SHA-256
    `c0ad5717ba6a2c5e6e9ef223c8f83bae21063cb84bce065da2e327d38a5c64db`.
- The four required identity/hash intersections are all empty. All 12 selected
  sentence IDs and audio hashes are unique.
- ASR outputs used for selection: `false`.
- The combined byte-binding hash of the 12 copied raw files is
  `c2acd63499e5dc8903c445330be99bbc98cf88d53f3eed82cb41924388b79c89`.
- The aggregate binding of the 24 pre-existing Dev v1 and burned Holdout v1
  raw files remained unchanged at
  `10e010b4a1028199e5dcca541a0b38ea181b46882c723e12bd000d59b47193ef`.

## Reference and audio QA

- Each raw and normalized reference exactly equals its selected official TSV
  row; IDs, filenames, word counts, and frame counts are exact source bindings.
- Every copied WAV is byte-identical to its `test/<filename>` archive member.
- All reference fields are non-empty UTF-8. Audio/transcript agreement was not
  manually listened to, and the manifest states that limitation explicitly.
- All 12 files are mono 16 kHz WAV/FLOAT, finite and unclipped. Total duration
  is 185.58 seconds; clip duration range is 4.44 to 46.50 seconds. Peak range is
  -25.0953 to -3.8283 dBFS and RMS range is -43.4308 to -23.5688 dBFS.
- The supplied test metadata labels all 862 source rows as `MALE`; no missing
  demographic balance was invented.

## Human holdout hashes

| Artifact | SHA-256 |
|---|---|
| `evaluation/data/manifests/fleurs_de_test_holdout_v2.json` | `493b440cedfb6978f868bc52aee5ae02d16dd3cf5631b1eb05d361073ebe607f` |
| `evaluation/data/manifests/fleurs_de_test_holdout_v2.seal.json` | `e6eae8113de3e3f03a4480840599278785c823c8498958095a84be9a213773d7` |
| Sealed canonical clip set | `b0be385dacbbab37dbfa0957d9132ab6f240b424cd4a244c4ac9e7642c02f203` |
| Importer `evaluation/import_fleurs_holdout_v2.py` | `0337c99bd90235f9e2387ded811d9f6d8e67f9ad4541563a703ffaea417d65dd` |

The importer refuses any overwrite once one v2 destination exists. Seal
verification rejects changed manifests or audio, missing/added files, links,
and non-regular entries.

## Deterministic degraded counterpart

- Dataset:
  `evaluation/generated/degraded_v1/fleurs_de_test_holdout_v2-degraded-v1-3d62a12152ef`.
- 60 derived PCM16 mono 16 kHz files: exactly 12 each for broadband noise,
  ambient noise, telephone 8 kHz roundtrip, bounded soft overdrive, and low
  gain. All are finite and format-valid.
- Base seed: `2026071301`.
- Configuration SHA-256:
  `3d62a12152ef8a029ef20030999a9720c2db1c350eb1d5caba1eec0363e58e53`.
- Generator SHA-256:
  `c6e65ae391ca8d7c2672184bf0956418e77c7854d3be76e046002ae7d96af4a5`.
- Every derived record binds the exact parent ID/hash, reference, per-profile
  seed, parameters, measured values, configuration, generator, and parent seal.
- All 60 output hashes are unique and disjoint from the 12 parent audio hashes.

| Artifact | SHA-256 |
|---|---|
| Degraded manifest | `2cf43c8dd2a56681279839b7248a54cc429ac395c51d414cfd22f8a2aa8fb47a` |
| Degraded `HOLDOUT_SEAL.json` | `2bd97ab96095584f2a72728a991f01787adc163cbe813e30d80298f668553d40` |

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q \
  tests/test_fleurs_holdout_v2_artifacts.py \
  evaluation/degradation_v1/tests \
  tests/test_fleurs_import.py

PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python \
  evaluation/degradation_v1/generate.py verify \
  evaluation/generated/degraded_v1/fleurs_de_test_holdout_v2-degraded-v1-3d62a12152ef
```

Result: 22 tests passed. No ASR was run. Both holdouts remain sealed and must
stay unopened until a formal candidate freeze explicitly authorizes evaluation.
