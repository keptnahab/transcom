from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from evaluation import benchmark_clip_suite
from evaluation import benchmark_oracle_segments
from evaluation import benchmark_streaming_latency
from evaluation.synthesis_v2 import generate as synthesis


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = PROJECT_ROOT / "evaluation/data/manifests"
BUILD_ROOTS = {
    "dev": PROJECT_ROOT
    / "evaluation/generated/synthetic_v2/dev/synthetic_de_v7-dev-001",
    "holdout": PROJECT_ROOT
    / "evaluation/generated/synthetic_v2/holdout/synthetic_de_v7-holdout-001",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _maximum_true_run(mask: np.ndarray) -> int:
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return max((int(end - start) for start, end in zip(starts, ends)), default=0)


def test_v7_builds_and_holdout_seal_are_byte_verified() -> None:
    assert synthesis.verify_build(BUILD_ROOTS["dev"]) == []
    assert synthesis.verify_build(BUILD_ROOTS["holdout"]) == []
    assert synthesis.verify_holdout_seal(BUILD_ROOTS["holdout"]) == []

    holdout = _json(BUILD_ROOTS["holdout"] / "manifest.json")
    assert holdout["split"] == "holdout"
    assert holdout["holdout_sealed"] is True
    assert holdout["configuration"]["spec_version"] == "v7"
    assert holdout["configuration"]["pause_frames"] == 10_400
    assert holdout["configuration"]["trailing_guard_ms"] == 0


def test_v7_audio_qa_guards_v6_tts_failure_modes() -> None:
    for split, build_root in BUILD_ROOTS.items():
        manifest = _json(build_root / "manifest.json")
        assert len(manifest["utterances"]) == 16
        for utterance in manifest["utterances"]:
            variants = {}
            for variant in ("clean", "intercom"):
                path = build_root / utterance["paths"][variant]
                info = sf.info(path)
                assert info.channels == 1
                assert info.samplerate == 16_000
                assert info.subtype == "PCM_16"
                assert info.frames > 0

                samples, sample_rate = sf.read(path, dtype="int16", always_2d=False)
                assert sample_rate == 16_000
                assert samples.ndim == 1
                assert np.isfinite(samples).all()
                assert not np.any((samples == -32_768) | (samples == 32_767))

                normalized = samples.astype(np.float64) / 32_768.0
                peak_dbfs = 20 * math.log10(float(np.max(np.abs(normalized))))
                rms_dbfs = 20 * math.log10(
                    float(np.sqrt(np.mean(normalized * normalized)))
                )
                assert -40.0 < peak_dbfs < -0.1
                assert -40.0 < rms_dbfs < -10.0
                variants[variant] = samples

            assert len(variants["clean"]) == len(variants["intercom"])

            clean = variants["clean"]
            assert synthesis.final_frame_is_active(
                build_root / utterance["paths"]["clean"]
            )
            assert _maximum_true_run(clean == 0) < int(0.25 * 16_000)
            framed = clean[: len(clean) // 160 * 160].astype(np.float64).reshape(-1, 160)
            frame_rms = np.sqrt(np.mean((framed / 32_768.0) ** 2, axis=1))
            assert _maximum_true_run(frame_rms < 10 ** (-50 / 20)) < 50

        timeline = [
            (int(item["start_frame"]), int(item["end_frame"]))
            for item in manifest["utterances"]
        ]
        for variant in ("clean", "intercom"):
            assert synthesis.verify_sample_exact_pauses(
                build_root / "audio" / f"{variant}.wav", timeline, 10_400
            ) == []


def test_v7_clip_stream_and_short_manifests_bind_exact_parent_data() -> None:
    for split, build_root in BUILD_ROOTS.items():
        parent_path = build_root / "manifest.json"
        parent = _json(parent_path)
        parent_hash = _sha256(parent_path)

        for variant in ("clean", "intercom"):
            clip_path = MANIFEST_ROOT / f"synthetic_v7_{split}_{variant}_v1.json"
            payload, clips = benchmark_clip_suite._validate_manifest(
                clip_path, PROJECT_ROOT
            )
            assert len(clips) == 16
            assert payload["source_manifest_sha256"] == parent_hash
            assert [item["manifest_clip"]["id"] for item in clips] == [
                item["id"] for item in parent["utterances"]
            ]
            assert [item["reference_text"] for item in clips] == [
                item["text"] for item in parent["utterances"]
            ]
            if split == "holdout":
                seal = payload["source_holdout_seal"]
                assert _sha256(PROJECT_ROOT / seal["path"]) == seal["sha256"]

        stream_path = MANIFEST_ROOT / f"synthetic_v7_{split}_intercom_stream_v1.json"
        stream_raw = _json(stream_path)
        stream, audio_path, _audio_hash = benchmark_oracle_segments._load_bound_audio(
            stream_path, PROJECT_ROOT / stream_raw["audio_file"]
        )
        assert stream["parent_manifest_sha256"] == parent_hash
        if split == "holdout":
            seal = stream["source_holdout_seal"]
            assert _sha256(PROJECT_ROOT / seal["path"]) == seal["sha256"]
        samples, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
        assert sample_rate == 16_000
        assert len(stream["turns"]) == 16
        for index, (turn, utterance) in enumerate(
            zip(stream["turns"], parent["utterances"]), start=1
        ):
            start, end, start_frame, end_frame = (
                benchmark_oracle_segments._turn_bounds(
                    turn, index, sample_rate, len(samples)
                )
            )
            assert turn["id"] == utterance["id"]
            assert turn["text"] == utterance["text"]
            assert start == utterance["start_seconds"]
            assert end == utterance["end_seconds"]
            assert start_frame == utterance["start_frame"]
            assert end_frame == utterance["end_frame"]

        short_path = MANIFEST_ROOT / f"synthetic_v7_short_latency_{split}_v1.json"
        short_fixture, short_clips = benchmark_streaming_latency._validate_fixture(
            short_path, PROJECT_ROOT
        )
        expected_short = [
            item for item in parent["utterances"] if "short" in item["categories"]
        ]
        assert short_fixture["source_manifest_sha256"] == parent_hash
        if split == "holdout":
            seal = short_fixture["source_holdout_seal"]
            assert _sha256(PROJECT_ROOT / seal["path"]) == seal["sha256"]
        assert len(short_clips) == len(expected_short) == 10
        assert [item["clip"]["id"] for item in short_clips] == [
            item["id"] for item in expected_short
        ]
        assert sum(
            "safety" in item["clip"]["categories"] for item in short_clips
        ) == 6
        assert sum(
            "alphanumeric" in item["clip"]["categories"] for item in short_clips
        ) == 4


def test_v7_isolation_catalog_and_group_structure_are_hash_bound() -> None:
    dev = _json(BUILD_ROOTS["dev"] / "manifest.json")
    holdout = _json(BUILD_ROOTS["holdout"] / "manifest.json")
    for field in ("id", "speaker", "voice", "rate", "text"):
        assert {item[field] for item in dev["utterances"]}.isdisjoint(
            item[field] for item in holdout["utterances"]
        )
    assert {
        item["sha256"] for item in dev["artifacts"] if "audio" in item
    }.isdisjoint(
        item["sha256"] for item in holdout["artifacts"] if "audio" in item
    )

    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4", "v5", "v6")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    assert prior_texts.isdisjoint(
        item["text"].casefold()
        for manifest in (dev, holdout)
        for item in manifest["utterances"]
    )

    catalog_record = dev["provenance"]["safety_catalog"]
    assert catalog_record == holdout["provenance"]["safety_catalog"]
    assert _sha256(PROJECT_ROOT / catalog_record["path"]) == catalog_record["sha256"]
    catalog = _json(PROJECT_ROOT / catalog_record["path"])
    assert "phrases" not in catalog
    assert "utterances" not in catalog
    assert catalog["split_policy"]["selection_uses_asr_output"] is False

    groups = _json(MANIFEST_ROOT / "evaluation_v7_groups_v1.json")
    assert set(groups["group_policy"]["groups"]) == {
        "human",
        "synthetic",
        "degraded",
    }
    assert groups["group_policy"]["unchanged_from_prior_suite"] is True
    for split in ("dev", "holdout"):
        assert set(groups["splits"][split]) == {"human", "synthetic", "degraded"}
        for group in groups["splits"][split].values():
            for record in group:
                assert _sha256(PROJECT_ROOT / record["path"]) == record["sha256"]
                if "seal" in record:
                    assert (
                        _sha256(PROJECT_ROOT / record["seal"]["path"])
                        == record["seal"]["sha256"]
                    )
