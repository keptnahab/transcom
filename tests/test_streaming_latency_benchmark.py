from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

import backend.config as cfg
from evaluation.benchmark_streaming_latency import _validate_fixture, run_benchmark


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _FakeEngine:
    def __init__(self, clock: _Clock, hypotheses: list[str], inference_seconds: list[float]) -> None:
        self.clock = clock
        self.hypotheses = iter(hypotheses)
        self.inference_seconds = iter(inference_seconds)
        self.loaded = False
        self.calls = []
        self.last_language = "de"

    def load(self) -> None:
        self.loaded = True

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> list:
        self.calls.append((audio.copy(), language))
        self.clock.advance(next(self.inference_seconds))
        self.last_language = language or "de"
        text = next(self.hypotheses)
        return [
            SimpleNamespace(text=f" {word}", raw_text=f" {word}", is_word=True)
            for word in text.split()
        ]

    def status(self) -> dict:
        return {"asr_backend": "fake", "model": "fake-latency"}


class _FakeSegmenter:
    def __init__(self, speech_samples: int, sample_rate: int) -> None:
        self.speech_samples = speech_samples
        self.sample_rate = sample_rate
        self.emitted = False

    def segment(self, audio: np.ndarray) -> list:
        if self.emitted or not np.any(audio[: self.speech_samples]):
            return []
        self.emitted = True
        return [SimpleNamespace(
            audio=audio[: self.speech_samples].copy(),
            stream_start=0.0,
            stream_end=self.speech_samples / self.sample_rate,
            speech_id="speech-0",
        )]

    def flush(self) -> list:
        return []


