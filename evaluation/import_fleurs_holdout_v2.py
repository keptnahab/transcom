#!/usr/bin/env python3
"""Create a sealed, metadata-only selected FLEURS human holdout v2.

The importer reads only local official FLEURS archive/TSV files, excludes every
ID and audio hash already present in the v1 Dev and burned v1 Holdout manifests,
copies selected WAV bytes unchanged, and never runs ASR.
"""

from __future__ import annotations

from collections import Counter
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.import_fleurs import (
    BUCKETS,
    COUNT_PER_BUCKET,
    FleursRow,
    load_metadata_with_repairs,
    safe_tar_members,
    sha256_bytes,
    sha256_file,
    verify_holdout_seal,
    wav_metadata,
    write_holdout_seal,
)


DATASET_ID = "fleurs_de_test_holdout_v2"
OUTPUT_DIR = PROJECT_ROOT / "evaluation/data/raw/human" / DATASET_ID
MANIFEST_PATH = PROJECT_ROOT / "evaluation/data/manifests" / f"{DATASET_ID}.json"
SEAL_PATH = PROJECT_ROOT / "evaluation/data/manifests" / f"{DATASET_ID}.seal.json"
EXCLUSION_MANIFESTS = (
    PROJECT_ROOT / "evaluation/data/manifests/fleurs_de_dev_v1.json",
    PROJECT_ROOT / "evaluation/data/manifests/fleurs_de_test_holdout_v1.json",
)


def load_exclusions(manifest_paths: tuple[Path, ...]) -> tuple[dict[str, set[str]], list[dict]]:
    excluded = {
        "audio_ids": set(),
        "filenames": set(),
        "sentence_ids": set(),
        "audio_sha256": set(),
    }
    provenance = []
    for path in manifest_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        clips = payload.get("clips")
        if not isinstance(clips, list) or not clips:
            raise ValueError(f"Exclusion manifest has no clips: {path}")
        for clip in clips:
            data_path = PROJECT_ROOT / str(clip["data_path"])
            if not data_path.is_file() or sha256_file(data_path) != clip["sha256"]:
                raise ValueError(f"Exclusion clip binding failed: {data_path}")
            excluded["audio_ids"].add(str(clip["audio_id"]))
            excluded["filenames"].add(str(clip["fleurs_audio_filename"]))
            excluded["sentence_ids"].add(str(clip["fleurs_sentence_id"]))
            excluded["audio_sha256"].add(str(clip["sha256"]))
        provenance.append(
            {
                "dataset_id": payload["dataset_id"],
                "path": path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": sha256_file(path),
                "clip_count": len(clips),
            }
        )
    return excluded, provenance


def select_unused_rows(
    rows: list[FleursRow],
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    excluded: dict[str, set[str]],
) -> list[tuple[FleursRow, bytes, dict]]:
    selected: list[tuple[FleursRow, bytes, dict]] = []
    selected_sentence_ids: set[str] = set()
    selected_filenames: set[str] = set()
    selected_hashes: set[str] = set()
    for bucket in BUCKETS:
        bucket_selected = 0
        candidates = sorted(
            (row for row in rows if row.length_bucket == bucket),
            key=lambda row: (int(row.sentence_id), row.audio_filename),
        )
        for row in candidates:
            audio_id = Path(row.audio_filename).stem
            if (
                audio_id in excluded["audio_ids"]
                or row.audio_filename in excluded["filenames"]
                or row.sentence_id in excluded["sentence_ids"]
                or row.sentence_id in selected_sentence_ids
                or row.audio_filename in selected_filenames
            ):
                continue
            member_name = f"test/{row.audio_filename}"
            member = members[member_name]
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Could not read archive member {member_name!r}")
            data = extracted.read()
            if len(data) != member.size:
                raise ValueError(f"Truncated archive member {member_name!r}")
            digest = sha256_bytes(data)
            if digest in excluded["audio_sha256"] or digest in selected_hashes:
                continue
            audio_meta = wav_metadata(data, row.sample_count, row.audio_filename)
            selected.append((row, data, audio_meta))
            selected_sentence_ids.add(row.sentence_id)
            selected_filenames.add(row.audio_filename)
            selected_hashes.add(digest)
            bucket_selected += 1
            if bucket_selected == COUNT_PER_BUCKET:
                break
        if bucket_selected != COUNT_PER_BUCKET:
            raise ValueError(
                f"Not enough unused and hash-disjoint rows in {bucket!r}: "
                f"selected {bucket_selected}, need {COUNT_PER_BUCKET}"
            )
    return selected


