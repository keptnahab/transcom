from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

import backend.config as cfg
from evaluation.benchmark_clip_suite import run_benchmark


class _FakeEngine:
    def __init__(self, hypotheses: list[str]) -> None:
        self._hypotheses = iter(hypotheses)
        self.calls: list[tuple[np.ndarray, str | None]] = []
        self.loaded = False
        self.last_language = "de"

    def load(self) -> None:
        self.loaded = True

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> list:
        self.calls.append((audio.copy(), language))
        self.last_language = language or "de"
        hypothesis = next(self._hypotheses)
        if not hypothesis:
            return []
        return [
            SimpleNamespace(text=f" {word}", raw_text=f" {word}", is_word=True)
            for word in hypothesis.split()
        ]

    def status(self) -> dict:
        return {"asr_backend": "fake", "model": "fake-clips"}


def _write_audio(path: Path, value: float) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.full(160, value, dtype=np.float32)
    sf.write(path, audio, cfg.SAMPLE_RATE, subtype="FLOAT")
    return {
        "path": path,
        "audio": audio,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_manifest(root: Path) -> tuple[Path, list[dict]]:
    specs = [
        ("one", "a b", "short", "FEMALE", "dev", 0.1),
        ("two", "c", "short", "MALE", "dev", 0.2),
        ("three", "d", "long", "MALE", "test", 0.3),
    ]
    written = []
    clips = []
    for audio_id, reference, bucket, gender, split, value in specs:
        relative_path = Path("clips") / f"{audio_id}.wav"
        item = _write_audio(root / relative_path, value)
        written.append(item)
        clips.append({
            "audio_id": audio_id,
            "data_path": str(relative_path),
            "sha256": item["sha256"],
            "reference_text": reference,
            "length_bucket": bucket,
            "gender": gender,
            "official_split": split,
            "categories": ["shared", audio_id],
        })
    manifest = {
        "schema_version": 1,
        "dataset_id": "fake-clips",
        "dataset_name": "Fake Clips",
        "language": "de-DE",
        "clips": clips,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, written


def test_clip_suite_reports_micro_macro_groups_and_exact_audio(tmp_path):
    manifest_path, written = _write_manifest(tmp_path)
    engine = _FakeEngine(["a x", "", "d extra"])

    report = run_benchmark(manifest_path, engine=engine, project_root=tmp_path)

    assert engine.loaded is True
    assert [call[1] for call in engine.calls] == [None, None, None]
    for call, expected in zip(engine.calls, written):
        np.testing.assert_array_equal(call[0], expected["audio"])
    assert report["all_clip_hashes_verified"] is True
    assert report["recognition_config"]["initial_prompt"] == cfg.WHISPER_INITIAL_PROMPT
    assert report["recognition_config"]["no_speech_threshold"] == cfg.WHISPER_NO_SPEECH_THRESHOLD
    assert report["clip_count"] == 3
    assert report["micro"]["word_errors"] == {
        "substitutions": 1,
        "deletions": 1,
        "insertions": 1,
        "errors": 3,
        "reference_length": 4,
        "rate": 0.75,
    }
    assert report["micro"]["word_error_rate"] == 0.75
    assert report["micro"]["semantic_word_error_rate"] == 0.75
    assert report["macro"]["word_error_rate"] == pytest.approx((0.5 + 1.0 + 1.0) / 3)
    assert report["groups"]["length_bucket"]["short"]["micro"]["word_error_rate"] == pytest.approx(2 / 3)
    assert report["groups"]["length_bucket"]["long"]["clip_count"] == 1
    assert report["groups"]["gender"]["MALE"]["clip_count"] == 2
    assert report["groups"]["official_split"]["dev"]["clip_count"] == 2
    assert report["groups"]["category"]["shared"]["clip_count"] == 3
    assert report["groups"]["category"]["one"]["clip_count"] == 1
    assert len(report["clip_results"]) == 3
    assert report["real_time_factor"] >= 0.0


def test_clip_suite_rejects_project_root_escape_before_engine_load(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = _write_audio(tmp_path / "outside.wav", 0.1)
    manifest = {
        "clips": [{
            "audio_id": "escape",
            "data_path": "../outside.wav",
            "sha256": outside["sha256"],
            "reference_text": "test",
        }]
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    engine = _FakeEngine(["unused"])

    with pytest.raises(ValueError, match="escapes project root"):
        run_benchmark(manifest_path, engine=engine, project_root=root)

    assert engine.loaded is False
    assert engine.calls == []


def test_clip_suite_validates_all_hashes_before_engine_load(tmp_path):
    manifest_path, _written = _write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["clips"][-1]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    engine = _FakeEngine(["unused"])

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_benchmark(manifest_path, engine=engine, project_root=tmp_path)

    assert engine.loaded is False
    assert engine.calls == []


def test_clip_suite_accepts_hash_bound_degradation_manifest_shape(tmp_path):
    clip_path = tmp_path / "derived" / "clips" / "noise" / "one.wav"
    written = _write_audio(clip_path, 0.15)
    manifest = {
        "dataset_id": "derived-v1",
        "clips": [{
            "derived_clip_id": "one--noise",
            "path": "clips/noise/one.wav",
            "sha256": written["sha256"],
            "profile": "noise",
            "reference": {"reference_text": "bühne frei"},
        }],
    }
    manifest_path = tmp_path / "derived" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    engine = _FakeEngine(["bühne frei"])

    report = run_benchmark(manifest_path, engine=engine, project_root=tmp_path)

    assert report["micro"]["word_error_rate"] == 0.0
    assert report["clip_results"][0]["audio_id"] == "one--noise"
    assert report["clip_results"][0]["data_path"] == "derived/clips/noise/one.wav"
    assert report["groups"]["profile"]["noise"]["clip_count"] == 1


def test_clip_suite_reports_closed_command_id_and_raw_hypothesis(tmp_path):
    audio = _write_audio(tmp_path / "clips" / "stop.wav", 0.1)
    manifest = {
        "dataset_id": "safety-v1",
        "clips": [{
            "audio_id": "stop-1",
            "data_path": "clips/stop.wav",
            "sha256": audio["sha256"],
            "reference_text": "Alle Bewegungen stoppen!",
            "expected_command_id": "safety_motion_stop",
            "length_bucket": "short",
            "categories": ["safety"],
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class _SafetyEngine(_FakeEngine):
        def transcribe(self, audio, language=None):
            self.calls.append((audio.copy(), language))
            return [SimpleNamespace(
                text="Alle Bewegungen stoppen!",
                raw_text="Alle Bewegung stoppen",
                is_word=False,
                confidence=0.9,
                requires_confirmation=True,
                safety_command_id="safety_motion_stop",
                safety_match_score=0.93,
            )]

    report = run_benchmark(
        manifest_path,
        engine=_SafetyEngine([]),
        project_root=tmp_path,
    )

    clip = report["clip_results"][0]
    assert clip["raw_hypothesis"] == "Alle Bewegung stoppen"
    assert clip["detected_command_id"] == "safety_motion_stop"
    assert clip["expected_command_id"] == "safety_motion_stop"
    assert report["command_id_exact"] == {
        "correct": 1,
        "total": 1,
        "accuracy": 1.0,
    }


def test_clip_suite_rejects_engine_without_raw_text_contract(tmp_path):
    manifest_path, _written = _write_manifest(tmp_path)

    class _MissingRawEngine(_FakeEngine):
        def transcribe(self, audio, language=None):
            return [SimpleNamespace(text="a b", is_word=False)]

    with pytest.raises(ValueError, match="missing pre-normalization raw_text"):
        run_benchmark(
            manifest_path,
            engine=_MissingRawEngine([]),
            project_root=tmp_path,
        )
