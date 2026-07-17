from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import numpy as np

import backend.config as cfg

logger = logging.getLogger(__name__)


@dataclass
class SpeechSegment:
    audio: np.ndarray
    start: float
    end: float
    duration: float
    stream_start: float
    stream_end: float
    is_final: bool = True
    speech_id: str | None = None


class SpeechSegmenter:
    """
    Turns contiguous audio blocks into finalized speech segments.

    The preferred path uses sherpa-onnx Silero VAD. If that is unavailable,
    a simple energy gate remains as a deterministic fallback so the rest of the
    live pipeline still works.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int = cfg.SAMPLE_RATE,
        provider: str = cfg.SHERPA_PROVIDER,
    ) -> None:
        self._model_path = Path(model_path or cfg.SILERO_VAD_MODEL)
        self._sample_rate = sample_rate
        self._provider = provider
        self._vad = None
        self._window_size = cfg.VAD_WINDOW_SIZE
        self._error: str | None = None
        self._fallback_reason: str | None = None
        self._pending = np.array([], dtype=np.float32)
        self._audio_history = np.array([], dtype=np.float32)
        self._history_start_sample = 0
        self._max_history_samples = max(
            1,
            int(round(cfg.VAD_AUDIO_HISTORY_SECONDS * self._sample_rate)),
        )
        self._last_core_end_sample: int | None = None
        self._input_samples = 0
        self._segment_index = 0
        self._load()

    def segment(self, audio: np.ndarray) -> list[SpeechSegment]:
        arr = np.asarray(audio, dtype=np.float32).ravel()
        if len(arr) == 0:
            return []

        chunk_start_sample = self._input_samples
        self._input_samples += len(arr)
        self._append_audio_history(arr, chunk_start_sample)

        if self._vad is not None:
            try:
                return self._segment_with_sherpa(arr, chunk_start_sample, flush=False)
            except Exception as exc:
                self._fallback_reason = f"sherpa-onnx VAD failed: {exc}"
                self._error = str(exc)
                logger.warning("sherpa-onnx VAD failed; falling back to energy gate: %s", exc)
                self._vad = None

        return self._segment_with_energy(arr, chunk_start_sample)

    def flush(self) -> list[SpeechSegment]:
        if self._vad is None:
            self._pending = np.array([], dtype=np.float32)
            return []
        return self._segment_with_sherpa(np.array([], dtype=np.float32), self._input_samples, flush=True)

    def reset(self) -> None:
        self._pending = np.array([], dtype=np.float32)
        self._audio_history = np.array([], dtype=np.float32)
        self._history_start_sample = 0
        self._last_core_end_sample = None
        self._input_samples = 0
        self._segment_index = 0
        if self._vad is not None:
            try:
                self._vad.reset()
            except Exception as exc:
                logger.warning("Failed to reset sherpa-onnx VAD: %s", exc)

    def status(self) -> dict:
        if self._vad is not None:
            return {
                "engine": "sherpa-onnx",
                "model": str(self._model_path),
                "provider": self._provider,
                "ready": True,
                "error": None,
                "fallback_reason": self._fallback_reason,
                "window_size": self._window_size,
                "threshold": cfg.VAD_THRESHOLD,
                "pre_roll_seconds": cfg.VAD_CONTEXT_PRE_ROLL_SECONDS,
                "post_roll_seconds": cfg.VAD_CONTEXT_POST_ROLL_SECONDS,
                "audio_history_seconds": cfg.VAD_AUDIO_HISTORY_SECONDS,
            }
        return {
            "engine": "energy-fallback",
            "model": str(self._model_path),
            "provider": self._provider,
            "ready": False,
            "error": self._error,
            "fallback_reason": self._fallback_reason or self._error,
            "window_size": self._window_size,
            "threshold": cfg.VAD_THRESHOLD,
            "pre_roll_seconds": cfg.VAD_CONTEXT_PRE_ROLL_SECONDS,
            "post_roll_seconds": cfg.VAD_CONTEXT_POST_ROLL_SECONDS,
            "audio_history_seconds": cfg.VAD_AUDIO_HISTORY_SECONDS,
        }

    def _load(self) -> None:
        if not self._model_path.exists():
            self._error = f"Model not found: {self._model_path}"
            self._fallback_reason = self._error
            return
        try:
            import sherpa_onnx

            vad_config = sherpa_onnx.VadModelConfig()
            vad_config.silero_vad.model = str(self._model_path)
            vad_config.silero_vad.threshold = cfg.VAD_THRESHOLD
            vad_config.silero_vad.min_silence_duration = cfg.VAD_MIN_SILENCE_SECONDS
            vad_config.silero_vad.min_speech_duration = cfg.VAD_MIN_SPEECH_SECONDS
            vad_config.silero_vad.max_speech_duration = cfg.VAD_MAX_SEGMENT_SECONDS
            vad_config.silero_vad.window_size = cfg.VAD_WINDOW_SIZE
            vad_config.sample_rate = self._sample_rate
            self._window_size = int(vad_config.silero_vad.window_size)
            self._vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=60)
            self._error = None
            self._fallback_reason = None
        except Exception as exc:
            self._error = str(exc)
            self._fallback_reason = str(exc)
            logger.info("sherpa-onnx VAD unavailable: %s", exc)

    def _segment_with_sherpa(
        self,
        audio: np.ndarray,
        chunk_start_sample: int,
        flush: bool,
    ) -> list[SpeechSegment]:
        assert self._vad is not None

        if len(audio):
            self._pending = np.concatenate([self._pending, audio])
        while len(self._pending) >= self._window_size:
            self._vad.accept_waveform(self._pending[: self._window_size])
            self._pending = self._pending[self._window_size :]

        if flush:
            if len(self._pending):
                padded = np.pad(self._pending, (0, max(0, self._window_size - len(self._pending))))
                self._vad.accept_waveform(padded[: self._window_size])
                self._pending = np.array([], dtype=np.float32)
            self._vad.flush()

        chunk_duration = len(audio) / self._sample_rate if len(audio) else 0.0
        chunk_end_sample = self._input_samples
        segments: list[SpeechSegment] = []
        while not self._vad.empty():
            vad_segment = self._vad.front
            samples = np.asarray(vad_segment.samples, dtype=np.float32)
            self._vad.pop()
            duration = len(samples) / self._sample_rate
            if duration < cfg.VAD_MIN_SPEECH_SECONDS:
                continue

            start_sample = int(getattr(vad_segment, "start", max(0, chunk_end_sample - len(samples))))
            end_sample = start_sample + len(samples)
            samples, start_sample, end_sample = self._add_context(samples, start_sample, end_sample)
            duration = len(samples) / self._sample_rate
            if flush or chunk_duration == 0.0:
                local_start = 0.0
                local_end = duration
            else:
                local_start = max(0.0, (start_sample - chunk_start_sample) / self._sample_rate)
                local_end = max(0.0, min(chunk_duration, (end_sample - chunk_start_sample) / self._sample_rate))
            segments.append(
                SpeechSegment(
                    audio=samples,
                    start=local_start,
                    end=local_end,
                    duration=duration,
                    stream_start=start_sample / self._sample_rate,
                    stream_end=end_sample / self._sample_rate,
                    is_final=True,
                    speech_id=f"speech-{self._segment_index}",
                )
            )
            self._segment_index += 1
        return segments

    def _append_audio_history(self, audio: np.ndarray, chunk_start_sample: int) -> None:
        if len(audio) == 0:
            return
        if len(self._audio_history) == 0:
            self._history_start_sample = chunk_start_sample
        self._audio_history = np.concatenate([self._audio_history, audio])
        if len(self._audio_history) > self._max_history_samples:
            trim = len(self._audio_history) - self._max_history_samples
            self._audio_history = self._audio_history[trim:]
            self._history_start_sample += trim

    def _history_slice(self, start_sample: int, end_sample: int) -> tuple[np.ndarray, int, int]:
        history_end_sample = self._history_start_sample + len(self._audio_history)
        actual_start = max(start_sample, self._history_start_sample)
        actual_end = min(end_sample, history_end_sample)
        if actual_end <= actual_start:
            return np.array([], dtype=np.float32), actual_start, actual_start
        local_start = actual_start - self._history_start_sample
        local_end = actual_end - self._history_start_sample
        return self._audio_history[local_start:local_end].copy(), actual_start, actual_end

    def _add_context(
        self,
        core_audio: np.ndarray,
        core_start_sample: int,
        core_end_sample: int,
    ) -> tuple[np.ndarray, int, int]:
        pre_roll = max(0, int(round(cfg.VAD_CONTEXT_PRE_ROLL_SECONDS * self._sample_rate)))
        post_roll = max(0, int(round(cfg.VAD_CONTEXT_POST_ROLL_SECONDS * self._sample_rate)))

        # A max-duration endpoint is a forced split, not a new acoustic onset.
        # Post-roll would copy the beginning of the following core, and the
        # following core's pre-roll would copy the end of this one. Suppress
        # both sides of that boundary while retaining pre-roll after real gaps.
        core_duration = (core_end_sample - core_start_sample) / self._sample_rate
        if core_duration + 0.05 >= cfg.VAD_MAX_SEGMENT_SECONDS:
            post_roll = 0
        adjacency_samples = max(1, int(round(0.02 * self._sample_rate)))
        suppress_pre_roll = (
            self._last_core_end_sample is not None
            and core_start_sample <= self._last_core_end_sample + adjacency_samples
        )
        if suppress_pre_roll:
            pre_roll = 0
        elif self._last_core_end_sample is not None:
            # Context before a genuine onset must contain only the acoustic
            # gap. Never copy speech from the preceding finalized segment.
            gap_samples = max(0, core_start_sample - self._last_core_end_sample)
            pre_roll = min(pre_roll, gap_samples)

        prefix, prefix_start, prefix_end = self._history_slice(
            max(0, core_start_sample - pre_roll), core_start_sample
        )
        if prefix_end != core_start_sample:
            prefix = np.array([], dtype=np.float32)
            prefix_start = core_start_sample

        suffix, suffix_start, suffix_end = self._history_slice(
            core_end_sample, min(self._input_samples, core_end_sample + post_roll)
        )
        if suffix_start != core_end_sample:
            suffix = np.array([], dtype=np.float32)
            suffix_end = core_end_sample

        padded = np.concatenate([prefix, core_audio, suffix])
        padded_start = prefix_start if len(prefix) else core_start_sample
        padded_end = suffix_end if len(suffix) else core_end_sample
        self._last_core_end_sample = core_end_sample
        return padded, padded_start, padded_end

    def _segment_with_energy(self, audio: np.ndarray, chunk_start_sample: int) -> list[SpeechSegment]:
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        if rms < cfg.ASR_MIN_RMS:
            return []
        duration = len(audio) / self._sample_rate
        if duration < cfg.VAD_MIN_SPEECH_SECONDS:
            return []
        speech_id = f"speech-{self._segment_index}"
        self._segment_index += 1
        return [
            SpeechSegment(
                audio=audio,
                start=0.0,
                end=duration,
                duration=duration,
                stream_start=chunk_start_sample / self._sample_rate,
                stream_end=(chunk_start_sample + len(audio)) / self._sample_rate,
                is_final=True,
                speech_id=speech_id,
            )
        ]
