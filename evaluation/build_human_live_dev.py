#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import wave


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
PAUSE_SECONDS = 0.65
PAUSE_FRAMES = 10_400
EXPECTED_CLIPS = 12
REVIEW_METHOD = "manual_audio_reference_review"


class HumanLiveBuildError(ValueError):
    """Raised when Human Dev evidence is not safe to build."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: object, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HumanLiveBuildError(f"{label} must be a valid SHA-256")
    return digest


def _safe_project_file(value: object, root: Path, label: str) -> Path:
    text = str(value or "").strip()
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts:
        raise HumanLiveBuildError(f"{label} must be a safe project-relative path")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HumanLiveBuildError(f"{label} escapes project root") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise HumanLiveBuildError(f"{label} is not a regular file: {text}")
    return resolved


def _safe_output_path(path: str | Path, root: Path, label: str) -> Path:
    candidate = Path(path)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HumanLiveBuildError(f"{label} must be inside project root") from exc
    if resolved.is_symlink():
        raise HumanLiveBuildError(f"{label} cannot be a symlink")
    return resolved


def _review_timestamp(value: object, label: str) -> str:
    timestamp = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanLiveBuildError(f"{label} must be an ISO-8601 timestamp") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise HumanLiveBuildError(f"{label} must use an explicit UTC offset")
    return timestamp


def _validate_reviewed_clip(clip: dict[str, Any], index: int) -> dict[str, str]:
    nested_reference = clip.get("reference") if isinstance(clip.get("reference"), dict) else {}
    text = str(clip.get("reference_text") or nested_reference.get("reference_text") or "").strip()
    status = str(
        clip.get("reference_status") or nested_reference.get("reference_status") or ""
    ).strip()
    normalized_status = status.lower().replace("-", "_")
    if not text:
        raise HumanLiveBuildError(f"Clip {index} has empty reference text")
    if "manually_reviewed" not in normalized_status or any(
        marker in normalized_status
        for marker in ("not_manually_reviewed", "unreviewed", "notreviewed", "pending")
    ):
        raise HumanLiveBuildError(
            f"Clip {index} reference_status is not fully manually reviewed: {status!r}"
        )
    provenance = clip.get("review_provenance")
    if not isinstance(provenance, dict):
        raise HumanLiveBuildError(f"Clip {index} lacks review_provenance")
    reviewer_id = str(provenance.get("reviewer_id") or "").strip()
    if not reviewer_id:
        raise HumanLiveBuildError(f"Clip {index} review_provenance lacks reviewer_id")
    method = str(provenance.get("method") or "").strip()
    if method != REVIEW_METHOD:
        raise HumanLiveBuildError(
            f"Clip {index} review method must be {REVIEW_METHOD!r}"
        )
    reviewed_at_utc = _review_timestamp(
        provenance.get("reviewed_at_utc"), f"Clip {index} reviewed_at_utc"
    )
    expected_text_hash = _valid_sha256(
        provenance.get("reference_text_sha256"),
        f"Clip {index} review reference_text_sha256",
    )
    actual_text_hash = _sha256_bytes(text.encode("utf-8"))
    if expected_text_hash != actual_text_hash:
        raise HumanLiveBuildError(
            f"Clip {index} review provenance does not bind its reference text"
        )
    return {
        "reference_text": text,
        "reference_status": status,
        "reviewer_id": reviewer_id,
        "reviewed_at_utc": reviewed_at_utc,
        "review_method": method,
        "reference_text_sha256": actual_text_hash,
    }


def _read_pcm16_mono_16k(path: Path, index: int) -> tuple[bytes, int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            frames = source.getnframes()
            if (
                channels != CHANNELS
                or sample_width != SAMPLE_WIDTH_BYTES
                or sample_rate != SAMPLE_RATE
                or compression != "NONE"
                or frames <= 0
            ):
                raise HumanLiveBuildError(
                    f"Clip {index} must be non-empty mono 16 kHz PCM16 WAV; got "
                    f"{channels}ch, {sample_rate} Hz, {sample_width * 8}-bit, {compression}"
                )
            raw_frames = source.readframes(frames)
            if len(raw_frames) != frames * CHANNELS * SAMPLE_WIDTH_BYTES:
                raise HumanLiveBuildError(f"Clip {index} PCM frame count is inconsistent")
            return raw_frames, frames
    except (wave.Error, EOFError) as exc:
        raise HumanLiveBuildError(f"Clip {index} is not a valid PCM WAV: {path}") from exc


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _render_wav(raw_frames: bytes) -> bytes:
    with tempfile.SpooledTemporaryFile() as handle:
        with wave.open(handle, "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH_BYTES)
            output.setframerate(SAMPLE_RATE)
            output.setcomptype("NONE", "not compressed")
            output.writeframes(raw_frames)
        handle.seek(0)
        return handle.read()


def build_human_live_dev(
    source_manifest: str | Path,
    output_audio: str | Path,
    output_manifest: str | Path,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source_path = Path(source_manifest)
    source_path = (
        (root / source_path).resolve() if not source_path.is_absolute() else source_path.resolve()
    )
    try:
        source_path.relative_to(root)
    except ValueError as exc:
        raise HumanLiveBuildError("Source manifest must be inside project root") from exc
    if not source_path.is_file() or source_path.is_symlink():
        raise HumanLiveBuildError("Source manifest must be a regular file")
    source_bytes = source_path.read_bytes()
    try:
        source = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HumanLiveBuildError("Source manifest is not valid UTF-8 JSON") from exc
    if not isinstance(source, dict):
        raise HumanLiveBuildError("Source manifest root must be an object")
    usage = str(source.get("usage") or source.get("split") or "").lower()
    official_split = str(source.get("official_split") or source.get("split") or "").lower()
    dataset_name = str(source.get("dataset_name") or "").strip().lower()
    dataset_id = str(source.get("dataset_id") or "").strip()
    if source.get("is_holdout") is True or usage not in {"dev", "development"}:
        raise HumanLiveBuildError("Source must be an explicit non-holdout Dev manifest")
    if official_split not in {"dev", "development"}:
        raise HumanLiveBuildError("Source official_split must be Dev")
    if dataset_name != "fleurs" or "fleurs" not in dataset_id.lower():
        raise HumanLiveBuildError("Source must be a FLEURS Human Dev manifest")
    clips = source.get("clips")
    if not isinstance(clips, list) or len(clips) != EXPECTED_CLIPS:
        raise HumanLiveBuildError(f"Source must contain exactly {EXPECTED_CLIPS} clips")

    # Review every reference before resolving or reading any audio path. This
    # makes an unreviewed manifest a safe, side-effect-free reject.
    reviewed = [_validate_reviewed_clip(clip, index) for index, clip in enumerate(clips, 1)]

    validated: list[dict[str, Any]] = []
    seen_audio_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for index, (clip, review) in enumerate(zip(clips, reviewed), 1):
        audio_id = str(clip.get("audio_id") or clip.get("id") or "").strip()
        if not audio_id or audio_id in seen_audio_ids:
            raise HumanLiveBuildError(f"Clip {index} has missing or duplicate audio_id")
        seen_audio_ids.add(audio_id)
        path = _safe_project_file(
            clip.get("data_path") or clip.get("path"), root, f"Clip {index} audio path"
        )
        relative_parts = {part.lower() for part in path.relative_to(root).parts}
        if path.suffix.lower() != ".wav" or not {"raw", "human"}.issubset(relative_parts):
            raise HumanLiveBuildError(
                f"Clip {index} must reference a raw Human WAV inside the project"
            )
        expected_hash = _valid_sha256(clip.get("sha256"), f"Clip {index} audio sha256")
        actual_hash = _sha256_file(path)
        if actual_hash != expected_hash:
            raise HumanLiveBuildError(
                f"Clip {index} audio SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
            )
        if actual_hash in seen_hashes:
            raise HumanLiveBuildError(f"Clip {index} duplicates an earlier audio hash")
        seen_hashes.add(actual_hash)
        raw_frames, frame_count = _read_pcm16_mono_16k(path, index)
        validated.append(
            {
                "audio_id": audio_id,
                "path": path,
                "audio_sha256": actual_hash,
                "raw_frames": raw_frames,
                "frames": frame_count,
                **review,
            }
        )

    audio_path = _safe_output_path(output_audio, root, "Output audio")
    manifest_path = _safe_output_path(output_manifest, root, "Output manifest")
    source_artifacts = {source_path, *(item["path"] for item in validated)}
    if (
        audio_path == manifest_path
        or audio_path in source_artifacts
        or manifest_path in source_artifacts
    ):
        raise HumanLiveBuildError("Output paths must not overwrite source artifacts")

    pause_bytes = b"\x00" * (PAUSE_FRAMES * CHANNELS * SAMPLE_WIDTH_BYTES)
    combined_parts: list[bytes] = []
    turns: list[dict[str, Any]] = []
    cursor = 0
    for index, item in enumerate(validated):
        start_frame = cursor
        end_frame = start_frame + item["frames"]
        combined_parts.append(item["raw_frames"])
        turns.append(
            {
                "turn_index": index + 1,
                "audio_id": item["audio_id"],
                "text": item["reference_text"],
                "reference_status": item["reference_status"],
                "review_provenance": {
                    "reviewer_id": item["reviewer_id"],
                    "reviewed_at_utc": item["reviewed_at_utc"],
                    "method": item["review_method"],
                    "reference_text_sha256": item["reference_text_sha256"],
                },
                "source_audio_sha256": item["audio_sha256"],
                "start_frame": start_frame,
                "end_frame": end_frame,
                "start_seconds": start_frame / SAMPLE_RATE,
                "end_seconds": end_frame / SAMPLE_RATE,
            }
        )
        cursor = end_frame
        if index < len(validated) - 1:
            combined_parts.append(pause_bytes)
            cursor += PAUSE_FRAMES
    wav_bytes = _render_wav(b"".join(combined_parts))
    audio_hash = _sha256_bytes(wav_bytes)
    manifest = {
        "schema_version": 1,
        "fixture_id": f"{dataset_id}-human-live-reviewed-v1",
        "dataset_family": "Human",
        "usage": "development",
        "split": "dev",
        "is_holdout": False,
        "source_manifest": {
            "path": source_path.relative_to(root).as_posix(),
            "sha256": _sha256_bytes(source_bytes),
        },
        "audio_path": audio_path.relative_to(root).as_posix(),
        "audio_sha256": audio_hash,
        "audio_format": {
            "container": "WAV",
            "subtype": "PCM_16",
            "channels": CHANNELS,
            "sample_rate_hz": SAMPLE_RATE,
            "frames": cursor,
        },
        "composition": {
            "policy": "source PCM frames copied byte-exactly in manifest order",
            "clip_count": EXPECTED_CLIPS,
            "pause_seconds": PAUSE_SECONDS,
            "pause_frames": PAUSE_FRAMES,
            "pause_count": EXPECTED_CLIPS - 1,
            "resampling": False,
        },
        "review_provenance": {
            "policy": REVIEW_METHOD,
            "all_references_manually_reviewed": True,
            "statuses": sorted({item["reference_status"] for item in validated}),
            "reviewers": sorted({item["reviewer_id"] for item in validated}),
        },
        "turns": turns,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(audio_path, wav_bytes)
    _atomic_write_bytes(manifest_path, manifest_bytes)
    return {
        "audio_path": audio_path.relative_to(root).as_posix(),
        "audio_sha256": audio_hash,
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "clips": EXPECTED_CLIPS,
        "frames": cursor,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build hash-bound reviewed Human FLEURS Dev live-stream evidence."
    )
    parser.add_argument("source_manifest")
    parser.add_argument("output_audio")
    parser.add_argument("output_manifest")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    args = parser.parse_args()
    try:
        result = build_human_live_dev(
            args.source_manifest,
            args.output_audio,
            args.output_manifest,
            project_root=args.project_root,
        )
    except (HumanLiveBuildError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
