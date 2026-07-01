from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

import numpy as np

import backend.config as cfg
from backend.speaker.service import SpeakerService


@dataclass
class _ActiveEnrollment:
    speaker_id: str
    deadline: float
    chunks: list[np.ndarray] = field(default_factory=list)


class AudioEnrollmentRecorder:
    def __init__(self, speaker_service: SpeakerService, sample_rate: int = cfg.SAMPLE_RATE) -> None:
        self._speaker_service = speaker_service
        self._sample_rate = sample_rate
        self._active: _ActiveEnrollment | None = None
        self._lock = threading.Lock()

    async def enroll(self, speaker_id: str, duration_seconds: float) -> dict:
        duration = max(1.0, min(float(duration_seconds or 0), 20.0))
        with self._lock:
            if self._active is not None:
                raise ValueError("Another speaker check-in is already recording")
            self._active = _ActiveEnrollment(
                speaker_id=speaker_id,
                deadline=time.monotonic() + duration,
            )

        await asyncio.sleep(duration)

        with self._lock:
            active = self._active
            self._active = None

        if active is None or active.speaker_id != speaker_id or not active.chunks:
            speaker = self._speaker_service.update_speaker(speaker_id)
            return {
                "speaker": speaker,
                "quality": 0.0,
                "usable": False,
                "message": "No live audio captured during check-in",
            }

        audio = np.concatenate(active.chunks).astype(np.float32, copy=False)
        return self._speaker_service.enroll_from_audio(
            speaker_id=speaker_id,
            audio=audio,
            sample_rate=self._sample_rate,
        )

    def add_audio(self, audio: np.ndarray) -> None:
        with self._lock:
            active = self._active
            if active is None:
                return
            if time.monotonic() > active.deadline:
                return
            active.chunks.append(np.asarray(audio, dtype=np.float32).ravel().copy())
