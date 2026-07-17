#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

import soundfile as sf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_IDS = {
    "dev": "fleurs_de_dev_v1",
    "test": "fleurs_de_test_holdout_v1",
}
DATASET_ID = DATASET_IDS["dev"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "data" / "raw" / "human" / DATASET_ID
DEFAULT_MANIFEST = PROJECT_ROOT / "evaluation" / "data" / "manifests" / f"{DATASET_ID}.json"
EXPECTED_COUNT = 12
COUNT_PER_BUCKET = 4
BUCKETS = ("short", "medium", "long")
GENDER_ORDER = ("FEMALE", "MALE", "OTHER")
WAV_NAME_RE = re.compile(r"[0-9]+\.wav\Z")
MAX_ARCHIVE_MEMBERS = 100_000
MAX_WAV_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class FleursRow:
    sentence_id: str
    audio_filename: str
    raw_transcription: str
    normalized_transcription: str
    phonemes: str
    sample_count: int
    gender: str

    @property
    def word_count(self) -> int:
        return len(self.normalized_transcription.split())

    @property
    def length_bucket(self) -> str:
        if self.word_count <= 10:
            return "short"
        if self.word_count <= 20:
            return "medium"
        return "long"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_metadata_with_repairs(path: Path) -> tuple[list[FleursRow], list[dict[str, int | str]]]:
    rows: list[FleursRow] = []
    repairs: list[dict[str, int | str]] = []
    seen_audio: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for line_number, fields in enumerate(reader, start=1):
            if (
                len(fields) == 6
                and fields[3].count("\t") == 1
                and fields[4].isdigit()
                and fields[5].strip().upper() in GENDER_ORDER
            ):
                normalized, phonemes = fields[3].split("\t", 1)
                fields = [fields[0], fields[1], fields[2], normalized, phonemes, fields[4], fields[5]]
                repairs.append(
                    {
                        "line": line_number,
                        "audio_filename": fields[1],
                        "reason": "official TSV quote anomaly joined normalized text and phonemes",
                    }
                )
            if len(fields) != 7:
                raise ValueError(f"TSV line {line_number}: expected 7 columns, got {len(fields)}")
            sentence_id, filename, raw, normalized, phonemes, samples, gender = fields
            if not sentence_id.isdigit():
                raise ValueError(f"TSV line {line_number}: invalid sentence ID {sentence_id!r}")
            if not WAV_NAME_RE.fullmatch(filename) or PurePosixPath(filename).name != filename:
                raise ValueError(f"TSV line {line_number}: unsafe WAV filename {filename!r}")
            if filename in seen_audio:
                raise ValueError(f"TSV line {line_number}: duplicate WAV filename {filename!r}")
            if not raw.strip() or not normalized.strip() or not phonemes.strip():
                raise ValueError(f"TSV line {line_number}: empty transcription metadata")
            try:
                sample_count = int(samples)
            except ValueError as exc:
                raise ValueError(f"TSV line {line_number}: invalid sample count {samples!r}") from exc
            if sample_count <= 0:
                raise ValueError(f"TSV line {line_number}: sample count must be positive")
            normalized_gender = gender.strip().upper()
            if normalized_gender not in GENDER_ORDER:
                raise ValueError(f"TSV line {line_number}: unsupported gender {gender!r}")
            rows.append(
                FleursRow(
                    sentence_id=sentence_id,
                    audio_filename=filename,
                    raw_transcription=raw.strip(),
                    normalized_transcription=normalized.strip(),
                    phonemes=phonemes.strip(),
                    sample_count=sample_count,
                    gender=normalized_gender,
                )
            )
            seen_audio.add(filename)
    if not rows:
        raise ValueError("FLEURS TSV is empty")
    return rows, repairs


def load_metadata(path: Path) -> list[FleursRow]:
    rows, _repairs = load_metadata_with_repairs(path)
    return rows


def select_rows(rows: list[FleursRow]) -> list[FleursRow]:
    """Select four sentence-disjoint clips per length bucket without ASR feedback."""
    selected: list[FleursRow] = []
    used_sentence_ids: set[str] = set()

    for bucket in BUCKETS:
        candidates = sorted(
            (row for row in rows if row.length_bucket == bucket),
            key=lambda row: (int(row.sentence_id), row.audio_filename),
        )
        genders = [gender for gender in GENDER_ORDER if any(row.gender == gender for row in candidates)]
        bucket_selected: list[FleursRow] = []
        while len(bucket_selected) < COUNT_PER_BUCKET:
            made_progress = False
            for gender in genders:
                candidate = next(
                    (
                        row
                        for row in candidates
                        if row.gender == gender and row.sentence_id not in used_sentence_ids
                    ),
                    None,
                )
                if candidate is None:
                    continue
                bucket_selected.append(candidate)
                used_sentence_ids.add(candidate.sentence_id)
                made_progress = True
                if len(bucket_selected) == COUNT_PER_BUCKET:
                    break
            if not made_progress:
                raise ValueError(
                    f"Not enough unique sentence IDs in {bucket!r} bucket; "
                    f"need {COUNT_PER_BUCKET}"
                )
        selected.extend(bucket_selected)

    if len(selected) != EXPECTED_COUNT or len(used_sentence_ids) != EXPECTED_COUNT:
        raise AssertionError("Deterministic FLEURS selection did not produce 12 unique sentences")
    return selected


def safe_tar_members(
    archive: tarfile.TarFile,
    official_split: str = "dev",
) -> dict[str, tarfile.TarInfo]:
    members = archive.getmembers()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError(f"Archive has too many members: {len(members)}")
    safe: dict[str, tarfile.TarInfo] = {}
    for member in members:
        name = member.name
        path = PurePosixPath(name)
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"Unsafe archive member path: {name!r}")
        if name in safe:
            raise ValueError(f"Duplicate archive member path: {name!r}")
        if member.isdir():
            if path.parts != (official_split,):
                raise ValueError(f"Unexpected archive directory: {name!r}")
        elif member.isfile():
            if (
                len(path.parts) != 2
                or path.parts[0] != official_split
                or not WAV_NAME_RE.fullmatch(path.parts[1])
            ):
                raise ValueError(f"Unexpected archive file: {name!r}")
            if member.size <= 0 or member.size > MAX_WAV_BYTES:
                raise ValueError(f"Unsafe WAV size for {name!r}: {member.size}")
        else:
            raise ValueError(f"Archive links and special files are forbidden: {name!r}")
        safe[name] = member
    return safe


