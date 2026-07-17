from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

import backend.config as cfg
from evaluation.benchmark_oracle_segments import main, run_benchmark


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
        return [SimpleNamespace(text=f" {word}", is_word=True) for word in hypothesis.split()]

    def status(self) -> dict:
        return {"asr_backend": "fake", "model": "fake-oracle"}


def _write_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    audio = np.arange(10, dtype=np.float32) / 20.0
    audio_path = tmp_path / "oracle.wav"
    sf.write(audio_path, audio, cfg.SAMPLE_RATE, subtype="FLOAT")
    audio_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "audio_id": "test-oracle",
        "audio_file": audio_path.name,
        "audio_sha256": audio_hash,
        "turns": [
            {
                "turn": 1,
                "start_seconds": 0.0,
                "end_seconds": 0.5,
                "speaker": "A",
                "language": "de",
                "text": "eins zwei",
            },
            {
                "turn": 2,
                "start_seconds": 0.5,
                "end_seconds": 1.0,
                "speaker": "B",
                "language": "de",
                "text": "vier",
            },
        ],
    }
    manifest_path = tmp_path / "oracle.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return audio, audio_path, manifest_path


def test_oracle_uses_exact_turn_slices_and_reports_metrics(tmp_path, monkeypatch):
    audio, _audio_path, manifest_path = _write_fixture(tmp_path, monkeypatch)
    engine = _FakeEngine(["eins drei extra", ""])

    report = run_benchmark(manifest_path, engine=engine)

    assert engine.loaded is True
    assert len(engine.calls) == 2
    np.testing.assert_array_equal(engine.calls[0][0], audio[:5])
    np.testing.assert_array_equal(engine.calls[1][0], audio[5:])
    assert [call[1] for call in engine.calls] == [None, None]
    assert report["audio_binding_verified"] is True
    assert report["language_mode"] == "auto"
    assert report["languages_used"] == ["de"]
    assert report["word_errors"] == {
        "substitutions": 1,
        "deletions": 1,
        "insertions": 1,
        "errors": 3,
        "reference_length": 3,
        "rate": 1.0,
    }
    assert report["word_error_rate"] == 1.0
    assert report["turn_results"][0]["start_sample"] == 0
    assert report["turn_results"][0]["end_sample"] == 5
    assert report["turn_results"][1]["hypothesis"] == ""
    assert report["real_time_factor"] >= 0.0


def test_oracle_rejects_hash_mismatch_before_inference(tmp_path, monkeypatch):
    _audio, _audio_path, manifest_path = _write_fixture(tmp_path, monkeypatch)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["audio_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    engine = _FakeEngine(["unused"])

    with pytest.raises(ValueError, match="Audio SHA-256 mismatch"):
        run_benchmark(manifest_path, engine=engine)

    assert engine.loaded is False
    assert engine.calls == []


def test_output_writes_the_same_json_report(tmp_path, monkeypatch, capsys):
    _audio, _audio_path, manifest_path = _write_fixture(tmp_path, monkeypatch)
    output_path = tmp_path / "results" / "oracle.json"
    engine = _FakeEngine(["eins zwei", "vier"])

    report = main(
        [str(manifest_path), "--language", "de", "--output", str(output_path)],
        engine=engine,
    )

    stdout_report = json.loads(capsys.readouterr().out)
    file_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert [call[1] for call in engine.calls] == ["de", "de"]
    assert stdout_report == report
    assert file_report == report
