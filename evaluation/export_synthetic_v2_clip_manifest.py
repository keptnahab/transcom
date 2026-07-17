#!/usr/bin/env python3
"""Export verified synthetic_v2 builds as benchmark clip manifests.

The exporter never reads, copies, converts, or rewrites audio payloads. It only
validates the existing build and emits project-relative, hash-bound references.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.synthesis_v2 import generate as synthesis


VARIANTS = ("clean", "intercom")
LENGTH_BUCKETS = {"short", "medium", "long"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REFERENCE_STATUS = "synthetic_v2_spec_not_manually_reviewed"


class ExportError(RuntimeError):
    """Raised when provenance, integrity, or write-safety checks fail."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _project_relative(path: Path, project_root: Path, label: str) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise ExportError(f"{label} is outside project root: {resolved}") from exc


def _safe_build_path(build_root: Path, value: object, label: str) -> tuple[str, Path]:
    text = str(value or "").strip()
    relative = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ExportError(f"Unsafe {label}: {text!r}")
    resolved = (build_root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(build_root.resolve())
    except ValueError as exc:
        raise ExportError(f"{label} escapes build root: {text!r}") from exc
    return relative.as_posix(), resolved


def _artifact_map(manifest: Mapping[str, Any]) -> dict[str, dict]:
    records: dict[str, dict] = {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ExportError("Build manifest has no artifacts")
    for index, raw in enumerate(artifacts, start=1):
        if not isinstance(raw, dict):
            raise ExportError(f"Artifact {index} must be an object")
        path = str(raw.get("path") or "")
        digest = str(raw.get("sha256") or "").lower()
        if path in records:
            raise ExportError(f"Duplicate artifact path: {path!r}")
        if not SHA256_RE.fullmatch(digest):
            raise ExportError(f"Artifact {index} has invalid SHA-256")
        if not isinstance(raw.get("bytes"), int) or raw["bytes"] <= 0:
            raise ExportError(f"Artifact {index} has invalid byte size")
        records[path] = raw
    return records


def _length_bucket(categories: object, utterance_id: str) -> tuple[list[str], str]:
    if not isinstance(categories, list) or not categories:
        raise ExportError(f"Utterance {utterance_id!r} has no categories")
    normalized = [str(item).strip() for item in categories]
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise ExportError(f"Utterance {utterance_id!r} has invalid categories")
    buckets = [item for item in normalized if item in LENGTH_BUCKETS]
    if len(buckets) != 1:
        raise ExportError(
            f"Utterance {utterance_id!r} must have exactly one length category"
        )
    return normalized, buckets[0]


def load_and_verify_build(
    manifest_path: Path,
    variant: str,
    expected_parent_sha256: str,
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict, str, dict[str, dict], dict | None]:
    if variant not in VARIANTS:
        raise ExportError(f"Unsupported variant: {variant!r}")
    manifest_path = manifest_path.expanduser().resolve()
    if manifest_path.name != "manifest.json" or not manifest_path.is_file():
        raise ExportError(f"Expected an existing synthetic_v2 manifest.json: {manifest_path}")
    _project_relative(manifest_path, project_root, "Build manifest")

    before = manifest_path.read_bytes()
    parent_hash = sha256_bytes(before)
    expected_parent_sha256 = str(expected_parent_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected_parent_sha256):
        raise ExportError("Expected build manifest SHA-256 is invalid or missing")
    if parent_hash != expected_parent_sha256:
        raise ExportError(
            "Build manifest SHA-256 mismatch: "
            f"expected {expected_parent_sha256}, got {parent_hash}"
        )
    try:
        manifest = json.loads(before.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"Invalid build manifest JSON: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "2.0":
        raise ExportError("Unsupported synthetic_v2 build manifest schema")
    split = str(manifest.get("split") or "")
    if split not in {"dev", "holdout"}:
        raise ExportError(f"Unsupported synthetic_v2 split: {split!r}")
    if split == "holdout" and manifest.get("holdout_sealed") is not True:
        raise ExportError("Holdout build is not marked sealed")
    if split == "dev" and manifest.get("holdout_sealed") not in {False, None}:
        raise ExportError("Development build is incorrectly marked as sealed holdout")

    build_root = manifest_path.parent
    verification_errors = synthesis.verify_build(build_root)
    if verification_errors:
        raise ExportError("Build verification failed: " + "; ".join(verification_errors))
    after_hash = sha256_file(manifest_path)
    if after_hash != parent_hash:
        raise ExportError("Build manifest changed during verification")

    artifacts = _artifact_map(manifest)
    for artifact_path, record in artifacts.items():
        safe_relative, resolved = _safe_build_path(build_root, artifact_path, "artifact path")
        if safe_relative != artifact_path:
            raise ExportError(f"Non-canonical artifact path: {artifact_path!r}")
        if not resolved.is_file():
            raise ExportError(f"Missing artifact: {artifact_path!r}")
        if resolved.stat().st_size != record["bytes"]:
            raise ExportError(f"Artifact size mismatch: {artifact_path!r}")
        if sha256_file(resolved) != record["sha256"]:
            raise ExportError(f"Artifact hash mismatch: {artifact_path!r}")

    seal_record = None
    if split == "holdout":
        seal_path = build_root / "HOLDOUT_SEAL.json"
        if not seal_path.is_file():
            raise ExportError("Holdout build is missing HOLDOUT_SEAL.json")
        seal_errors = synthesis.verify_holdout_seal(build_root)
        if seal_errors:
            raise ExportError("Holdout seal verification failed: " + "; ".join(seal_errors))
        seal_record = {
            "path": _project_relative(seal_path, project_root, "Holdout seal"),
            "sha256": sha256_file(seal_path),
        }
    return manifest, parent_hash, artifacts, seal_record


def build_clip_manifest(
    build_manifest_path: str | Path,
    variant: str,
    expected_parent_sha256: str,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> dict:
    root = Path(project_root).expanduser().resolve()
    parent_path = Path(build_manifest_path).expanduser().resolve()
    parent, parent_hash, artifacts, seal_record = load_and_verify_build(
        parent_path,
        variant,
        expected_parent_sha256,
        root,
    )
    split = str(parent["split"])
    usage = str(parent.get("usage", split))
    if "usage" in parent and usage != str(parent["usage"]):
        raise ExportError("Build usage changed during normalization")
    utterances = parent.get("utterances")
    if not isinstance(utterances, list) or not utterances:
        raise ExportError("Build manifest has no utterances")

    clips = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, utterance in enumerate(utterances, start=1):
        if not isinstance(utterance, dict):
            raise ExportError(f"Utterance {index} must be an object")
        utterance_id = str(utterance.get("id") or "").strip()
        if not utterance_id or utterance_id in seen_ids:
            raise ExportError(f"Invalid or duplicate utterance id: {utterance_id!r}")
        reference = str(utterance.get("text") or "").strip()
        speaker = str(utterance.get("speaker") or "").strip()
        voice = str(utterance.get("voice") or "").strip()
        role = str(utterance.get("role") or "").strip()
        if not reference or not speaker or not voice or not role:
            raise ExportError(f"Utterance {utterance_id!r} lacks reference/speaker/voice/role")
        categories, length_bucket = _length_bucket(
            utterance.get("categories"), utterance_id
        )
        paths = utterance.get("paths")
        if not isinstance(paths, dict) or variant not in paths:
            raise ExportError(f"Utterance {utterance_id!r} lacks variant {variant!r}")
        artifact_path, resolved = _safe_build_path(
            parent_path.parent,
            paths[variant],
            f"{variant} path for {utterance_id}",
        )
        if artifact_path in seen_paths:
            raise ExportError(f"Duplicate clip artifact path: {artifact_path!r}")
        artifact = artifacts.get(artifact_path)
        if artifact is None:
            raise ExportError(f"Clip is not bound by artifacts: {artifact_path!r}")
        audio = artifact.get("audio")
        if not isinstance(audio, dict):
            raise ExportError(f"Clip artifact lacks audio metadata: {artifact_path!r}")
        if (
            audio.get("channels") != 1
            or audio.get("sample_rate") != 16_000
            or not isinstance(audio.get("frames"), int)
            or audio["frames"] <= 0
        ):
            raise ExportError(f"Clip artifact has invalid audio metadata: {artifact_path!r}")
        actual_hash = sha256_file(resolved)
        if actual_hash != artifact["sha256"]:
            raise ExportError(f"Clip hash changed after build verification: {artifact_path!r}")

        clip = {
            "audio_id": utterance_id,
            "id": utterance_id,
            "data_path": _project_relative(resolved, root, "Clip audio"),
            "sha256": actual_hash,
            "byte_size": artifact["bytes"],
            "audio_frames": audio["frames"],
            "audio_seconds": audio.get("duration_seconds"),
            "sample_rate_hz": audio["sample_rate"],
            "channels": audio["channels"],
            "reference_text": reference,
            "reference_status": REFERENCE_STATUS,
            "categories": categories,
            "length_bucket": length_bucket,
            "speaker_id": speaker,
            "speaker_name": speaker,
            "voice": voice,
            "role": role,
            "variant": variant,
            "official_split": split,
            "usage": usage,
            "parent_artifact_path": artifact_path,
            "parent_manifest_sha256": parent_hash,
        }
        if "command_id" in utterance:
            command_id = str(utterance.get("command_id") or "").strip()
            if not command_id:
                raise ExportError(
                    f"Utterance {utterance_id!r} has an empty command_id"
                )
            clip["expected_command_id"] = command_id
        elif "expected_command_id" in utterance:
            if utterance["expected_command_id"] is not None:
                raise ExportError(
                    f"Utterance {utterance_id!r} has an unsupported expected_command_id"
                )
            clip["expected_command_id"] = None
        for metadata_key in ("negative_case_id", "negative_type"):
            if metadata_key in utterance:
                value = str(utterance.get(metadata_key) or "").strip()
                if not value:
                    raise ExportError(
                        f"Utterance {utterance_id!r} has empty {metadata_key}"
                    )
                clip[metadata_key] = value
        for source_key, target_key in (
            ("start_seconds", "speech_start_seconds"),
            ("end_seconds", "speech_end_seconds"),
        ):
            if source_key in utterance:
                clip[target_key] = utterance[source_key]
        clips.append(clip)
        seen_ids.add(utterance_id)
        seen_paths.add(artifact_path)

    parent_relative = _project_relative(parent_path, root, "Build manifest")
    dataset_id = f"{parent['dataset_id']}-{variant}-clips-v1"
    result = {
        "schema_version": 1,
        "adapter": "synthetic_v2-to-benchmark-clip-suite-v1",
        "dataset_id": dataset_id,
        "fixture_id": dataset_id,
        "dataset_name": "Synthetic German evaluation data v2",
        "language": parent.get("language"),
        "split": split,
        "usage": usage,
        "official_split": split,
        "is_holdout": split == "holdout",
        "variant": variant,
        "clip_count": len(clips),
        "selection": "All synthetic_v2 utterances in source order; no ASR output used.",
        "source_manifest": parent_relative,
        "source_manifest_sha256": parent_hash,
        "parent_manifest_sha256": parent_hash,
        "clips": clips,
    }
    if seal_record is not None:
        result["source_holdout_seal"] = seal_record
    return result


def atomic_write_identical_or_new(path: Path, data: bytes) -> str:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise ExportError(f"Refusing non-regular output path: {path}")
        if path.read_bytes() == data:
            return "unchanged"
        raise ExportError(f"Refusing to overwrite non-identical output: {path}")

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_file() and not path.is_symlink() and path.read_bytes() == data:
                return "unchanged"
            raise ExportError(f"Refusing to overwrite concurrently created output: {path}")
        return "created"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_clip_manifest(
    build_manifest_path: str | Path,
    variant: str,
    output_path: str | Path,
    expected_parent_sha256: str,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> tuple[dict, str]:
    manifest = build_clip_manifest(
        build_manifest_path,
        variant,
        expected_parent_sha256,
        project_root=project_root,
    )
    status = atomic_write_identical_or_new(
        Path(output_path),
        canonical_json_bytes(manifest),
    )
    return manifest, status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export one verified synthetic_v2 variant for benchmark_clip_suite.py."
    )
    parser.add_argument("build_manifest", type=Path)
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-build-sha256", required=True)
    args = parser.parse_args()
    manifest, status = export_clip_manifest(
        args.build_manifest,
        args.variant,
        args.output,
        args.expected_build_sha256,
    )
    print(
        json.dumps(
            {
                "status": status,
                "output": str(args.output.expanduser().resolve()),
                "dataset_id": manifest["dataset_id"],
                "split": manifest["split"],
                "usage": manifest["usage"],
                "variant": manifest["variant"],
                "clip_count": manifest["clip_count"],
                "output_sha256": sha256_file(args.output.expanduser().resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