def build_holdout_v2(
    archive_path: Path,
    metadata_path: Path,
    output_dir: Path = OUTPUT_DIR,
    manifest_path: Path = MANIFEST_PATH,
    seal_path: Path = SEAL_PATH,
) -> dict:
    for destination in (output_dir, manifest_path, seal_path):
        if destination.exists():
            raise ValueError(f"Refusing to overwrite existing v2 artifact: {destination}")
    archive_path = archive_path.resolve()
    metadata_path = metadata_path.resolve()
    rows, repairs = load_metadata_with_repairs(metadata_path)
    excluded, exclusion_provenance = load_exclusions(EXCLUSION_MANIFESTS)

    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = safe_tar_members(archive, official_split="test")
        archive_wavs = {
            PurePosixPath(name).name for name, member in members.items() if member.isfile()
        }
        metadata_wavs = {row.audio_filename for row in rows}
        if archive_wavs != metadata_wavs:
            raise ValueError("Official test archive and TSV filename sets differ")
        selected = select_unused_rows(rows, archive, members, excluded)

    staging = output_dir.parent / f".{DATASET_ID}.tmp-{uuid.uuid4().hex}"
    if staging.exists():
        raise ValueError(f"Unexpected staging collision: {staging}")
    staging.mkdir(parents=True)
    clips = []
    try:
        for row, data, audio_meta in selected:
            (staging / row.audio_filename).write_bytes(data)
            clips.append(
                {
                    "audio_id": Path(row.audio_filename).stem,
                    "fleurs_sentence_id": row.sentence_id,
                    "fleurs_audio_filename": row.audio_filename,
                    "official_split": "test",
                    "usage": "holdout",
                    "gender": row.gender,
                    "reference_text": row.raw_transcription,
                    "normalized_reference_text": row.normalized_transcription,
                    "reference_status": "official_fleurs_tsv_structurally_verified_not_audio_manually_reviewed",
                    "word_count": row.word_count,
                    "length_bucket": row.length_bucket,
                    "archive_member": f"test/{row.audio_filename}",
                    "data_path": f"evaluation/data/raw/human/{DATASET_ID}/{row.audio_filename}",
                    "sha256": sha256_bytes(data),
                    "byte_size": len(data),
                    **audio_meta,
                }
            )

        manifest = {
            "schema_version": 1,
            "dataset_id": DATASET_ID,
            "dataset_name": "FLEURS",
            "dataset_configuration": "de_de",
            "language": "de-DE",
            "official_split": "test",
            "usage": "holdout",
            "is_holdout": True,
            "reference_policy": (
                "Official FLEURS TSV raw and normalized text, UTF-8 and source-row "
                "binding structurally verified; audio/transcript agreement not manually reviewed."
            ),
            "reference_validation": {
                "metadata_rows_parsed": len(rows),
                "selected_rows_exactly_bound_to_tsv": True,
                "all_reference_fields_nonempty": True,
                "all_audio_frame_counts_match_tsv": True,
                "manual_audio_transcript_review": False,
            },
            "source": {
                "archive_filename": archive_path.name,
                "archive_sha256": sha256_file(archive_path),
                "metadata_filename": metadata_path.name,
                "metadata_sha256": sha256_file(metadata_path),
                "source_row_count": len(rows),
                "local_cache_used": True,
            },
            "selection": {
                "algorithm": (
                    "metadata-only-v2: exclude every v1 Dev/burned-Holdout audio ID, "
                    "filename, sentence ID and SHA-256; then take the first four "
                    "hash-disjoint rows per word-count bucket by numeric sentence ID "
                    "and filename"
                ),
                "selected_count": len(clips),
                "unique_sentence_ids": len({clip["fleurs_sentence_id"] for clip in clips}),
                "length_buckets": {
                    bucket: sum(clip["length_bucket"] == bucket for clip in clips)
                    for bucket in BUCKETS
                },
                "source_gender_counts": dict(sorted(Counter(row.gender for row in rows).items())),
                "selected_gender_counts": dict(sorted(Counter(clip["gender"] for clip in clips).items())),
                "gender_limitation": (
                    "The supplied official test TSV contains only MALE labels; "
                    "gender-balanced selection is unavailable."
                ),
                "asr_outputs_used_for_selection": False,
                "excluded_manifests": exclusion_provenance,
                "disjoint_fields": [
                    "audio_id",
                    "fleurs_audio_filename",
                    "fleurs_sentence_id",
                    "sha256",
                ],
            },
            "license": {
                "spdx_id": "CC-BY-4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution_file": "evaluation/data/LICENSES/FLEURS.md",
            },
            "holdout_seal": {
                "required": True,
                "path": f"evaluation/data/manifests/{seal_path.name}",
            },
            "clips": clips,
        }
        if repairs:
            manifest["source"]["metadata_repairs"] = repairs

        os.replace(staging, output_dir)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_holdout_seal(manifest, manifest_path, output_dir, seal_path)
        verify_holdout_seal(manifest_path, output_dir, seal_path)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        manifest_path.unlink(missing_ok=True)
        seal_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("/private/tmp/fleurs_de_test.tar.gz"))
    parser.add_argument("--metadata", type=Path, default=Path("/private/tmp/fleurs_de_test.tsv"))
    args = parser.parse_args()
    manifest = build_holdout_v2(args.archive, args.metadata)
    print(
        json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "selected_count": len(manifest["clips"]),
                "manifest": MANIFEST_PATH.relative_to(PROJECT_ROOT).as_posix(),
                "seal": SEAL_PATH.relative_to(PROJECT_ROOT).as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
