from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.audio.segmentation import SpeechSegmenter
import backend.config as cfg


@dataclass
class _FakeVadSegment:
    samples: np.ndarray
    start: int


class _FakeVad:
    def __init__(self, emit_on_accept: bool = True) -> None:
        self._segments: list[_FakeVadSegment] = []
        self._accepted: list[np.ndarray] = []
        self._emit_on_accept = emit_on_accept

    def accept_waveform(self, audio: np.ndarray) -> None:
        self._accepted.append(np.asarray(audio, dtype=np.float32))
        if self._emit_on_accept and len(self._accepted) >= 2 and not self._segments:
            target = int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE)
            samples = np.ones(target, dtype=np.float32)
            self._segments.append(_FakeVadSegment(samples=samples, start=0))

    def empty(self) -> bool:
        return len(self._segments) == 0

    @property
    def front(self) -> _FakeVadSegment:
        return self._segments[0]

    def pop(self) -> None:
        self._segments.pop(0)

    def flush(self) -> None:
        if not self._segments and self._accepted:
            target = int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE)
            samples = np.ones(target, dtype=np.float32)
            self._segments.append(_FakeVadSegment(samples=samples, start=0))

    def reset(self) -> None:
        self._segments.clear()
        self._accepted.clear()


def _make_segmenter() -> SpeechSegmenter:
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx")
    segmenter._vad = _FakeVad()
    segmenter._window_size = cfg.VAD_WINDOW_SIZE
    segmenter._error = None
    segmenter._fallback_reason = None
    return segmenter


def test_sherpa_vad_path_yields_segment():
    segmenter = _make_segmenter()

    audio = np.ones(cfg.VAD_WINDOW_SIZE * 2, dtype=np.float32)
    segments = segmenter.segment(audio)

    assert len(segments) == 1
    assert segments[0].is_final is True
    assert segments[0].speech_id == "speech-0"
    assert segments[0].duration == len(segments[0].audio) / cfg.SAMPLE_RATE


def test_silence_chunk_yields_no_segment_with_energy_fallback():
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx")

    segments = segmenter.segment(np.zeros(int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE), dtype=np.float32))

    assert segments == []


def test_missing_model_falls_back_to_energy_gate():
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx")

    audio = np.ones(int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE), dtype=np.float32)
    segments = segmenter.segment(audio)
    status = segmenter.status()

    assert len(segments) == 1
    assert status["engine"] == "energy-fallback"
    assert "Model not found" in status["fallback_reason"]


