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


ROOT = Path(__file__).resolve().parents[3]
MANIFESTS = ROOT / "evaluation/data/manifests"
BUILDS = {
    split: ROOT
    / f"evaluation/generated/synthetic_v2/{split}/synthetic_de_v8-{split}-001"
    for split in ("dev", "holdout")
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _longest(mask: np.ndarray) -> int:
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return max((int(end - start) for start, end in zip(starts, ends)), default=0)


def test_v8_build_and_seal_integrity() -> None:
    assert synthesis.verify_build(BUILDS["dev"]) == []
    assert synthesis.verify_build(BUILDS["holdout"]) == []
    assert synthesis.verify_holdout_seal(BUILDS["holdout"]) == []
    holdout = _json(BUILDS["holdout"] / "manifest.json")
    assert holdout["holdout_sealed"] is True
    assert holdout["configuration"]["spec_version"] == "v8"
    assert holdout["configuration"]["pause_frames"] == 10_400
    assert holdout["provenance"]["safety_catalog"]["sha256"] == (
        "70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190"
    )


def test_v8_audio_qa_and_tts_silence_guards() -> None:
    for build in BUILDS.values():
        parent = _json(build / "manifest.json")
        assert len(parent["utterances"]) == 18
        timeline = []
        for utterance in parent["utterances"]:
            timeline.append((utterance["start_frame"], utterance["end_frame"]))
            variants = {}
            for variant in ("clean", "intercom"):
                path = build / utterance["paths"][variant]
                info = sf.info(path)
                assert (info.channels, info.samplerate, info.subtype) == (
                    1,
                    16_000,
                    "PCM_16",
                )
                samples, rate = sf.read(path, dtype="int16", always_2d=False)
                assert rate == 16_000 and samples.ndim == 1 and len(samples) > 0
                assert np.isfinite(samples).all()
                assert not np.any((samples == -32_768) | (samples == 32_767))
                scaled = samples.astype(np.float64) / 32_768.0
                peak = 20 * math.log10(float(np.max(np.abs(scaled))))
                rms = 20 * math.log10(float(np.sqrt(np.mean(scaled * scaled))))
                assert -40.0 < peak < -0.1
                assert -40.0 < rms < -10.0
                variants[variant] = samples
            assert len(variants["clean"]) == len(variants["intercom"])
            clean = variants["clean"]
            assert synthesis.final_frame_is_active(build / utterance["paths"]["clean"])
            assert _longest(clean == 0) < int(0.25 * 16_000)
            frames = clean[: len(clean) // 160 * 160].astype(np.float64).reshape(-1, 160)
            frame_rms = np.sqrt(np.mean((frames / 32_768.0) ** 2, axis=1))
            assert _longest(frame_rms < 10 ** (-50 / 20)) < 50
        for variant in ("clean", "intercom"):
            assert synthesis.verify_sample_exact_pauses(
                build / "audio" / f"{variant}.wav", timeline, 10_400
            ) == []


def test_v8_manifests_preserve_expected_command_ids_and_parent_bindings() -> None:
    for split, build in BUILDS.items():
        parent_path = build / "manifest.json"
        parent = _json(parent_path)
        parent_hash = _sha(parent_path)
        expected_commands = {
            item["id"]: item["command_id"]
            for item in parent["utterances"]
            if "command_id" in item
        }
        assert len(expected_commands) == 8

        for variant in ("clean", "intercom"):
            path = MANIFESTS / f"synthetic_v8_{split}_{variant}_v1.json"
            payload, clips = benchmark_clip_suite._validate_manifest(path, ROOT)
            assert len(clips) == 18
            assert payload["source_manifest_sha256"] == parent_hash
            observed = {
                item["manifest_clip"]["id"]: item["manifest_clip"][
                    "expected_command_id"
                ]
                for item in clips
                if "expected_command_id" in item["manifest_clip"]
            }
            assert observed == expected_commands

        stream_path = MANIFESTS / f"synthetic_v8_{split}_intercom_stream_v1.json"
        raw = _json(stream_path)
        stream, audio_path, _ = benchmark_oracle_segments._load_bound_audio(
            stream_path, ROOT / raw["audio_file"]
        )
        audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
        assert stream["parent_manifest_sha256"] == parent_hash
        assert len(stream["turns"]) == 18
        for index, (turn, utterance) in enumerate(
            zip(stream["turns"], parent["utterances"]), start=1
        ):
            bounds = benchmark_oracle_segments._turn_bounds(
                turn, index, sample_rate, len(audio)
            )
            assert turn["id"] == utterance["id"]
            assert turn["text"] == utterance["text"]
            assert bounds[2:] == (
                utterance["start_frame"],
                utterance["end_frame"],
            )
            assert turn.get("expected_command_id") == utterance.get("command_id")

        short_path = MANIFESTS / f"synthetic_v8_short_latency_{split}_v1.json"
        fixture, short = benchmark_streaming_latency._validate_fixture(
            short_path, ROOT
        )
        expected_short = [
            item for item in parent["utterances"] if "short" in item["categories"]
        ]
        assert fixture["source_manifest_sha256"] == parent_hash
        assert len(short) == len(expected_short) == 12
        assert sum("safety" in item["clip"]["categories"] for item in short) == 8
        assert sum(
            "alphanumeric" in item["clip"]["categories"] for item in short
        ) == 4
        observed = {
            item["clip"]["id"]: item["clip"]["expected_command_id"]
            for item in short
            if "expected_command_id" in item["clip"]
        }
        assert observed == expected_commands

        if split == "holdout":
            for payload in (
                _json(MANIFESTS / f"synthetic_v8_{split}_clean_v1.json"),
                _json(MANIFESTS / f"synthetic_v8_{split}_intercom_v1.json"),
                stream,
                fixture,
            ):
                seal = payload["source_holdout_seal"]
                assert _sha(ROOT / seal["path"]) == seal["sha256"]


def test_v8_split_audio_isolation_catalog_freeze_and_group_hashes() -> None:
    dev = _json(BUILDS["dev"] / "manifest.json")
    holdout = _json(BUILDS["holdout"] / "manifest.json")
    for field in ("id", "speaker", "voice", "rate"):
        assert {item[field] for item in dev["utterances"]}.isdisjoint(
            item[field] for item in holdout["utterances"]
        )
    assert {
        item["sha256"] for item in dev["artifacts"] if "audio" in item
    }.isdisjoint(
        item["sha256"] for item in holdout["artifacts"] if "audio" in item
    )
    dev_safety = {
        (item["command_id"], item["text"])
        for item in dev["utterances"]
        if "command_id" in item
    }
    holdout_safety = {
        (item["command_id"], item["text"])
        for item in holdout["utterances"]
        if "command_id" in item
    }
    assert dev_safety == holdout_safety
    dev_open = {
        item["text"].casefold()
        for item in dev["utterances"]
        if "open_dictation" in item["categories"]
    }
    holdout_open = {
        item["text"].casefold()
        for item in holdout["utterances"]
        if "open_dictation" in item["categories"]
    }
    assert dev_open.isdisjoint(holdout_open)

    catalog_record = dev["provenance"]["safety_catalog"]
    assert catalog_record == holdout["provenance"]["safety_catalog"]
    assert _sha(ROOT / catalog_record["path"]) == catalog_record["sha256"]
    catalog = _json(ROOT / catalog_record["path"])
    assert catalog["mode"] == "closed_command"
    assert catalog["freeze_policy"]["catalog_frozen_before_asr"] is True
    assert catalog["freeze_policy"]["catalog_frozen_before_holdout_generation"] is True
    assert catalog["evaluation_policy"]["selection_uses_asr_output"] is False

    groups = _json(MANIFESTS / "evaluation_v8_groups_v1.json")
    assert set(groups["group_policy"]["groups"]) == {
        "human",
        "synthetic",
        "degraded",
    }
    for split in ("dev", "holdout"):
        assert set(groups["splits"][split]) == {"human", "synthetic", "degraded"}
        for records in groups["splits"][split].values():
            for record in records:
                assert _sha(ROOT / record["path"]) == record["sha256"]
                if "seal" in record:
                    assert _sha(ROOT / record["seal"]["path"]) == record["seal"]["sha256"]
