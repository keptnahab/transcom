from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import wave

import pytest

from evaluation.build_human_live_dev import (
    HumanLiveBuildError,
    PAUSE_FRAMES,
    build_human_live_dev,
)
from scripts.benchmark_live_pipeline import load_reference


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pcm16(path: Path, samples: list[int], *, sample_rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _reviewed_manifest(root: Path) -> tuple[Path, list[bytes]]:
    clips = []
    raw_frames = []
    for index in range(12):
        audio_id = f"human-dev-{index + 1:02d}"
        audio_path = root / "evaluation" / "data" / "raw" / "human" / f"{audio_id}.wav"
        samples = [index + 1, -(index + 1), index + 2]
        _write_pcm16(audio_path, samples)
        with wave.open(str(audio_path), "rb") as source:
            raw_frames.append(source.readframes(source.getnframes()))
        text = f"Manuell geprüfte Referenz Nummer {index + 1}."
        clips.append(
            {
                "audio_id": audio_id,
                "data_path": audio_path.relative_to(root).as_posix(),
                "sha256": _sha256(audio_path),
                "reference_text": text,
                "reference_status": "manually_reviewed_against_audio",
                "review_provenance": {
                    "reviewer_id": "reviewer-a",
                    "reviewed_at_utc": "2026-07-13T20:00:00Z",
                    "method": "manual_audio_reference_review",
                    "reference_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            }
        )
    manifest = {
        "schema_version": 1,
        "dataset_id": "fleurs_de_dev_reviewed_v1",
        "dataset_name": "FLEURS",
        "usage": "development",
        "official_split": "dev",
        "is_holdout": False,
        "clips": clips,
    }
    path = root / "reviewed-human-dev.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, raw_frames


def test_build_is_deterministic_sample_exact_and_live_pipeline_compatible(tmp_path):
    source, source_frames = _reviewed_manifest(tmp_path)
    audio = tmp_path / "generated" / "human-live.wav"
    reference = tmp_path / "generated" / "human-live.json"

    first = build_human_live_dev(source, audio, reference, project_root=tmp_path)
    first_audio = audio.read_bytes()
    first_manifest = reference.read_bytes()
    second = build_human_live_dev(source, audio, reference, project_root=tmp_path)

    assert second == first
    assert audio.read_bytes() == first_audio
    assert reference.read_bytes() == first_manifest
    payload = json.loads(reference.read_text(encoding="utf-8"))
    assert payload["audio_sha256"] == _sha256(audio) == first["audio_sha256"]
    assert payload["source_manifest"]["sha256"] == _sha256(source)
    assert payload["composition"] == {
        "clip_count": 12,
        "pause_count": 11,
        "pause_frames": 10_400,
        "pause_seconds": 0.65,
        "policy": "source PCM frames copied byte-exactly in manifest order",
        "resampling": False,
    }
    assert payload["review_provenance"]["all_references_manually_reviewed"] is True

    with wave.open(str(audio), "rb") as combined:
        assert combined.getparams()[:4] == (1, 2, 16_000, first["frames"])
        output_frames = combined.readframes(combined.getnframes())
    cursor = 0
    pause = b"\x00" * (PAUSE_FRAMES * 2)
    for index, source_data in enumerate(source_frames):
        assert output_frames[cursor : cursor + len(source_data)] == source_data
        cursor += len(source_data)
        if index < 11:
            assert output_frames[cursor : cursor + len(pause)] == pause
            cursor += len(pause)
    assert cursor == len(output_frames)

    expected, source_label, verified = load_reference(audio, _sha256(audio), reference)
    assert expected == " ".join(turn["text"] for turn in payload["turns"])
    assert source_label == str(reference.resolve())
    assert verified is True


@pytest.mark.parametrize(
    "status",
    [None, "unreviewed", "official_fleurs_metadata_not_manually_reviewed"],
)
def test_rejects_unreviewed_before_resolving_audio_or_writing_outputs(tmp_path, status):
    source, _frames = _reviewed_manifest(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["clips"][0]["reference_status"] = status
    payload["clips"][0]["data_path"] = "missing/should-not-be-opened.wav"
    source.write_text(json.dumps(payload), encoding="utf-8")
    audio = tmp_path / "generated" / "rejected.wav"
    reference = tmp_path / "generated" / "rejected.json"

    with pytest.raises(HumanLiveBuildError, match="not fully manually reviewed"):
        build_human_live_dev(source, audio, reference, project_root=tmp_path)

    assert not audio.exists()
    assert not reference.exists()


def test_rejects_audio_hash_and_format_before_writing_outputs(tmp_path):
    source, _frames = _reviewed_manifest(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["clips"][0]["sha256"] = "0" * 64
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HumanLiveBuildError, match="audio SHA-256 mismatch"):
        build_human_live_dev(
            source,
            tmp_path / "generated/hash.wav",
            tmp_path / "generated/hash.json",
            project_root=tmp_path,
        )

    source, _frames = _reviewed_manifest(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    bad_audio = tmp_path / payload["clips"][0]["data_path"]
    _write_pcm16(bad_audio, [1, 2, 3], sample_rate=8_000)
    payload["clips"][0]["sha256"] = _sha256(bad_audio)
    source.write_text(json.dumps(payload), encoding="utf-8")
    audio = tmp_path / "generated/format.wav"
    reference = tmp_path / "generated/format.json"
    with pytest.raises(HumanLiveBuildError, match="mono 16 kHz PCM16"):
        build_human_live_dev(source, audio, reference, project_root=tmp_path)
    assert not audio.exists()
    assert not reference.exists()
