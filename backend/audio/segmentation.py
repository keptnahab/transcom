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


class SpeechSegmenter:
    """
    Turns capture chunks into speech-only chunks.

    The live path is latency-first: capture already emits short windows, so this
    class gates silence and forwards speech windows immediately. sherpa-onnx VAD
    is still loaded and reported for availability checks, but endpoint-style VAD
    is not used to hold audio until a long utterance ends.
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
        self._window_size: int | None = None
        self._error: str | None = None
        self._pending = np.array([], dtype=np.float32)
        self._samples_seen = 0
        self._load()

    def segment(self, audio: np.ndarray) -> list[SpeechSegment]:
        arr = np.asarray(audio, dtype=np.float32).ravel()
        if len(arr) == 0:
            return []

        self._samples_seen += len(arr)

        return self._segment_with_energy(arr)

    def status(self) -> dict:
        if self._vad is not None:
            return {
                "engine": "sherpa-onnx",
                "model": str(self._model_path),
                "provider": self._provider,
                "ready": True,
                "error": None,
            }
        return {
            "engine": "energy-fallback",
            "model": str(self._model_path),
            "provider": self._provider,
            "ready": False,
            "error": self._error,
        }

    def _load(self) -> None:
        if not self._model_path.exists():
            self._error = f"Model not found: {self._model_path}"
            return
        try:
            import sherpa_onnx

            vad_config = sherpa_onnx.VadModelConfig()
            vad_config.silero_vad.model = str(self._model_path)
            vad_config.silero_vad.min_silence_duration = cfg.VAD_MIN_SILENCE_SECONDS
            vad_config.silero_vad.min_speech_duration = cfg.VAD_MIN_SPEECH_SECONDS
            vad_config.sample_rate = self._sample_rate
            self._window_size = int(vad_config.silero_vad.window_size)
            self._vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=60)
            self._error = None
        except Exception as exc:
            self._error = str(exc)
            logger.info("sherpa-onnx VAD unavailable: %s", exc)

    def _segment_with_sherpa(self, audio: np.ndarray, chunk_start_sample: int) -> list[SpeechSegment]:
        assert self._vad is not None
        assert self._window_size is not None

        try:
            self._pending = np.concatenate([self._pending, audio])
            while len(self._pending) >= self._window_size:
                self._vad.accept_waveform(self._pending[: self._window_size])
                self._pending = self._pending[self._window_size :]

            segments: list[SpeechSegment] = []
            while not self._vad.empty():
                vad_segment = self._vad.front
                samples = np.asarray(vad_segment.samples, dtype=np.float32)
                self._vad.pop()
                duration = len(samples) / self._sample_rate
                if duration < cfg.VAD_MIN_SPEECH_SECONDS:
                    continue
                vad_start_sample = int(getattr(vad_segment, "start", 0))
                vad_end_sample = vad_start_sample + len(samples)
                local_start = (vad_start_sample - chunk_start_sample) / self._sample_rate
                local_end = (vad_end_sample - chunk_start_sample) / self._sample_rate
                chunk_duration = len(audio) / self._sample_rate
                segments.append(
                    SpeechSegment(
                        audio=samples,
                        start=max(0.0, local_start),
                        end=max(0.0, min(chunk_duration, local_end)),
                    )
                )
            return segments
        except Exception as exc:
            self._error = str(exc)
            logger.warning("sherpa-onnx VAD failed; falling back to energy gate: %s", exc)
            return []

    def _segment_with_energy(self, audio: np.ndarray) -> list[SpeechSegment]:
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        if rms < cfg.ASR_MIN_RMS:
            return []
        duration = len(audio) / self._sample_rate
        if duration < cfg.VAD_MIN_SPEECH_SECONDS:
            return []
        return [SpeechSegment(audio=audio, start=0.0, end=duration)]
