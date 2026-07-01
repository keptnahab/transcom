from __future__ import annotations
import contextlib
from dataclasses import dataclass
import io
import logging
import numpy as np
from faster_whisper import WhisperModel

import backend.config as cfg

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    text: str
    start: float   # seconds relative to chunk start
    end: float
    confidence: float
    is_word: bool = False


class WhisperEngine:
    """
    Singleton wrapper around faster-whisper. Thread-safe for single-worker use.

    The model is loaded lazily on first call to `transcribe` to avoid blocking
    the startup path. Loading takes a few seconds on first run.
    """

    _instance: WhisperEngine | None = None

    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._mlx = None
        self._mlx_warmed = False
        self._last_language = cfg.WHISPER_DEFAULT_LANGUAGE

    @classmethod
    def get(cls) -> WhisperEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        """Eagerly load the model. Call once at startup to warm up."""
        if cfg.WHISPER_BACKEND == "mlx":
            self._load_mlx()
            return
        if self._model is None:
            self._model = WhisperModel(
                cfg.WHISPER_MODEL,
                device=cfg.WHISPER_DEVICE,
                compute_type=cfg.WHISPER_COMPUTE_TYPE,
            )

    @property
    def last_language(self) -> str:
        return self._last_language

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> list[Segment]:
        """
        Transcribe a float32 mono audio array sampled at 16 kHz.
        Returns a list of Segment objects with text and timing.
        """
        self.load()
        if cfg.WHISPER_BACKEND == "mlx":
            return self._transcribe_mlx(audio, language=language)

        assert self._model is not None

        lang = self._select_language(audio, language)
        segments, _info = self._model.transcribe(
            audio,
            language=lang,
            task="transcribe",
            beam_size=cfg.WHISPER_BEAM_SIZE,
            best_of=1,
            initial_prompt=cfg.WHISPER_INITIAL_PROMPT,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            language_detection_threshold=0.0,
        )

        result: list[Segment] = []
        for seg in segments:
            avg_logprob = getattr(seg, "avg_logprob", 0.0)
            confidence = float(np.exp(avg_logprob)) if avg_logprob else 1.0
            result.append(
                Segment(
                    text=seg.text.strip(),
                    start=float(seg.start),
                    end=float(seg.end),
                    confidence=confidence,
                )
            )
        return result

    def _load_mlx(self) -> None:
        if self._mlx is None:
            import mlx_whisper

            self._mlx = mlx_whisper
        if self._mlx_warmed:
            return
        silence = np.zeros(cfg.SAMPLE_RATE, dtype=np.float32)
        lang = self._mlx_language()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self._mlx.transcribe(
                silence,
                path_or_hf_repo=cfg.MLX_WHISPER_MODEL,
                language=lang,
                task="transcribe",
                verbose=False,
                condition_on_previous_text=False,
                word_timestamps=True,
                no_speech_threshold=0.6,
            )
        self._last_language = lang
        self._mlx_warmed = True

    def _transcribe_mlx(self, audio: np.ndarray, language: str | None = None) -> list[Segment]:
        assert self._mlx is not None
        lang = self._mlx_language(language)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = self._mlx.transcribe(
                np.asarray(audio, dtype=np.float32).ravel(),
                path_or_hf_repo=cfg.MLX_WHISPER_MODEL,
                language=lang,
                task="transcribe",
                verbose=False,
                condition_on_previous_text=False,
                initial_prompt=cfg.WHISPER_INITIAL_PROMPT or None,
                word_timestamps=True,
                no_speech_threshold=0.6,
                temperature=(0.0,),
            )
        self._last_language = str(result.get("language") or lang)

        segments: list[Segment] = []
        for raw_segment in result.get("segments") or []:
            words = raw_segment.get("words") or []
            if words:
                for word in words:
                    text = str(word.get("word") or "")
                    if not text.strip():
                        continue
                    start = float(word.get("start") or raw_segment.get("start") or 0.0)
                    end = float(word.get("end") or raw_segment.get("end") or start)
                    segments.append(
                        Segment(
                            text=text,
                            start=start,
                            end=end,
                            confidence=float(word.get("probability") or 0.0),
                            is_word=True,
                        )
                    )
                continue
            text = str(raw_segment.get("text") or "").strip()
            if not text:
                continue
            avg_logprob = float(raw_segment.get("avg_logprob") or 0.0)
            segments.append(
                Segment(
                    text=text,
                    start=float(raw_segment.get("start") or 0.0),
                    end=float(raw_segment.get("end") or 0.0),
                    confidence=float(np.exp(avg_logprob)) if avg_logprob else 1.0,
                )
            )
        return segments

    def _mlx_language(self, requested: str | None = None) -> str:
        lang = (requested or cfg.WHISPER_LANGUAGE or "auto").lower()
        if lang == "auto":
            lang = self._fallback_language()
        if lang not in cfg.WHISPER_ALLOWED_LANGUAGES:
            fallback = self._fallback_language()
            logger.warning("Unsupported MLX transcription language %s; falling back to %s", lang, fallback)
            lang = fallback
        self._last_language = lang
        return lang

    def _select_language(self, audio: np.ndarray, requested: str | None = None) -> str:
        lang = (requested or cfg.WHISPER_LANGUAGE or "auto").lower()
        if lang and lang != "auto":
            if lang in cfg.WHISPER_ALLOWED_LANGUAGES:
                self._last_language = lang
                return lang
            fallback = self._fallback_language()
            logger.warning("Unsupported transcription language %s; falling back to %s", lang, fallback)
            self._last_language = fallback
            return fallback

        try:
            _detected, _probability, probabilities = self._model.detect_language(
                audio,
                vad_filter=False,
                language_detection_segments=1,
                language_detection_threshold=0.0,
            )
        except Exception as exc:
            fallback = self._fallback_language()
            logger.warning("Language detection failed; falling back to %s: %s", fallback, exc)
            self._last_language = fallback
            return fallback

        allowed = [
            (detected_lang.lower(), float(probability))
            for detected_lang, probability in probabilities
            if detected_lang.lower() in cfg.WHISPER_ALLOWED_LANGUAGES
        ]
        if not allowed:
            fallback = self._fallback_language()
            self._last_language = fallback
            return fallback

        best_lang, best_probability = max(allowed, key=lambda item: item[1])
        current_probability = next(
            (probability for detected_lang, probability in allowed if detected_lang == self._last_language),
            0.0,
        )
        if best_probability < 0.55 and current_probability >= best_probability * 0.75:
            return self._last_language

        self._last_language = best_lang
        return best_lang

    def _fallback_language(self) -> str:
        fallback = cfg.WHISPER_DEFAULT_LANGUAGE
        if fallback in cfg.WHISPER_ALLOWED_LANGUAGES:
            return fallback
        return sorted(cfg.WHISPER_ALLOWED_LANGUAGES or {"de"})[0]
