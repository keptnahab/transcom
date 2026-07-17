from __future__ import annotations
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable
import numpy as np

from backend.transcription.engine import WhisperEngine, Segment
import backend.config as cfg

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    channel_id: str
    segments: list[Segment]
    source_audio: np.ndarray
    language: str
    speech_start_ts: float
    speech_end_ts: float
    speech_id: str | None = None
    is_final: bool = True


ResultCallback = Callable[[TranscriptionResult], None]
StatusCallback = Callable[[dict], None]


class TranscriptionPool:
    """
    Wraps a ThreadPoolExecutor to run Whisper inference off the asyncio loop.

    Usage:
        pool = TranscriptionPool(loop, on_result_callback)
        pool.submit(channel_id, audio_np, wall_clock_ts)
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_result: ResultCallback,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._loop = loop
        self._on_result = on_result
        self._on_status = on_status
        self._executor = ThreadPoolExecutor(
            max_workers=cfg.TRANSCRIPTION_WORKERS,
            thread_name_prefix="whisper-worker",
        )
        self._engine = WhisperEngine.get()

    def submit(
        self,
        channel_id: str,
        audio: np.ndarray,
        speech_start_ts: float,
        speech_end_ts: float,
        speech_id: str | None = None,
        is_final: bool = True,
    ) -> None:
        self._executor.submit(
            self._infer,
            channel_id,
            audio,
            speech_start_ts,
            speech_end_ts,
            speech_id,
            is_final,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Internal — runs in ThreadPoolExecutor worker thread
    # ------------------------------------------------------------------

    def _infer(
        self,
        channel_id: str,
        audio: np.ndarray,
        speech_start_ts: float,
        speech_end_ts: float,
        speech_id: str | None,
        is_final: bool,
    ) -> None:
        try:
            engine_status = self._engine.status()
            self._dispatch_status({
                "state": "loading",
                "channel_id": channel_id,
                "message": f"Loading {engine_status['asr_backend']} model {engine_status['model']}",
                **engine_status,
            })
            segments = self._engine.transcribe(audio)
        except Exception as exc:
            logger.error("Whisper inference error on channel %s: %s", channel_id, exc)
            self._dispatch_status({
                "state": "error",
                "channel_id": channel_id,
                "message": str(exc),
                **self._engine.status(),
            })
            return

        self._dispatch_status({
            "state": "ready",
            "channel_id": channel_id,
            "message": "Model ready",
            **self._engine.status(),
        })

        if not segments:
            return

        result = TranscriptionResult(
            channel_id=channel_id,
            segments=segments,
            source_audio=audio,
            language=self._engine.last_language,
            speech_start_ts=speech_start_ts,
            speech_end_ts=speech_end_ts,
            speech_id=speech_id,
            is_final=is_final,
        )
        # Marshal back to the asyncio event loop safely
        asyncio.run_coroutine_threadsafe(self._dispatch(result), self._loop)

    async def _dispatch(self, result: TranscriptionResult) -> None:
        try:
            self._on_result(result)
        except Exception as exc:
            logger.error("Result dispatch error: %s", exc)

    def _dispatch_status(self, status: dict) -> None:
        if self._on_status is None:
            return
        asyncio.run_coroutine_threadsafe(self._dispatch_status_async(status), self._loop)

    async def _dispatch_status_async(self, status: dict) -> None:
        try:
            self._on_status(status)
        except Exception as exc:
            logger.error("Status dispatch error: %s", exc)