def wav_metadata(data: bytes, expected_frames: int, filename: str) -> dict[str, int | float | str]:
    try:
        with sf.SoundFile(io.BytesIO(data), mode="r") as audio:
            channels = audio.channels
            sample_rate = audio.samplerate
            frame_count = audio.frames
            container_format = audio.format
            subtype = audio.subtype
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid WAV data for {filename!r}: {exc}") from exc
    if container_format != "WAV" or subtype not in {"PCM_16", "FLOAT"}:
        raise ValueError(
            f"Unsupported WAV encoding for {filename!r}: {container_format}/{subtype}"
        )
    if channels != 1 or sample_rate != 16_000:
        raise ValueError(
            f"Unexpected WAV format for {filename!r}: "
            f"{channels}ch, {subtype}, {sample_rate}Hz"
        )
    if frame_count != expected_frames:
        raise ValueError(
            f"Frame count mismatch for {filename!r}: TSV={expected_frames}, WAV={frame_count}"
        )
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_format": subtype,
        "sample_width_bytes": 2 if subtype == "PCM_16" else 4,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate,
    }


def split_paths(official_split: str) -> tuple[str, Path, Path, Path | None]:
    if official_split not in DATASET_IDS:
        raise ValueError(f"Unsupported official FLEURS split: {official_split!r}")
    dataset_id = DATASET_IDS[official_split]
    output_dir = PROJECT_ROOT / "evaluation" / "data" / "raw" / "human" / dataset_id
    manifest_path = PROJECT_ROOT / "evaluation" / "data" / "manifests" / f"{dataset_id}.json"
    seal_path = (
        PROJECT_ROOT / "evaluation" / "data" / "manifests" / f"{dataset_id}.seal.json"
        if official_split == "test"
        else None
    )
    return dataset_id, output_dir, manifest_path, seal_path


def _canonical_clip_set(clips: list[dict]) -> list[dict]:
    return sorted(
        (
            {
                "filename": clip["fleurs_audio_filename"],
                "sha256": clip["sha256"],
                "byte_size": clip["byte_size"],
            }
            for clip in clips
        ),
        key=lambda item: item["filename"],
    )


