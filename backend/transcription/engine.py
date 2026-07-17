from __future__ import annotations
import contextlib
from dataclasses import dataclass
from difflib import SequenceMatcher
import importlib
import io
import logging
import math
import numpy as np
import re
import threading
import unicodedata
import zlib
from faster_whisper import WhisperModel

import backend.config as cfg
from backend.transcription.normalization import (
    normalize_german_spoken_number_segments,
    normalize_split_domain_terms,
)
from backend.transcription.safety_commands import (
    SafetyCommandCatalog,
    SafetyMatch,
    normalize_command,
)

logger = logging.getLogger(__name__)
_MLX_MODEL_HOLDER_LOCK = threading.RLock()


@dataclass
class Segment:
    text: str
    start: float   # seconds relative to chunk start
    end: float
    confidence: float
    is_word: bool = False
    requires_confirmation: bool = False
    raw_text: str | None = None
    safety_command_id: str | None = None
    safety_match_score: float | None = None
    safety_match_margin: float | None = None
    safety_rejection_reason: str | None = None
    safety_catalog_id: str | None = None
    safety_catalog_sha256: str | None = None
    safety_confirmation_raw_text: str | None = None
    safety_confirmation_model: str | None = None
    safety_confirmation_used: bool = False


class WhisperEngine:
    """
    Singleton wrapper around faster-whisper. Thread-safe for single-worker use.

    The model is loaded lazily on first call to `transcribe` to avoid blocking
    the startup path. Loading takes a few seconds on first run.
    """

    _instance: WhisperEngine | None = None

    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._guard_fallback_model: WhisperModel | None = None
        self._guard_fallback_model_path: str | None = None
        self._guard_fallback_count = 0
        self._mlx = None
        self._mlx_warmed = False
        self._mlx_short_warmed = False
        self._mlx_model_holder = None
        self._mlx_model_loader = None
        self._mlx_float16 = None
        self._mlx_model_cache: dict[str, object] = {}
        self._active_backend = cfg.WHISPER_BACKEND
        self._fallback_reason: str | None = None
        self._last_language = cfg.WHISPER_DEFAULT_LANGUAGE
        self._resolved_model_path: str | None = None
        self._model_revision: str | None = None
        self._short_mlx_resolved_model_path: str | None = None
        self._short_mlx_model_revision: str | None = None
        self._last_mlx_model_role: str | None = None
        self._last_mlx_model_source: str | None = None
        self._last_mlx_model_revision: str | None = None
        self._safety_catalog: SafetyCommandCatalog | None = None
        self._safety_catalog_error: str | None = None
        self._safety_confirmation_error: str | None = None
        if cfg.SAFETY_COMMAND_MODE and cfg.SAFETY_COMMAND_CATALOG:
            try:
                self._safety_catalog = SafetyCommandCatalog.load(cfg.SAFETY_COMMAND_CATALOG)
            except Exception as exc:
                self._safety_catalog_error = str(exc)
                logger.error("Safety command catalog disabled: %s", exc)

    @classmethod
    def get(cls) -> WhisperEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        """Eagerly load the model. Call once at startup to warm up."""
        if cfg.WHISPER_BACKEND == "mlx":
            try:
                self._load_mlx()
                self._active_backend = "mlx"
                if cfg.SAFETY_COMMAND_MODE and self._safety_catalog is not None:
                    try:
                        self._load_guard_fallback_model()
                    except Exception as exc:
                        self._safety_confirmation_error = str(exc)
                        logger.warning("Safety confirmation preload failed: %s", exc)
                return
            except Exception as exc:
                self._fallback_reason = str(exc)
                logger.warning("MLX warmup failed; falling back to faster-whisper: %s", exc)
                self._load_faster_whisper()
                self._active_backend = "faster-whisper"
            return
        self._load_faster_whisper()
        self._active_backend = "faster-whisper"

    @property
    def last_language(self) -> str:
        return self._last_language

    @property
    def active_backend(self) -> str:
        return self._active_backend

    def status(self) -> dict:
        return {
            "asr_backend": self._active_backend,
            "model": cfg.MLX_WHISPER_MODEL if self._active_backend == "mlx" else cfg.WHISPER_MODEL,
            "model_revision": self._model_revision,
            "resolved_model_path": self._resolved_model_path,
            "mlx_model_strategy": "original-duration-router",
            "mlx_long_model": {
                "configured": cfg.MLX_WHISPER_MODEL,
                "default_repository": cfg.MLX_MODEL_REPOSITORY,
                "revision": self._model_revision,
                "resolved_model_path": self._resolved_model_path,
            },
            "mlx_short_model": {
                "configured": cfg.MLX_SHORT_WHISPER_MODEL,
                "default_repository": cfg.MLX_SHORT_MODEL_REPOSITORY,
                "revision": self._short_mlx_model_revision,
                "resolved_model_path": self._short_mlx_resolved_model_path,
                "max_original_audio_seconds": cfg.MLX_SHORT_MAX_SECONDS,
                "short_word_timestamps": False,
            },
            "short_word_timestamps": False,
            "last_mlx_model_role": self._last_mlx_model_role,
            "last_mlx_model_source": self._last_mlx_model_source,
            "last_mlx_model_revision": self._last_mlx_model_revision,
            "mlx_cached_models": len(self._mlx_model_cache),
            "device": "apple-silicon" if self._active_backend == "mlx" else cfg.WHISPER_DEVICE,
            "compute_type": "mlx-q4" if self._active_backend == "mlx" else cfg.WHISPER_COMPUTE_TYPE,
            "faster_whisper_cpu_threads": cfg.WHISPER_CPU_THREADS,
            "language_mode": cfg.WHISPER_LANGUAGE,
            "last_language": self._last_language,
            "fallback_reason": self._fallback_reason,
            "guard_fallback_count": self._guard_fallback_count,
            "confirm_short_seconds": cfg.ASR_CONFIRM_SHORT_SECONDS,
            "edge_padding_seconds": cfg.ASR_EDGE_PADDING_SECONDS,
            "edge_padding_max_seconds": cfg.ASR_EDGE_PADDING_MAX_SECONDS,
            "domain_glossary_terms": list(cfg.DOMAIN_GLOSSARY_TERMS),
            "safety_command_mode": cfg.SAFETY_COMMAND_MODE,
            "safety_command_catalog": (
                {
                    "catalog_id": self._safety_catalog.catalog_id,
                    "path": self._safety_catalog.path,
                    "sha256": self._safety_catalog.sha256,
                    "commands": len(self._safety_catalog.commands),
                }
                if self._safety_catalog
                else None
            ),
            "safety_command_catalog_error": self._safety_catalog_error,
            "safety_confirmation_model": cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY,
            "safety_confirmation_model_revision": cfg.SAFETY_CONFIRMATION_MODEL_REVISION,
            "safety_confirmation_beam_size": cfg.SAFETY_CONFIRMATION_BEAM_SIZE,
            "safety_confirmation_error": self._safety_confirmation_error,
            "guard_fallback_model": (
                cfg.WHISPER_MODEL_REPOSITORY if self._active_backend == "mlx" else None
            ),
        }

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> list[Segment]:
        """
        Transcribe a float32 mono audio array sampled at 16 kHz.
        Returns a list of Segment objects with text and timing.
        """
        original_audio = np.asarray(audio, dtype=np.float32).ravel()
        original_duration = len(original_audio) / cfg.SAMPLE_RATE
        use_short_mlx = original_duration <= cfg.MLX_SHORT_MAX_SECONDS
        safety_mode = bool(
            cfg.SAFETY_COMMAND_MODE
            and self._safety_catalog
            and original_duration <= cfg.ASR_CONFIRM_SHORT_SECONDS
        )
        initial_prompt = (
            self._safety_catalog.prompt(cfg.WHISPER_INITIAL_PROMPT)
            if safety_mode and self._safety_catalog
            else cfg.WHISPER_INITIAL_PROMPT
        )
        model_audio = original_audio
        timeline_shift_samples = 0
        if original_duration <= cfg.ASR_EDGE_PADDING_MAX_SECONDS:
            model_audio, timeline_shift_samples = self._normalize_edge_context(original_audio)
        self.load()
        if self._active_backend == "mlx":
            mlx_model_source = (
                self._short_mlx_resolved_model_path or cfg.MLX_SHORT_WHISPER_MODEL
                if use_short_mlx
                else self._resolved_model_path or cfg.MLX_WHISPER_MODEL
            )
            guard_fallback_count = self._guard_fallback_count
            segments = self._transcribe_mlx(
                model_audio,
                language=language,
                initial_prompt=initial_prompt,
                model_source=mlx_model_source,
                model_role="short" if use_short_mlx else "long",
            )
            primary_was_mlx = self._guard_fallback_count == guard_fallback_count
            segments = self._restore_edge_timestamps(segments, timeline_shift_samples)
            raw_model_text = self._segments_text(segments)
            self._capture_raw_segment_text(segments)
            segments = self._normalize_output(segments, self._last_language)
            if safety_mode:
                segments = self._apply_safety_catalog(
                    segments,
                    raw_model_text=raw_model_text,
                    confirmation_audio=model_audio if primary_was_mlx else None,
                    confirmation_language=self._last_language,
                    confirmation_prompt=cfg.WHISPER_INITIAL_PROMPT,
                )
            return self._apply_confirmation_policy(segments, len(original_audio))

        assert self._model is not None

        lang = self._select_language(model_audio, language)
        segments = self._transcribe_faster_whisper_model(
            model_audio, self._model, lang, initial_prompt=initial_prompt
        )
        segments = self._restore_edge_timestamps(segments, timeline_shift_samples)
        raw_model_text = self._segments_text(segments)
        self._capture_raw_segment_text(segments)
        segments = self._normalize_output(segments, lang)
        if safety_mode:
            segments = self._apply_safety_catalog(segments, raw_model_text=raw_model_text)
        return self._apply_confirmation_policy(segments, len(original_audio))

    @staticmethod
    def _restore_edge_timestamps(segments: list[Segment], timeline_shift_samples: int) -> list[Segment]:
        if not timeline_shift_samples:
            return segments
        offset = timeline_shift_samples / cfg.SAMPLE_RATE
        for segment in segments:
            segment.start = max(0.0, segment.start + offset)
            segment.end = max(segment.start, segment.end + offset)
        return segments

    @staticmethod
    def _normalize_edge_context(audio: np.ndarray) -> tuple[np.ndarray, int]:
        """Return audio with exactly the configured quiet context at each edge.

        The integer offset maps model-relative timestamps back to the original
        unmodified input: positive for trimmed leading silence, negative for
        inserted leading silence.
        """
        target = max(0, int(round(cfg.ASR_EDGE_PADDING_SECONDS * cfg.SAMPLE_RATE)))
        if not target or not len(audio):
            return audio, 0
        quiet = np.abs(audio) <= cfg.ASR_MIN_RMS
        leading = 0
        for is_quiet in quiet:
            if not is_quiet:
                break
            leading += 1
        trailing = 0
        for is_quiet in quiet[::-1]:
            if not is_quiet:
                break
            trailing += 1
        if leading + trailing >= len(audio):
            leading = trailing = 0

        left_trim = max(0, leading - target)
        right_trim = max(0, trailing - target)
        stop = len(audio) - right_trim if right_trim else len(audio)
        trimmed = audio[left_trim:stop]
        left_padding = max(0, target - (leading - left_trim))
        right_padding = max(0, target - (trailing - right_trim))
        normalized = np.pad(trimmed, (left_padding, right_padding))
        return normalized, left_trim - left_padding

    @staticmethod
    def _capture_raw_segment_text(segments: list[Segment]) -> None:
        for segment in segments:
            if segment.raw_text is None:
                segment.raw_text = segment.text

    @staticmethod
    def _normalize_output(segments: list[Segment], language: str) -> list[Segment]:
        if language != "de":
            return segments
        normalized = [segment.text for segment in segments]
        if cfg.GERMAN_SPOKEN_NUMBER_NORMALIZATION:
            normalized = normalize_german_spoken_number_segments(normalized)
        normalized = normalize_split_domain_terms(normalized, cfg.DOMAIN_GLOSSARY_TERMS)
        for segment, text in zip(segments, normalized):
            segment.text = text
        for index in range(1, len(segments)):
            if not segments[index].text and segments[index - 1].text:
                segments[index - 1].end = max(segments[index - 1].end, segments[index].end)
        return segments

    @staticmethod
    def _apply_confirmation_policy(segments: list[Segment], audio_samples: int) -> list[Segment]:
        duration = audio_samples / cfg.SAMPLE_RATE
        if duration <= cfg.ASR_CONFIRM_SHORT_SECONDS:
            for segment in segments:
                segment.requires_confirmation = True
        return segments

    def _transcribe_faster_whisper_model(
        self,
        audio: np.ndarray,
        model: WhisperModel,
        language: str,
        initial_prompt: str | None = None,
        *,
        beam_size_override: int | None = None,
    ) -> list[Segment]:
        segments, _info = model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=(
                cfg.WHISPER_BEAM_SIZE
                if beam_size_override is None
                else beam_size_override
            ),
            best_of=1,
            initial_prompt=(
                cfg.WHISPER_INITIAL_PROMPT if initial_prompt is None else initial_prompt
            ),
            hotwords=cfg.WHISPER_HOTWORDS or None,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=True,
            no_speech_threshold=cfg.WHISPER_NO_SPEECH_THRESHOLD,
            language_detection_threshold=0.0,
        )

        result: list[Segment] = []
        for seg in segments:
            words = list(getattr(seg, "words", None) or [])
            if words:
                for word in words:
                    text = str(getattr(word, "word", "") or "")
                    if not text.strip():
                        continue
                    start = float(getattr(word, "start", seg.start) or 0.0)
                    end = float(getattr(word, "end", seg.end) or start)
                    result.append(
                        Segment(
                            text=text,
                            start=start,
                            end=end,
                            confidence=float(getattr(word, "probability", 0.0) or 0.0),
                            is_word=True,
                        )
                    )
                continue
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

    def _load_faster_whisper(self) -> None:
        if self._model is None:
            model_source, revision = self._resolve_model_source(
                cfg.WHISPER_MODEL,
                default_repository=cfg.WHISPER_MODEL_REPOSITORY,
                pinned_revision=cfg.WHISPER_MODEL_REVISION,
            )
            self._model = WhisperModel(
                model_source,
                device=cfg.WHISPER_DEVICE,
                compute_type=cfg.WHISPER_COMPUTE_TYPE,
                cpu_threads=cfg.WHISPER_CPU_THREADS,
            )
            self._resolved_model_path = model_source
            self._model_revision = revision

    def _load_mlx(self) -> None:
        if self._resolved_model_path is None:
            self._resolved_model_path, self._model_revision = self._resolve_model_source(
                cfg.MLX_WHISPER_MODEL,
                default_repository=cfg.MLX_MODEL_REPOSITORY,
                pinned_revision=cfg.MLX_MODEL_REVISION,
            )
        if self._short_mlx_resolved_model_path is None:
            (
                self._short_mlx_resolved_model_path,
                self._short_mlx_model_revision,
            ) = self._resolve_model_source(
                cfg.MLX_SHORT_WHISPER_MODEL,
                default_repository=cfg.MLX_SHORT_MODEL_REPOSITORY,
                pinned_revision=cfg.MLX_SHORT_MODEL_REVISION,
            )
        long_model_source = self._resolved_model_path
        short_model_source = self._short_mlx_resolved_model_path
        assert long_model_source is not None
        assert short_model_source is not None
        if self._mlx is None:
            import mlx_whisper

            self._mlx = mlx_whisper
        if self._mlx_model_holder is None:
            transcribe_module = importlib.import_module("mlx_whisper.transcribe")
            try:
                self._mlx_model_holder = transcribe_module.ModelHolder
                self._mlx_model_loader = transcribe_module.load_model
                self._mlx_float16 = transcribe_module.mx.float16
            except AttributeError as exc:
                raise RuntimeError(
                    "Installed mlx-whisper does not expose the required dual-model cache API"
                ) from exc
        assert self._mlx_model_loader is not None
        assert self._mlx_float16 is not None
        with _MLX_MODEL_HOLDER_LOCK:
            for source in (long_model_source, short_model_source):
                if source not in self._mlx_model_cache:
                    self._mlx_model_cache[source] = self._mlx_model_loader(
                        source, dtype=self._mlx_float16
                    )
        silence = np.zeros(cfg.SAMPLE_RATE, dtype=np.float32)
        lang = self._mlx_language()
        if not self._mlx_warmed:
            self._call_mlx_transcribe(
                silence,
                model_source=long_model_source,
                language=lang,
                task="transcribe",
                verbose=False,
                condition_on_previous_text=False,
                word_timestamps=True,
                no_speech_threshold=cfg.WHISPER_NO_SPEECH_THRESHOLD,
            )
            self._mlx_warmed = True
        if short_model_source == long_model_source:
            self._mlx_short_warmed = self._mlx_warmed
        elif not self._mlx_short_warmed:
            self._call_mlx_transcribe(
                silence,
                model_source=short_model_source,
                language=lang,
                task="transcribe",
                verbose=False,
                condition_on_previous_text=False,
                word_timestamps=False,
                no_speech_threshold=cfg.WHISPER_NO_SPEECH_THRESHOLD,
            )
            self._mlx_short_warmed = True
        self._last_language = lang

    def _call_mlx_transcribe(self, audio: np.ndarray, *, model_source: str, **kwargs):
        """Run MLX with one of the two preloaded float16 models without reloading weights."""
        assert self._mlx is not None
        with _MLX_MODEL_HOLDER_LOCK:
            if self._mlx_model_holder is not None:
                try:
                    model = self._mlx_model_cache[model_source]
                except KeyError as exc:
                    raise RuntimeError(f"MLX model was not preloaded: {model_source}") from exc
                self._mlx_model_holder.model = model
                self._mlx_model_holder.model_path = model_source
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return self._mlx.transcribe(
                    np.asarray(audio, dtype=np.float32).ravel(),
                    path_or_hf_repo=model_source,
                    **kwargs,
                )

    def _load_guard_fallback_model(self) -> WhisperModel:
        if self._guard_fallback_model is None:
            model_source, _revision = self._resolve_model_source(
                cfg.WHISPER_MODEL_REPOSITORY,
                default_repository=cfg.WHISPER_MODEL_REPOSITORY,
                pinned_revision=cfg.WHISPER_MODEL_REVISION,
            )
            self._guard_fallback_model = WhisperModel(
                model_source,
                device=cfg.WHISPER_DEVICE,
                compute_type=cfg.WHISPER_COMPUTE_TYPE,
                cpu_threads=cfg.WHISPER_CPU_THREADS,
            )
            self._guard_fallback_model_path = model_source
        return self._guard_fallback_model

    def _transcribe_mlx(
        self,
        audio: np.ndarray,
        language: str | None = None,
        initial_prompt: str | None = None,
        *,
        model_source: str | None = None,
        model_role: str | None = None,
    ) -> list[Segment]:
        assert self._mlx is not None
        lang = self._mlx_language(language)
        selected_source = model_source or self._resolved_model_path or cfg.MLX_WHISPER_MODEL
        selected_role = model_role or (
            "short"
            if selected_source
            == (self._short_mlx_resolved_model_path or cfg.MLX_SHORT_WHISPER_MODEL)
            and selected_source != (self._resolved_model_path or cfg.MLX_WHISPER_MODEL)
            else "long"
        )
        with _MLX_MODEL_HOLDER_LOCK:
            self._last_mlx_model_role = selected_role
            self._last_mlx_model_source = selected_source
            self._last_mlx_model_revision = (
                self._short_mlx_model_revision if selected_role == "short" else self._model_revision
            )
            result = self._call_mlx_transcribe(
                audio,
                model_source=selected_source,
                language=lang,
                task="transcribe",
                verbose=False,
                condition_on_previous_text=False,
                initial_prompt=(
                    cfg.WHISPER_INITIAL_PROMPT if initial_prompt is None else initial_prompt
                ) or None,
                word_timestamps=selected_role != "short",
                no_speech_threshold=cfg.WHISPER_NO_SPEECH_THRESHOLD,
                # Release decoding is deterministic. Greedy token loops or
                # script drift are rejected below and re-run through the
                # independently pinned faster-whisper fallback.
                temperature=0.0,
            )
        self._last_language = self._remember_language(str(result.get("language") or lang), fallback=lang)

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
        pathology = self._pathology_reason(
            self._segments_text(segments),
            duration_seconds=len(np.asarray(audio).ravel()) / cfg.SAMPLE_RATE,
            language=lang,
        )
        if not segments and float(np.sqrt(np.mean(np.square(audio)))) >= cfg.ASR_MIN_RMS:
            pathology = "empty-transcript"
        if pathology is None:
            return segments

        self._guard_fallback_count += 1
        logger.warning("Rejected pathological MLX transcript (%s); using pinned fallback", pathology)
        try:
            fallback_model = self._load_guard_fallback_model()
            fallback_segments = self._transcribe_faster_whisper_model(
                audio, fallback_model, lang, initial_prompt=initial_prompt
            )
        except Exception:
            logger.exception("Pinned fallback transcription failed")
            return []
        fallback_pathology = self._pathology_reason(
            self._segments_text(fallback_segments),
            duration_seconds=len(np.asarray(audio).ravel()) / cfg.SAMPLE_RATE,
            language=lang,
        )
        if fallback_pathology is not None:
            logger.error("Rejected pathological fallback transcript (%s)", fallback_pathology)
            return []
        return fallback_segments

    def _apply_safety_catalog(
        self,
        segments: list[Segment],
        *,
        raw_model_text: str | None = None,
        confirmation_audio: np.ndarray | None = None,
        confirmation_language: str | None = None,
        confirmation_prompt: str | None = None,
    ) -> list[Segment]:
        """Resolve a short transcript against the frozen command allow-list.

        A confident, unambiguous match emits the canonical phrase and command
        id. An unresolved utterance remains verbatim with no command id. Both
        paths are collapsed into one auditable segment and are later marked as
        requiring explicit confirmation; this method never executes a command.
        """
        if self._safety_catalog is None:
            return segments
        match_text = self._segments_text(segments)
        raw_text = match_text if raw_model_text is None else raw_model_text
        if not match_text:
            return []
        match = self._safety_catalog.match(
            match_text,
            min_score=cfg.SAFETY_COMMAND_MIN_SCORE,
            min_margin=cfg.SAFETY_COMMAND_MIN_MARGIN,
        )
        starts = [segment.start for segment in segments]
        ends = [segment.end for segment in segments]
        confidences = [segment.confidence for segment in segments]
        command = match.command
        confirmation_raw_text = None
        confirmation_model = None
        confirmation_used = False
        should_confirm = bool(
            confirmation_audio is not None
            and match.rejection_reason == "not-allowlisted-exact"
            and match.score >= cfg.SAFETY_COMMAND_MIN_SCORE
            and match.margin >= cfg.SAFETY_COMMAND_MIN_MARGIN
            and self._match_allows_safety_confirmation(match_text, match)
        )
        if should_confirm:
            confirmation_used = True
            confirmation_model = (
                f"{cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY}"
                f"@{cfg.SAFETY_CONFIRMATION_MODEL_REVISION}"
            )
            try:
                confirmation_segments = self._transcribe_faster_whisper_model(
                    confirmation_audio,
                    self._load_guard_fallback_model(),
                    confirmation_language or self._last_language,
                    initial_prompt=confirmation_prompt,
                    beam_size_override=cfg.SAFETY_CONFIRMATION_BEAM_SIZE,
                )
                confirmation_raw_text = self._segments_text(confirmation_segments)
                confirmation_match = self._safety_catalog.match(
                    confirmation_raw_text,
                    min_score=cfg.SAFETY_COMMAND_MIN_SCORE,
                    min_margin=cfg.SAFETY_COMMAND_MIN_MARGIN,
                )
                same_candidate = (
                    confirmation_match.best_candidate.command_id
                    == match.best_candidate.command_id
                )
                exact_confirmation = confirmation_match.command is not None
                safe_near_confirmation = bool(
                    confirmation_match.rejection_reason == "not-allowlisted-exact"
                    and confirmation_match.score >= cfg.SAFETY_COMMAND_MIN_SCORE
                    and confirmation_match.margin >= cfg.SAFETY_COMMAND_MIN_MARGIN
                    and self._match_allows_safety_confirmation(
                        confirmation_raw_text,
                        confirmation_match,
                    )
                )
                if same_candidate and (exact_confirmation or safe_near_confirmation):
                    command = confirmation_match.best_candidate
            except Exception:
                logger.exception("Safety command second confirmation failed")
        return [
            Segment(
                text=command.text if command else raw_text,
                start=min(starts),
                end=max(ends),
                confidence=sum(confidences) / len(confidences),
                is_word=False,
                requires_confirmation=True,
                raw_text=raw_text,
                safety_command_id=command.command_id if command else None,
                safety_match_score=match.score,
                safety_match_margin=match.margin,
                safety_rejection_reason=match.rejection_reason,
                safety_catalog_id=self._safety_catalog.catalog_id,
                safety_catalog_sha256=self._safety_catalog.sha256,
                safety_confirmation_raw_text=confirmation_raw_text,
                safety_confirmation_model=confirmation_model,
                safety_confirmation_used=confirmation_used,
            )
        ]

    @staticmethod
    def _match_allows_safety_confirmation(text: str, match: SafetyMatch) -> bool:
        """Allow a near match only for one non-action-token recognition error."""
        primary_tokens = normalize_command(text).split()
        canonical_tokens = normalize_command(match.best_candidate.text).split()
        if len(primary_tokens) != len(canonical_tokens):
            return False
        differences = [
            index
            for index, (primary, canonical) in enumerate(
                zip(primary_tokens, canonical_tokens)
            )
            if primary != canonical
        ]
        if len(differences) != 1:
            return False
        difference = differences[0]
        if difference == len(canonical_tokens) - 1:
            return False
        return (
            SequenceMatcher(
                None,
                primary_tokens[difference],
                canonical_tokens[difference],
            ).ratio()
            >= 0.75
        )

    @staticmethod
    def _segments_text(segments: list[Segment]) -> str:
        if not segments:
            return ""
        if all(segment.is_word for segment in segments):
            return "".join(segment.text for segment in segments).strip()
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    @staticmethod
    def _pathology_reason(text: str, *, duration_seconds: float, language: str) -> str | None:
        """Reject loops and script drift; never guess at semantic correctness."""
        normalized_tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
        token_limit = max(20, int(math.ceil(max(0.0, duration_seconds) * 10)))
        if len(normalized_tokens) > token_limit:
            return f"token-density:{len(normalized_tokens)}>{token_limit}"

        character_limit = max(160, int(math.ceil(max(0.0, duration_seconds) * 100)))
        if len(text) > character_limit:
            return f"character-density:{len(text)}>{character_limit}"
        encoded = text.encode("utf-8")
        if len(encoded) >= 40:
            compression_ratio = len(encoded) / max(1, len(zlib.compress(encoded)))
            if compression_ratio > 3.0:
                return f"character-loop:{compression_ratio:.2f}"

        if normalized_tokens:
            most_common = max(normalized_tokens.count(token) for token in set(normalized_tokens))
            if most_common >= 8 and most_common / len(normalized_tokens) >= 0.5:
                return "token-loop"
            consecutive = 1
            for previous, current in zip(normalized_tokens, normalized_tokens[1:]):
                consecutive = consecutive + 1 if current == previous else 1
                if consecutive >= 6:
                    return "consecutive-token-loop"

        if language in {"de", "en"}:
            for character in text:
                if character.isalpha() and "LATIN" not in unicodedata.name(character, ""):
                    return "unexpected-script"
        return None

    @staticmethod
    def _resolve_model_source(
        configured_model: str,
        *,
        default_repository: str,
        pinned_revision: str,
    ) -> tuple[str, str | None]:
        """Resolve release defaults to an immutable, already-downloaded snapshot."""
        if configured_model != default_repository:
            return configured_model, None
        try:
            from huggingface_hub import snapshot_download

            snapshot = snapshot_download(
                repo_id=default_repository,
                revision=pinned_revision,
                local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Pinned ASR model {default_repository}@{pinned_revision} is not installed; "
                "run ./scripts/setup.sh while online."
            ) from exc
        return str(snapshot), pinned_revision

    def _mlx_language(self, requested: str | None = None) -> str:
        lang = (requested or cfg.WHISPER_LANGUAGE or "auto").lower()
        if lang == "auto":
            lang = self._fallback_language()
        return self._remember_language(lang)

    def _select_language(self, audio: np.ndarray, requested: str | None = None) -> str:
        lang = (requested or cfg.WHISPER_LANGUAGE or "auto").lower()
        if lang and lang != "auto":
            if lang in cfg.WHISPER_ALLOWED_LANGUAGES:
                return self._remember_language(lang)
            fallback = self._fallback_language()
            logger.warning("Unsupported transcription language %s; falling back to %s", lang, fallback)
            return self._remember_language(fallback)

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
            return self._remember_language(fallback)

        allowed = [
            (detected_lang.lower(), float(probability))
            for detected_lang, probability in probabilities
            if detected_lang.lower() in cfg.WHISPER_ALLOWED_LANGUAGES
        ]
        if not allowed:
            fallback = self._fallback_language()
            return self._remember_language(fallback)

        best_lang, best_probability = max(allowed, key=lambda item: item[1])
        current_probability = next(
            (probability for detected_lang, probability in allowed if detected_lang == self._last_language),
            0.0,
        )
        if (
            best_lang != self._last_language
            and (
                (
                    best_probability < cfg.WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY
                    and current_probability
                    >= best_probability * cfg.WHISPER_LANGUAGE_STICKINESS_RATIO
                )
                or best_probability - current_probability < cfg.WHISPER_LANGUAGE_SWITCH_MARGIN
            )
        ):
            return self._last_language

        return self._remember_language(best_lang)

    def _fallback_language(self) -> str:
        fallback = cfg.WHISPER_DEFAULT_LANGUAGE
        if self._last_language in cfg.WHISPER_ALLOWED_LANGUAGES:
            return self._last_language
        if fallback in cfg.WHISPER_ALLOWED_LANGUAGES:
            return fallback
        return sorted(cfg.WHISPER_ALLOWED_LANGUAGES or {"de"})[0]

    def _remember_language(self, language: str, fallback: str | None = None) -> str:
        lang = (language or "").lower()
        if lang not in cfg.WHISPER_ALLOWED_LANGUAGES:
            lang = (fallback or self._fallback_language()).lower()
        if lang not in cfg.WHISPER_ALLOWED_LANGUAGES:
            lang = self._fallback_language()
        self._last_language = lang
        return lang
