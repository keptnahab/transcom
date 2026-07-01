from __future__ import annotations
from dataclasses import dataclass, asdict
import logging
import math
from pathlib import Path
import threading
import uuid

import numpy as np

import backend.config as cfg


COLORS = ["#4cc9f0", "#f72585", "#80ed99", "#f9c74f", "#b5179e", "#43aa8b", "#f3722c", "#577590"]
logger = logging.getLogger(__name__)


@dataclass
class SpeakerProfile:
    id: str
    name: str
    color: str
    quality: float = 0.0
    duration_seconds: float = 0.0
    level: float = 0.0
    usable: bool = False
    embedding: list[float] | None = None
    embedding_kind: str | None = None


@dataclass
class SpeakerMatch:
    speaker_id: str | None
    speaker_name: str
    speaker_color: str | None
    confidence: float
    is_unknown: bool


class SpeakerService:
    """
    v1 speaker profile service.

    Uses sherpa-onnx speaker embeddings when the package and model are available.
    Falls back to stable local audio summary features so the workflow remains
    deterministic and usable in development without downloaded models.
    """

    def __init__(
        self,
        max_speakers: int = cfg.SPEAKER_MAX_V1,
        embedding_model_path: str | Path | None = None,
        provider: str = cfg.SHERPA_PROVIDER,
        threshold: float = cfg.SPEAKER_THRESHOLD,
    ) -> None:
        self._max_speakers = max_speakers
        self._embedding_model_path = Path(embedding_model_path or cfg.SPEAKER_EMBEDDING_MODEL)
        self._provider = provider
        self._threshold = threshold
        self._speakers: dict[str, SpeakerProfile] = {}
        self._auto_speakers: dict[str, SpeakerProfile] = {}
        self._extractor = None
        self._extractor_error: str | None = None
        self._lock = threading.Lock()

    def list_speakers(self) -> list[dict]:
        return [self._public(profile) for profile in self._speakers.values()]

    def create_speaker(self, name: str, color: str | None = None) -> dict:
        if len(self._speakers) >= self._max_speakers:
            raise ValueError(f"v1 supports up to {self._max_speakers} speakers")
        idx = len(self._speakers)
        profile = SpeakerProfile(
            id=str(uuid.uuid4()),
            name=name.strip() or f"Speaker {idx + 1}",
            color=color or COLORS[idx % len(COLORS)],
        )
        self._speakers[profile.id] = profile
        return self._public(profile)

    def update_speaker(self, speaker_id: str, name: str | None = None, color: str | None = None) -> dict:
        profile = self._get(speaker_id)
        if name is not None and name.strip():
            profile.name = name.strip()
        if color is not None and color.strip():
            profile.color = color.strip()
        return self._public(profile)

    def delete_speaker(self, speaker_id: str) -> None:
        self._speakers.pop(speaker_id, None)

    def enroll_from_stats(self, speaker_id: str, duration_seconds: float, level: float) -> dict:
        profile = self._get(speaker_id)
        duration = max(0.0, float(duration_seconds or 0))
        rms = max(0.0, float(level or 0))
        duration_score = min(duration / 10.0, 1.0)
        level_score = min(rms / 0.04, 1.0)
        quality = round((duration_score * 0.65 + level_score * 0.35), 3)
        profile.duration_seconds = duration
        profile.level = rms
        profile.quality = quality
        profile.usable = False
        profile.embedding = self._embedding_from_stats(duration, rms)
        profile.embedding_kind = "stats"
        return {
            "speaker": self._public(profile),
            "quality": quality,
            "usable": False,
            "message": "Live audio check-in required",
        }

    def enroll_from_audio(
        self,
        speaker_id: str,
        audio: np.ndarray,
        sample_rate: int = cfg.SAMPLE_RATE,
    ) -> dict:
        profile = self._get(speaker_id)
        arr = self._clean_audio(audio)
        duration = len(arr) / float(sample_rate) if sample_rate > 0 else 0.0
        rms = float(np.sqrt(np.mean(np.square(arr)))) if len(arr) else 0.0
        duration_score = min(duration / 10.0, 1.0)
        level_score = min(rms / 0.04, 1.0)
        quality = round((duration_score * 0.65 + level_score * 0.35), 3)

        embedding = self._embedding_from_audio(arr, sample_rate=sample_rate)
        kind = "sherpa" if embedding is not None and len(embedding) > 3 else "fallback"
        profile.duration_seconds = round(duration, 3)
        profile.level = rms
        profile.quality = quality
        profile.usable = quality >= 0.55 and duration >= 1.0 and embedding is not None
        profile.embedding = embedding
        profile.embedding_kind = kind
        return {
            "speaker": self._public(profile),
            "quality": quality,
            "usable": profile.usable,
            "message": "Profile usable" if profile.usable else "Need clear speech for enrollment",
        }

    def match_audio(self, audio: np.ndarray | None, sample_rate: int = cfg.SAMPLE_RATE) -> SpeakerMatch:
        usable = [p for p in self._speakers.values() if p.usable and p.embedding and p.embedding_kind != "stats"]
        if not usable or audio is None or len(audio) == 0:
            if audio is None or len(audio) == 0:
                return SpeakerMatch(None, "Unknown", None, 0.0, True)
        arr = self._clean_audio(audio)
        rms = float(np.sqrt(np.mean(np.square(arr)))) if len(arr) else 0.0
        if rms < cfg.ASR_MIN_RMS:
            return SpeakerMatch(None, "Unknown", None, 0.0, True)

        sherpa_candidate = self._sherpa_embedding(arr, sample_rate)
        fallback_candidate = self._fallback_embedding_from_audio(arr)
        if sherpa_candidate is None and fallback_candidate is None:
            return SpeakerMatch(None, "Unknown", None, 0.0, True)
        best_profile: SpeakerProfile | None = None
        best_score = -1.0
        for profile in usable:
            profile_embedding = profile.embedding or []
            candidate = sherpa_candidate if sherpa_candidate and len(profile_embedding) == len(sherpa_candidate) else fallback_candidate
            if candidate is None or len(candidate) != len(profile_embedding):
                continue
            score = self._cosine(candidate, profile_embedding)
            if score > best_score:
                best_score = score
                best_profile = profile

        confidence = max(0.0, min(1.0, best_score))
        if best_profile is None or confidence < self._threshold:
            auto_match = self._match_auto_speaker(sherpa_candidate or fallback_candidate)
            if auto_match is not None:
                return auto_match
            return SpeakerMatch(None, "Unknown", None, round(confidence, 3), True)
        return SpeakerMatch(best_profile.id, best_profile.name, best_profile.color, round(confidence, 3), False)

    def public_match(self, match: SpeakerMatch) -> dict:
        return asdict(match)

    def status(self) -> dict:
        extractor = self._get_extractor()
        if extractor is not None:
            return {
                "engine": "sherpa-onnx",
                "model": str(self._embedding_model_path),
                "provider": self._provider,
                "ready": True,
                "auto_cluster": cfg.SPEAKER_AUTO_CLUSTER,
                "auto_speakers": len(self._auto_speakers),
                "error": None,
            }
        return {
            "engine": "fallback-features",
            "model": str(self._embedding_model_path),
            "provider": self._provider,
            "ready": False,
            "auto_cluster": cfg.SPEAKER_AUTO_CLUSTER,
            "auto_speakers": len(self._auto_speakers),
            "error": self._extractor_error,
        }

    def _get(self, speaker_id: str) -> SpeakerProfile:
        profile = self._speakers.get(speaker_id)
        if profile is None:
            raise KeyError(f"Speaker not found: {speaker_id}")
        return profile

    def _public(self, profile: SpeakerProfile) -> dict:
        data = asdict(profile)
        data.pop("embedding", None)
        return data

    def _embedding_from_stats(self, duration: float, rms: float) -> list[float]:
        return [min(duration / 12.0, 1.0), min(rms / 0.08, 1.0), math.sqrt(max(rms, 0.0))]

    def _embedding_from_audio(self, audio: np.ndarray, sample_rate: int = cfg.SAMPLE_RATE) -> list[float] | None:
        arr = self._clean_audio(audio)
        sherpa_embedding = self._sherpa_embedding(arr, sample_rate)
        if sherpa_embedding is not None:
            return sherpa_embedding
        return self._fallback_embedding_from_audio(arr)

    def _fallback_embedding_from_audio(self, audio: np.ndarray) -> list[float] | None:
        arr = self._clean_audio(audio)
        if len(arr) == 0:
            return None
        rms = float(np.sqrt(np.mean(np.square(arr))))
        peak = float(np.max(np.abs(arr)))
        zcr = float(np.mean(np.abs(np.diff(np.signbit(arr))))) if len(arr) > 1 else 0.0
        return [min(peak, 1.0), min(rms / 0.08, 1.0), min(zcr, 1.0)]

    def _match_auto_speaker(self, embedding: list[float] | None) -> SpeakerMatch | None:
        if not cfg.SPEAKER_AUTO_CLUSTER or not embedding:
            return None

        best_profile: SpeakerProfile | None = None
        best_score = -1.0
        for profile in self._auto_speakers.values():
            if not profile.embedding or len(profile.embedding) != len(embedding):
                continue
            score = self._cosine(embedding, profile.embedding)
            if score > best_score:
                best_score = score
                best_profile = profile

        confidence = max(0.0, min(1.0, best_score))
        if best_profile is not None and confidence >= cfg.SPEAKER_AUTO_THRESHOLD:
            self._blend_embedding(best_profile, embedding)
            return SpeakerMatch(
                best_profile.id,
                best_profile.name,
                best_profile.color,
                round(confidence, 3),
                False,
            )

        if len(self._auto_speakers) >= self._max_speakers:
            return SpeakerMatch(None, "Unknown", None, round(confidence, 3), True)

        idx = len(self._auto_speakers)
        profile = SpeakerProfile(
            id=f"auto-{idx + 1}",
            name=f"Speaker {idx + 1}",
            color=COLORS[idx % len(COLORS)],
            quality=1.0,
            duration_seconds=0.0,
            level=0.0,
            usable=True,
            embedding=list(embedding),
            embedding_kind="auto",
        )
        self._auto_speakers[profile.id] = profile
        return SpeakerMatch(profile.id, profile.name, profile.color, 1.0, False)

    def _blend_embedding(self, profile: SpeakerProfile, embedding: list[float]) -> None:
        old = np.asarray(profile.embedding or [], dtype=np.float32)
        new = np.asarray(embedding, dtype=np.float32)
        if old.shape != new.shape:
            profile.embedding = list(embedding)
            return
        blended = old * 0.85 + new * 0.15
        profile.embedding = blended.astype(float).tolist()

    def _sherpa_embedding(self, audio: np.ndarray, sample_rate: int) -> list[float] | None:
        extractor = self._get_extractor()
        if extractor is None or len(audio) == 0:
            return None
        try:
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sample_rate, waveform=np.ascontiguousarray(audio))
            stream.input_finished()
            if not extractor.is_ready(stream):
                return None
            return list(map(float, extractor.compute(stream)))
        except Exception as exc:
            self._extractor_error = str(exc)
            logger.warning("sherpa-onnx speaker embedding failed: %s", exc)
            return None

    def _get_extractor(self):
        if self._extractor is not None:
            return self._extractor
        with self._lock:
            if self._extractor is not None:
                return self._extractor
            if not self._embedding_model_path.exists():
                self._extractor_error = f"Model not found: {self._embedding_model_path}"
                return None
            try:
                import sherpa_onnx

                config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self._embedding_model_path),
                    num_threads=1,
                    debug=False,
                    provider=self._provider,
                )
                if not config.validate():
                    self._extractor_error = f"Invalid sherpa speaker config: {config}"
                    return None
                self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
                self._extractor_error = None
            except Exception as exc:
                self._extractor_error = str(exc)
                logger.info("sherpa-onnx speaker embeddings unavailable: %s", exc)
            return self._extractor

    def _clean_audio(self, audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32).ravel()
        if len(arr) == 0:
            return arr
        return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    def _cosine(self, a: list[float], b: list[float]) -> float:
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        if va.shape != vb.shape:
            return -1.0
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0:
            return -1.0
        return float(np.dot(va, vb) / denom)
