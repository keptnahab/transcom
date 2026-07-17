from __future__ import annotations

import threading

import numpy as np
import pytest
import soundfile as sf

import backend.config as cfg
from backend.audio.capture import ChannelCapture


def _configure_small_chunks(monkeypatch) -> None:
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    monkeypatch.setattr(cfg, "CHUNK_SECONDS", 1.0)
    monkeypatch.setattr(cfg, "OVERLAP_SECONDS", 0.5)
    monkeypatch.setattr(cfg, "CAPTURE_BLOCK_SIZE", 5)


def test_live_queue_emits_contiguous_chunks_as_soon_as_chunk_is_available(monkeypatch):
    _configure_small_chunks(monkeypatch)
    emitted: list[tuple[int, np.ndarray]] = []
    supplied_samples = 0
    emitted_events = [threading.Event() for _index in range(3)]

    capture: ChannelCapture

    def on_chunk(_channel_id: str, audio: np.ndarray, _wall_ts: float) -> None:
        emitted.append((supplied_samples, audio.copy()))
        emitted_events[len(emitted) - 1].set()
        if len(emitted) == 3:
            capture._stop_event.set()

    capture = ChannelCapture("live", 0, on_chunk)
    drain_thread = threading.Thread(target=capture._drain_queue_loop)
    drain_thread.start()

    for chunk_index in range(3):
        chunk_start = chunk_index * 10
        for block_start in range(chunk_start, chunk_start + 10, 5):
            supplied_samples = block_start + 5
            capture._raw_queue.put(np.arange(block_start, block_start + 5, dtype=np.float32))
        # Do not supply the next chunk until this callback fires. This makes
        # the observed sample count the exact availability at emission time.
        assert emitted_events[chunk_index].wait(timeout=1.0)

    drain_thread.join(timeout=1.0)

    assert [available for available, _audio in emitted] == [10, 20, 30]
    np.testing.assert_array_equal(
        np.concatenate([audio for _available, audio in emitted]),
        np.arange(30, dtype=np.float32),
    )


def test_file_source_flushes_partial_tail_without_overlap_delay(monkeypatch, tmp_path):
    _configure_small_chunks(monkeypatch)
    source = np.arange(13, dtype=np.float32) / 20.0
    path = tmp_path / "partial.wav"
    sf.write(path, source, cfg.SAMPLE_RATE, subtype="FLOAT")

    emitted: list[np.ndarray] = []
    capture: ChannelCapture

    def on_chunk(_channel_id: str, audio: np.ndarray, _wall_ts: float) -> None:
        emitted.append(audio.copy())
        if len(emitted) == 2:
            capture._stop_event.set()

    capture = ChannelCapture("file", 0, on_chunk)
    monkeypatch.setattr("backend.audio.capture.time.sleep", lambda _seconds: None)

    capture._run_from_file(str(path))

    assert len(emitted) == 2
    np.testing.assert_allclose(emitted[0], source[:10], atol=1e-6)
    np.testing.assert_allclose(emitted[1][:3], source[10:], atol=1e-6)
    np.testing.assert_array_equal(emitted[1][3:], np.zeros(7, dtype=np.float32))


def test_file_source_mixes_stereo_and_bandlimited_resamples(monkeypatch, tmp_path):
    _configure_small_chunks(monkeypatch)
    source_rate = 5
    left = np.ones(5, dtype=np.float32) * 0.4
    right = np.zeros(5, dtype=np.float32)
    path = tmp_path / "stereo-5hz.wav"
    sf.write(path, np.column_stack([left, right]), source_rate, subtype="FLOAT")
    emitted: list[np.ndarray] = []
    capture: ChannelCapture

    def on_chunk(_channel_id: str, audio: np.ndarray, _wall_ts: float) -> None:
        emitted.append(audio.copy())
        capture._stop_event.set()

    capture = ChannelCapture("resample", 0, on_chunk)
    monkeypatch.setattr("backend.audio.capture.time.sleep", lambda _seconds: None)

    capture._run_from_file(str(path))

    assert len(emitted) == 1
    assert len(emitted[0]) == 10
    # The stereo mean is 0.2. Polyphase edge transients are expected, but the
    # interior remains close and the second channel is demonstrably retained.
    assert np.mean(emitted[0][2:-2]) == pytest.approx(0.2, abs=0.03)
