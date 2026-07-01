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
    wall_clock_ts: float   # time.time() at chunk-slice moment
    chunk_duration: float  # seconds of audio in the chunk
    source_audio: np.ndarray
    context_prefix_seconds: float = 0.0


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
        wall_clock_ts: float,
        context_prefix_seconds: float = 0.0,
    ) -> None:
        chunk_duration = len(audio) / cfg.SAMPLE_RATE
        self._executor.submit(
            self._infer,
            channel_id,
            audio,
            wall_clock_ts,
            chunk_duration,
            context_prefix_seconds,
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
        wall_clock_ts: float,
        chunk_duration: float,
        context_prefix_seconds: float,
    ) -> None:
        try:
            model_name = cfg.MLX_WHISPER_MODEL if cfg.WHISPER_BACKEND == "mlx" else cfg.WHISPER_MODEL
            self._dispatch_status({
                "state": "loading",
                "channel_id": channel_id,
                "message": f"Loading {cfg.WHISPER_BACKEND} model {model_name}",
            })
            segments = self._engine.transcribe(audio)
        except Exception as exc:
            logger.error("Whisper inference error on channel %s: %s", channel_id, exc)
            self._dispatch_status({
                "state": "error",
                "channel_id": channel_id,
                "message": str(exc),
            })
            return

        self._dispatch_status({
            "state": "ready",
            "channel_id": channel_id,
            "message": "Model ready",
        })

        if not segments:
            return

        result = TranscriptionResult(
            channel_id=channel_id,
            segments=segments,
            wall_clock_ts=wall_clock_ts,
            chunk_duration=chunk_duration,
            source_audio=audio,
            context_prefix_seconds=context_prefix_seconds,
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