def _write_fixture(root: Path, *, bad_hash: bool = False) -> Path:
    source_manifest = root / "source-dev.json"
    source_manifest.write_text(
        json.dumps(
            {
                "split": "dev",
                "clips": [
                    {
                        "audio_id": "short-1",
                        "reference": {
                            "reference_text": "kurzer test",
                            "reference_status": "manually_reviewed_against_audio",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_hash = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    audio_path = root / "audio" / "short.wav"
    audio_path.parent.mkdir(parents=True)
    audio = np.ones(5, dtype=np.float32) * 0.25
    sf.write(audio_path, audio, cfg.SAMPLE_RATE, subtype="FLOAT")
    audio_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    fixture = {
        "schema_version": 1,
        "fixture_id": "test-short-dev",
        "split": "dev",
        "source_manifest": source_manifest.name,
        "source_manifest_sha256": source_hash,
        "clips": [{
            "id": "short-1",
            "data_path": "audio/short.wav",
            "sha256": "0" * 64 if bad_hash else audio_hash,
            "speech_end_seconds": 0.5,
            "reference_text": "kurzer test",
        }],
    }
    fixture_path = root / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    return fixture_path


def test_streaming_latency_uses_sample_clock_and_reports_end_to_emit(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    monkeypatch.setattr(cfg, "CHUNK_SECONDS", 1.0)
    monkeypatch.setattr(cfg, "OVERLAP_SECONDS", 0.5)
    monkeypatch.setattr(cfg, "VAD_MIN_SILENCE_SECONDS", 0.3)
    monkeypatch.setattr(cfg, "CAPTURE_BLOCK_SIZE", 2)
    fixture = _write_fixture(tmp_path)
    clock = _Clock()
    engine = _FakeEngine(clock, ["kurzer test"], [0.2])

    report = run_benchmark(
        fixture,
        language="de",
        engine=engine,
        timer=clock,
        segmenter_factory=lambda: _FakeSegmenter(5, 10),
        project_root=tmp_path,
    )
    assert report["recognition_config"]["initial_prompt"] == cfg.WHISPER_INITIAL_PROMPT
    assert report["recognition_config"]["no_speech_threshold"] == cfg.WHISPER_NO_SPEECH_THRESHOLD

    clip = report["clip_results"][0]
    assert engine.loaded is True
    assert len(engine.calls) == 1
    assert engine.calls[0][1] == "de"
    assert clip["speech_end_seconds"] == 0.5
    assert clip["reference_status"] == "manually_reviewed_against_audio"
    assert clip["job_results"][0]["available_at_seconds"] == 1.0
    assert clip["first_usable_emit_seconds"] == pytest.approx(1.2)
    assert clip["end_to_emit_seconds"] == pytest.approx(0.7)
    assert clip["jobs"] == 1
    assert clip["word_error_rate"] == 0.0
    assert clip["character_error_rate"] == 0.0
    assert clip["real_time_factor"] == pytest.approx(0.4)
    assert report["jobs"] == 1
    assert report["word_error_rate"] == 0.0
    assert report["real_time_factor"] == pytest.approx(0.4)


def test_streaming_latency_rejects_reference_status_different_from_bound_source(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    fixture = _write_fixture(tmp_path)
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["clips"][0]["reference_status"] = "different_reviewed_status"
    fixture.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="reference_status differs from hash-bound source"):
        _validate_fixture(fixture, tmp_path)


def test_streaming_latency_validates_hash_before_engine_load(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    fixture = _write_fixture(tmp_path, bad_hash=True)
    clock = _Clock()
    engine = _FakeEngine(clock, ["unused"], [0.1])

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_benchmark(
            fixture,
            engine=engine,
            timer=clock,
            segmenter_factory=lambda: _FakeSegmenter(5, 10),
            project_root=tmp_path,
        )

    assert engine.loaded is False
    assert engine.calls == []


def test_historical_fixture_validation_allows_missing_status_but_scoring_rejects(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    fixture = _write_fixture(tmp_path)
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    source_path = tmp_path / payload["source_manifest"]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    del source["clips"][0]["reference"]["reference_status"]
    source_path.write_text(json.dumps(source), encoding="utf-8")
    payload["source_manifest_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    fixture.write_text(json.dumps(payload), encoding="utf-8")

    _fixture_payload, validated = _validate_fixture(fixture, tmp_path)
    assert validated[0]["reference_status"] is None

    clock = _Clock()
    engine = _FakeEngine(clock, ["unused"], [0.1])
    with pytest.raises(ValueError, match="requires reviewed reference provenance"):
        run_benchmark(
            fixture,
            engine=engine,
            timer=clock,
            segmenter_factory=lambda: _FakeSegmenter(5, 10),
            project_root=tmp_path,
        )
    assert engine.loaded is False
    assert engine.calls == []


def test_streaming_latency_accepts_only_seal_bound_holdout_fixture(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    fixture = _write_fixture(tmp_path)
    seal_path = tmp_path / "HOLDOUT_SEAL.json"
    seal_path.write_text(json.dumps({"sealed": True}), encoding="utf-8")
    seal_hash = hashlib.sha256(seal_path.read_bytes()).hexdigest()
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload.update({
        "split": "holdout",
        "is_holdout": True,
        "source_holdout_seal": {
            "path": seal_path.name,
            "sha256": seal_hash,
        },
    })
    fixture.write_text(json.dumps(payload), encoding="utf-8")

    validated, clips = _validate_fixture(fixture, tmp_path)

    assert validated["split"] == "holdout"
    assert validated["is_holdout"] is True
    assert len(clips) == 1

    del payload["source_holdout_seal"]
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="bind a source holdout seal"):
        _validate_fixture(fixture, tmp_path)


def test_punctuation_only_output_is_not_counted_as_usable(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    monkeypatch.setattr(cfg, "CHUNK_SECONDS", 1.0)
    monkeypatch.setattr(cfg, "OVERLAP_SECONDS", 0.5)
    monkeypatch.setattr(cfg, "VAD_MIN_SILENCE_SECONDS", 0.3)
    monkeypatch.setattr(cfg, "CAPTURE_BLOCK_SIZE", 2)
    fixture = _write_fixture(tmp_path)
    clock = _Clock()
    engine = _FakeEngine(clock, ["!!!!"], [0.2])

    report = run_benchmark(
        fixture,
        engine=engine,
        timer=clock,
        segmenter_factory=lambda: _FakeSegmenter(5, 10),
        project_root=tmp_path,
    )

    clip = report["clip_results"][0]
    assert clip["first_usable_emit_seconds"] is None
    assert clip["end_to_emit_seconds"] is None
    assert report["successful_first_emits"] == 0