def write_holdout_seal(
    manifest: dict,
    manifest_path: Path,
    output_dir: Path,
    seal_path: Path,
) -> dict:
    expected_clips = _canonical_clip_set(manifest["clips"])
    expected_names = {clip["filename"] for clip in expected_clips}
    entries = list(output_dir.iterdir())
    actual_names = {entry.name for entry in entries}
    if actual_names != expected_names:
        raise ValueError(
            "Holdout seal file set mismatch before sealing: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"additional={sorted(actual_names - expected_names)}"
        )
    invalid_entries = sorted(
        entry.name for entry in entries if entry.is_symlink() or not entry.is_file()
    )
    if invalid_entries:
        raise ValueError(f"Holdout seal rejects non-regular files: {invalid_entries}")

    clip_set_bytes = json.dumps(
        expected_clips,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    seal = {
        "schema_version": 1,
        "seal_type": "transcom-fleurs-holdout-v1",
        "dataset_id": manifest["dataset_id"],
        "official_split": "test",
        "usage": "holdout",
        "is_holdout": True,
        "manifest_filename": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "clip_count": len(expected_clips),
        "clip_set_sha256": sha256_bytes(clip_set_bytes),
        "clips": expected_clips,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return seal


def verify_holdout_seal(manifest_path: Path, output_dir: Path, seal_path: Path) -> dict:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("seal_type") != "transcom-fleurs-holdout-v1":
        raise ValueError("Holdout seal type mismatch")
    if sha256_file(manifest_path) != seal.get("manifest_sha256"):
        raise ValueError("Holdout seal manifest hash mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("usage") != "holdout" or manifest.get("is_holdout") is not True:
        raise ValueError("Holdout seal manifest metadata mismatch")
    if (
        manifest.get("dataset_id") != seal.get("dataset_id")
        or manifest.get("official_split") != "test"
        or seal.get("official_split") != "test"
        or seal.get("usage") != "holdout"
        or seal.get("is_holdout") is not True
    ):
        raise ValueError("Holdout seal identity mismatch")
    manifest_clips = _canonical_clip_set(manifest.get("clips", []))
    if manifest_clips != seal.get("clips"):
        raise ValueError("Holdout seal clip metadata mismatch")
    sealed_clip_set_bytes = json.dumps(
        seal["clips"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if sha256_bytes(sealed_clip_set_bytes) != seal.get("clip_set_sha256"):
        raise ValueError("Holdout seal clip set hash mismatch")

    expected = {clip["filename"]: clip for clip in manifest_clips}
    entries = list(output_dir.iterdir())
    actual_names = {entry.name for entry in entries}
    if actual_names != set(expected):
        raise ValueError(
            "Holdout seal file set mismatch: "
            f"missing={sorted(set(expected) - actual_names)}, "
            f"additional={sorted(actual_names - set(expected))}"
        )
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(f"Holdout seal rejects non-regular file: {entry.name!r}")
        expected_clip = expected[entry.name]
        if entry.stat().st_size != expected_clip["byte_size"]:
            raise ValueError(f"Holdout seal byte size mismatch: {entry.name!r}")
        if sha256_file(entry) != expected_clip["sha256"]:
            raise ValueError(f"Holdout seal clip hash mismatch: {entry.name!r}")
    return seal


def import_fleurs(
    archive_path: Path,
    metadata_path: Path,
    output_dir: Path | None = None,
    manifest_path: Path | None = None,
    official_split: str = "dev",
    seal_path: Path | None = None,
) -> dict:
    dataset_id, default_output, default_manifest, default_seal = split_paths(official_split)
    output_dir = output_dir or default_output
    manifest_path = manifest_path or default_manifest
    if official_split == "test":
        seal_path = seal_path or default_seal
        assert seal_path is not None
    elif seal_path is not None:
        raise ValueError("A holdout seal is only valid for the official test split")
    usage = "holdout" if official_split == "test" else "development"
    is_holdout = official_split == "test"
    archive_path = archive_path.resolve()
    metadata_path = metadata_path.resolve()
    rows, metadata_repairs = load_metadata_with_repairs(metadata_path)
    selected = select_rows(rows)
    metadata_by_filename = {row.audio_filename: row for row in rows}

    output_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = safe_tar_members(archive, official_split=official_split)
        archive_wavs = {PurePosixPath(name).name for name, member in members.items() if member.isfile()}
        missing_from_archive = sorted(set(metadata_by_filename) - archive_wavs)
        unexpected_in_archive = sorted(archive_wavs - set(metadata_by_filename))
        if missing_from_archive or unexpected_in_archive:
            raise ValueError(
                "Archive/TSV filename mismatch: "
                f"missing={missing_from_archive[:3]}, unexpected={unexpected_in_archive[:3]}"
            )

        for row in selected:
            member_name = f"{official_split}/{row.audio_filename}"
            member = members[member_name]
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Could not read archive member {member_name!r}")
            data = extracted.read()
            if len(data) != member.size:
                raise ValueError(f"Truncated archive member {member_name!r}")
            audio_meta = wav_metadata(data, row.sample_count, row.audio_filename)
            destination = output_dir / row.audio_filename
            destination.write_bytes(data)
            clips.append(
                {
                    "audio_id": Path(row.audio_filename).stem,
                    "fleurs_sentence_id": row.sentence_id,
                    "fleurs_audio_filename": row.audio_filename,
                    "official_split": official_split,
                    "usage": usage,
                    "gender": row.gender,
                    "reference_text": row.raw_transcription,
                    "normalized_reference_text": row.normalized_transcription,
                    "reference_status": "official_fleurs_metadata_not_manually_reviewed",
                    "word_count": row.word_count,
                    "length_bucket": row.length_bucket,
                    "archive_member": member_name,
                    "data_path": f"evaluation/data/raw/human/{dataset_id}/{row.audio_filename}",
                    "sha256": sha256_bytes(data),
                    "byte_size": len(data),
                    **audio_meta,
                }
            )

    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "dataset_name": "FLEURS",
        "dataset_configuration": "de_de",
        "language": "de-DE",
        "official_split": official_split,
        "usage": usage,
        "is_holdout": is_holdout,
        "reference_policy": "Official FLEURS TSV text; not yet manually reviewed by TransCom.",
        "source": {
            "archive_filename": archive_path.name,
            "archive_sha256": sha256_file(archive_path),
            "metadata_filename": metadata_path.name,
            "metadata_sha256": sha256_file(metadata_path),
            "source_row_count": len(rows),
        },
        "selection": {
            "algorithm": "metadata-only-v1: 4 unique sentence IDs per word-count bucket, gender round-robin when available, then numeric sentence ID and filename",
            "selected_count": len(clips),
            "unique_sentence_ids": len({clip["fleurs_sentence_id"] for clip in clips}),
            "length_buckets": {bucket: sum(clip["length_bucket"] == bucket for clip in clips) for bucket in BUCKETS},
            "source_gender_counts": dict(sorted(Counter(row.gender for row in rows).items())),
            "selected_gender_counts": dict(sorted(Counter(clip["gender"] for clip in clips).items())),
            "gender_limitation": (
                f"The supplied official {official_split} TSV contains only MALE labels; both genders could not be selected."
                if len({row.gender for row in rows}) == 1
                else None
            ),
            "asr_outputs_used_for_selection": False,
        },
        "license": {
            "spdx_id": "CC-BY-4.0",
            "url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution_file": "evaluation/data/LICENSES/FLEURS.md",
        },
        "clips": clips,
    }
    if metadata_repairs:
        manifest["source"]["metadata_repairs"] = metadata_repairs
    if is_holdout:
        assert seal_path is not None
        manifest["holdout_seal"] = {
            "required": True,
            "path": f"evaluation/data/manifests/{seal_path.name}",
        }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if is_holdout:
        assert seal_path is not None
        write_holdout_seal(manifest, manifest_path, output_dir, seal_path)
        verify_holdout_seal(manifest_path, output_dir, seal_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a deterministic German FLEURS subset.")
    parser.add_argument("--official-split", choices=("dev", "test"), default="dev")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    _, default_output, default_manifest, default_seal = split_paths(args.official_split)
    archive = args.archive or Path(f"/tmp/fleurs_de_{args.official_split}.tar.gz")
    metadata = args.metadata or Path(f"/tmp/fleurs_de_{args.official_split}.tsv")
    output_dir = args.output_dir or default_output
    manifest_path = args.manifest or default_manifest
    seal_path = args.seal or default_seal
    manifest = import_fleurs(
        archive,
        metadata,
        output_dir,
        manifest_path,
        official_split=args.official_split,
        seal_path=seal_path,
    )
    print(
        json.dumps(
            {
                "dataset_id": manifest["dataset_id"],
                "selected_count": manifest["selection"]["selected_count"],
                "official_split": manifest["official_split"],
                "usage": manifest["usage"],
                "manifest": str(manifest_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "seal": str(seal_path.resolve()) if seal_path else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
