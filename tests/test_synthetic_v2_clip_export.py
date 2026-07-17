from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from evaluation import benchmark_clip_suite
from evaluation.export_synthetic_v2_clip_manifest import (
    ExportError,
    canonical_json_bytes,
    export_clip_manifest,
    sha256_file,
)
from evaluation.synthesis_v2 import generate as synthesis


def _write_wav(path: Path, frequency: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    time = np.arange(3200, dtype=np.float64) / 16_000
    sf.write(path, 0.2 * np.sin(2 * np.pi * frequency * time), 16_000, subtype="PCM_16")


def _build(tmp_path: Path, split: str = "dev") -> tuple[Path, dict[str, str]]:
    build_id = f"synthetic-test-{split}-001"
    build_root = tmp_path / "generated" / split / build_id
    paths = {}
    for variant, frequency in (("clean", 440.0), ("intercom", 720.0)):
        for utterance_id, offset in ((f"{split}-001", 0.0), (f"{split}-002", 35.0)):
            path = build_root / "parts" / variant / f"{utterance_id}.wav"
            _write_wav(path, frequency + offset)
            paths[f"{variant}:{utterance_id}"] = path.relative_to(build_root).as_posix()
    utterances = [
        {
            "id": f"{split}-001",
            "speaker": "Lea",
            "voice": "Anna",
            "role": "Regie",
            "text": "Bühne frei?",
            "command_id": "safety_stage_clear",
            "categories": ["short", "command", "umlaut"],
            "paths": {
                "clean": paths[f"clean:{split}-001"],
                "intercom": paths[f"intercom:{split}-001"],
            },
            "start_seconds": 0.0,
            "end_seconds": 0.2,
        },
        {
            "id": f"{split}-002",
            "speaker": "Murat",
            "voice": "Eddy",
            "role": "Inspizienz",
            "text": "Die nächste Lichtmarke kommt in zwölf Sekunden.",
            "categories": ["medium", "number", "technical"],
            "paths": {
                "clean": paths[f"clean:{split}-002"],
                "intercom": paths[f"intercom:{split}-002"],
            },
            "start_seconds": 0.3,
            "end_seconds": 0.5,
        },
    ]
    artifacts = [
        synthesis.artifact_record(path, build_root)
        for path in sorted(build_root.rglob("*.wav"))
    ]
    manifest = {
        "schema_version": "2.0",
        "dataset_version": "synthetic_de_v2",
        "dataset_id": f"synthetic_de_v2-{split}-{build_id}",
        "split": split,
        "usage": split,
        "build_id": build_id,
        "holdout_sealed": split == "holdout",
        "language": "de-DE",
        "utterances": utterances,
        "artifacts": artifacts,
    }
    manifest_path = build_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    if split == "holdout":
        synthesis.write_holdout_seal(build_root)
    return manifest_path, paths


@pytest.mark.parametrize("variant", ["clean", "intercom"])
def test_exports_both_variants_without_copying_audio(tmp_path: Path, variant: str) -> None:
    parent_path, paths = _build(tmp_path, split="dev")
    before = {
        path.relative_to(tmp_path).as_posix(): (sha256_file(path), path.stat().st_mtime_ns)
        for path in parent_path.parent.rglob("*.wav")
    }
    output = tmp_path / "manifests" / f"dev-{variant}.json"

    exported, status = export_clip_manifest(
        parent_path,
        variant,
        output,
        sha256_file(parent_path),
        project_root=tmp_path,
    )

    assert status == "created"
    assert exported["split"] == "dev"
    assert exported["usage"] == "dev"
    assert exported["official_split"] == "dev"
    assert exported["is_holdout"] is False
    assert exported["variant"] == variant
    assert exported["clip_count"] == 2
    assert all(clip["variant"] == variant for clip in exported["clips"])
    assert all(clip["parent_manifest_sha256"] == exported["parent_manifest_sha256"] for clip in exported["clips"])
    assert [clip["categories"] for clip in exported["clips"]] == [
        ["short", "command", "umlaut"],
        ["medium", "number", "technical"],
    ]
    assert exported["clips"][0]["expected_command_id"] == "safety_stage_clear"
    assert "expected_command_id" not in exported["clips"][1]
    assert [clip["length_bucket"] for clip in exported["clips"]] == ["short", "medium"]
    assert [clip["speaker_name"] for clip in exported["clips"]] == ["Lea", "Murat"]
    assert [clip["voice"] for clip in exported["clips"]] == ["Anna", "Eddy"]
    assert all(clip["reference_status"] == "synthetic_v2_spec_not_manually_reviewed" for clip in exported["clips"])
    assert {clip["parent_artifact_path"] for clip in exported["clips"]} == {
        paths[f"{variant}:dev-001"],
        paths[f"{variant}:dev-002"],
    }
    payload, validated = benchmark_clip_suite._validate_manifest(output, tmp_path)
    assert payload == exported
    assert len(validated) == 2
    assert before == {
        path.relative_to(tmp_path).as_posix(): (sha256_file(path), path.stat().st_mtime_ns)
        for path in parent_path.parent.rglob("*.wav")
    }

    repeated, repeated_status = export_clip_manifest(
        parent_path,
        variant,
        output,
        sha256_file(parent_path),
        project_root=tmp_path,
    )
    assert repeated == exported
    assert repeated_status == "unchanged"
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ExportError, match="Refusing to overwrite non-identical"):
        export_clip_manifest(
            parent_path,
            variant,
            output,
            sha256_file(parent_path),
            project_root=tmp_path,
        )


def test_rejects_tampered_build_artifact_before_export(tmp_path: Path) -> None:
    parent_path, _paths = _build(tmp_path, split="dev")
    artifact = parent_path.parent / "parts" / "clean" / "dev-001.wav"
    with artifact.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ExportError, match="Build verification failed"):
        export_clip_manifest(
            parent_path,
            "clean",
            tmp_path / "manifest.json",
            sha256_file(parent_path),
            project_root=tmp_path,
        )


def test_rejects_unexpected_build_manifest_hash(tmp_path: Path) -> None:
    parent_path, _paths = _build(tmp_path, split="dev")

    with pytest.raises(ExportError, match="Build manifest SHA-256 mismatch"):
        export_clip_manifest(
            parent_path,
            "clean",
            tmp_path / "manifest.json",
            "0" * 64,
            project_root=tmp_path,
        )


def test_holdout_split_and_usage_are_preserved_and_seal_is_required(tmp_path: Path) -> None:
    parent_path, _paths = _build(tmp_path, split="holdout")
    output = tmp_path / "holdout-clips.json"

    exported, status = export_clip_manifest(
        parent_path,
        "intercom",
        output,
        sha256_file(parent_path),
        project_root=tmp_path,
    )

    assert status == "created"
    assert exported["split"] == "holdout"
    assert exported["usage"] == "holdout"
    assert exported["official_split"] == "holdout"
    assert exported["is_holdout"] is True
    assert exported["source_holdout_seal"]["sha256"] == sha256_file(
        parent_path.parent / "HOLDOUT_SEAL.json"
    )
    assert all(clip["official_split"] == "holdout" for clip in exported["clips"])
    assert all(clip["usage"] == "holdout" for clip in exported["clips"])

    (parent_path.parent / "HOLDOUT_SEAL.json").unlink()
    with pytest.raises(ExportError, match="Build verification failed"):
        export_clip_manifest(
            parent_path,
            "intercom",
            tmp_path / "second.json",
            sha256_file(parent_path),
            project_root=tmp_path,
        )