def test_flush_emits_pending_segment():
    segmenter = _make_segmenter()
    segmenter._vad = _FakeVad(emit_on_accept=False)

    segments = segmenter.segment(np.ones(cfg.VAD_WINDOW_SIZE // 2, dtype=np.float32))
    flushed = segmenter.flush()

    assert segments == []
    assert len(flushed) == 1
    assert flushed[0].is_final is True


class _ContextVad(_FakeVad):
    def __init__(self, core: np.ndarray, start: int, emit_after: int) -> None:
        super().__init__(emit_on_accept=False)
        self._core = core
        self._start = start
        self._emit_after = emit_after

    def accept_waveform(self, audio: np.ndarray) -> None:
        self._accepted.append(np.asarray(audio, dtype=np.float32))
        if len(self._accepted) == self._emit_after:
            self._segments.append(_FakeVadSegment(samples=self._core.copy(), start=self._start))


class _AdjacentContextVad(_FakeVad):
    def __init__(self, segments: list[_FakeVadSegment], emit_after: int) -> None:
        super().__init__(emit_on_accept=False)
        self._source_segments = segments
        self._emit_after = emit_after

    def accept_waveform(self, audio: np.ndarray) -> None:
        self._accepted.append(np.asarray(audio, dtype=np.float32))
        if len(self._accepted) == self._emit_after:
            self._segments.extend(self._source_segments)


def test_vad_context_preserves_prefix_and_suffix(monkeypatch):
    monkeypatch.setattr(cfg, "VAD_CONTEXT_PRE_ROLL_SECONDS", 0.2)
    monkeypatch.setattr(cfg, "VAD_CONTEXT_POST_ROLL_SECONDS", 0.1)
    monkeypatch.setattr(cfg, "VAD_AUDIO_HISTORY_SECONDS", 2.0)
    sample_rate = 10
    source = np.arange(20, dtype=np.float32)
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx", sample_rate=sample_rate)
    segmenter._window_size = 5
    segmenter._max_history_samples = 20
    segmenter._vad = _ContextVad(core=source[5:12], start=5, emit_after=4)

    segments = segmenter.segment(source)

    assert len(segments) == 1
    np.testing.assert_array_equal(segments[0].audio, source[3:13])
    assert segments[0].stream_start == 0.3
    assert segments[0].stream_end == 1.3
    assert segments[0].duration == 1.0


def test_audio_history_is_bounded_and_reset_clears_it(monkeypatch):
    monkeypatch.setattr(cfg, "VAD_AUDIO_HISTORY_SECONDS", 1.0)
    sample_rate = 10
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx", sample_rate=sample_rate)

    for index in range(6):
        segmenter.segment(np.full(4, index + 1, dtype=np.float32))

    assert len(segmenter._audio_history) == 10
    assert segmenter._history_start_sample == 14
    np.testing.assert_array_equal(
        segmenter._audio_history,
        np.concatenate([
            np.full(2, 4, dtype=np.float32),
            np.full(4, 5, dtype=np.float32),
            np.full(4, 6, dtype=np.float32),
        ]),
    )

    segmenter.reset()

    assert len(segmenter._audio_history) == 0
    assert segmenter._history_start_sample == 0
    assert segmenter._input_samples == 0
    assert segmenter._last_core_end_sample is None


def test_adjacent_max_duration_cores_do_not_overlap_context(monkeypatch):
    monkeypatch.setattr(cfg, "VAD_CONTEXT_PRE_ROLL_SECONDS", 0.2)
    # Even an explicit post-roll override must not cross a forced max-duration split.
    monkeypatch.setattr(cfg, "VAD_CONTEXT_POST_ROLL_SECONDS", 0.1)
    monkeypatch.setattr(cfg, "VAD_MAX_SEGMENT_SECONDS", 0.5)
    monkeypatch.setattr(cfg, "VAD_AUDIO_HISTORY_SECONDS", 3.0)
    sample_rate = 10
    source = np.arange(20, dtype=np.float32)
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx", sample_rate=sample_rate)
    segmenter._window_size = 5
    segmenter._vad = _AdjacentContextVad(
        [
            _FakeVadSegment(samples=source[5:10], start=5),
            _FakeVadSegment(samples=source[10:15], start=10),
        ],
        emit_after=4,
    )

    segments = segmenter.segment(source)

    assert len(segments) == 2
    # The first genuine onset keeps its pre-roll, but no post-roll crosses the split.
    np.testing.assert_array_equal(segments[0].audio, source[3:10])
    # The directly adjacent second core gets neither duplicated prefix nor suffix.
    np.testing.assert_array_equal(segments[1].audio, source[10:15])
    assert segments[0].stream_end == segments[1].stream_start == 1.0
    assert segmenter._last_core_end_sample == 15

    segmenter.reset()

    assert segmenter._last_core_end_sample is None


def test_pre_roll_after_real_gap_never_copies_previous_speech(monkeypatch):
    monkeypatch.setattr(cfg, "VAD_CONTEXT_PRE_ROLL_SECONDS", 0.5)
    monkeypatch.setattr(cfg, "VAD_CONTEXT_POST_ROLL_SECONDS", 0.0)
    sample_rate = 10
    source = np.concatenate([
        np.ones(5, dtype=np.float32),
        np.zeros(4, dtype=np.float32),
        np.full(5, 2.0, dtype=np.float32),
    ])
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx", sample_rate=sample_rate)
    segmenter._audio_history = source.copy()
    segmenter._history_start_sample = 0
    segmenter._input_samples = len(source)
    segmenter._last_core_end_sample = 5

    padded, start, end = segmenter._add_context(source[9:14], 9, 14)

    np.testing.assert_array_equal(padded, source[5:14])
    assert start == 5
    assert end == 14


def test_first_segment_preroll_covers_slow_vad_onset(monkeypatch):
    """Silero can declare speech about 0.62 s after a soft initial phoneme."""
    monkeypatch.setattr(cfg, "VAD_CONTEXT_PRE_ROLL_SECONDS", 0.65)
    monkeypatch.setattr(cfg, "VAD_CONTEXT_POST_ROLL_SECONDS", 0.0)
    sample_rate = 100
    source = np.linspace(-0.2, 0.2, 100, dtype=np.float32)
    segmenter = SpeechSegmenter(model_path="/tmp/does-not-exist.onnx", sample_rate=sample_rate)
    segmenter._audio_history = source.copy()
    segmenter._history_start_sample = 0
    segmenter._input_samples = len(source)

    padded, start, end = segmenter._add_context(source[62:90], 62, 90)

    np.testing.assert_array_equal(padded, source[:90])
    assert start == 0
    assert end == 90
