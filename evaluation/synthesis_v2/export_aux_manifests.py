#!/usr/bin/env python3
"""Export hash-bound stream and short-latency manifests without running ASR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.export_synthetic_v2_clip_manifest import (
    atomic_write_identical_or_new,
    canonical_json_bytes,
    load_and_verify_build,
    sha256_file,
)


def _project_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_aux_manifests(
    parent_path: Path,
    expected_parent_sha256: str,
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict, dict]:
    root = project_root.resolve()
    parent_path = parent_path.resolve()
    parent, parent_hash, artifacts, seal = load_and_verify_build(
        parent_path, "intercom", expected_parent_sha256, root
    )
    split = str(parent["split"])
    build_root = parent_path.parent
    combined_record = artifacts.get("audio/intercom.wav")
    if not isinstance(combined_record, dict):
        raise ValueError("Build has no bound combined intercom audio")
    combined_path = build_root / "audio/intercom.wav"
    if sha256_file(combined_path) != combined_record["sha256"]:
        raise ValueError("Combined intercom audio hash mismatch")

    turns = []
    short_clips = []
    for utterance in parent["utterances"]:
        turn = {
            "id": utterance["id"],
            "start_seconds": utterance["start_seconds"],
            "end_seconds": utterance["end_seconds"],
            "text": utterance["text"],
        }
        if "command_id" in utterance:
            turn["expected_command_id"] = utterance["command_id"]
        elif "expected_command_id" in utterance:
            turn["expected_command_id"] = utterance["expected_command_id"]
        for key in ("negative_case_id", "negative_type"):
            if key in utterance:
                turn[key] = utterance[key]
        turns.append(turn)

        if "short" not in utterance["categories"]:
            continue
        relative = utterance["paths"]["intercom"]
        artifact = artifacts.get(relative)
        if not isinstance(artifact, dict) or not isinstance(
            artifact.get("audio"), dict
        ):
            raise ValueError(f"Missing bound intercom artifact for {utterance['id']}")
        audio_path = build_root / relative
        clip = {
            "id": utterance["id"],
            "data_path": _project_relative(audio_path, root),
            "sha256": artifact["sha256"],
            "speech_end_seconds": artifact["audio"]["duration_seconds"],
            "reference_text": utterance["text"],
            "categories": utterance["categories"],
        }
        if "command_id" in utterance:
            clip["expected_command_id"] = utterance["command_id"]
        elif "expected_command_id" in utterance:
            clip["expected_command_id"] = utterance["expected_command_id"]
        for key in ("negative_case_id", "negative_type"):
            if key in utterance:
                clip[key] = utterance[key]
        short_clips.append(clip)

    version = str(parent["dataset_version"]).removeprefix("synthetic_de_")
    stream = {
        "schema_version": 1,
        "dataset_id": f"synthetic_{version}_{split}_intercom_stream_v1",
        "dataset_name": f"Synthetic German closed-command {version} intercom stream",
        "language": parent["language"],
        "split": split,
        "usage": split,
        "is_holdout": split == "holdout",
        "audio_file": _project_relative(combined_path, root),
        "audio_sha256": combined_record["sha256"],
        "parent_manifest": _project_relative(parent_path, root),
        "parent_manifest_sha256": parent_hash,
        "reference_status": "synthetic_v2_spec_not_manually_reviewed",
        "selection": "All v8 turns in source order; no ASR output used.",
        "turns": turns,
    }
    short = {
        "schema_version": 1,
        "fixture_id": f"synthetic_{version}_short_latency_{split}_v1",
        "split": split,
        "usage": split,
        "is_holdout": split == "holdout",
        "source_manifest": _project_relative(parent_path, root),
        "source_manifest_sha256": parent_hash,
        "variant": "intercom",
        "selection": (
            f"All synthetic {version} utterances tagged short, including the complete "
            "closed-command catalog; no ASR output used for selection."
        ),
        "clips": short_clips,
    }
    if seal is not None:
        stream["source_holdout_seal"] = seal
        short["source_holdout_seal"] = seal
    return stream, short


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_manifest", type=Path)
    parser.add_argument("--expected-build-sha256", required=True)
    parser.add_argument("--stream-output", required=True, type=Path)
    parser.add_argument("--short-output", required=True, type=Path)
    args = parser.parse_args()
    stream, short = build_aux_manifests(
        args.parent_manifest, args.expected_build_sha256
    )
    stream_status = atomic_write_identical_or_new(
        args.stream_output, canonical_json_bytes(stream)
    )
    short_status = atomic_write_identical_or_new(
        args.short_output, canonical_json_bytes(short)
    )
    print(
        json.dumps(
            {
                "stream_status": stream_status,
                "stream_sha256": sha256_file(args.stream_output),
                "short_status": short_status,
                "short_sha256": sha256_file(args.short_output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
