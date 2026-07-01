from __future__ import annotations
import logging
import queue
import threading
import time
from typing import Callable
import numpy as np
import sounddevice as sd

from backend.audio.ring_buffer import RingBuffer
import backend.config as cfg

logger = logging.getLogger(__name__)


AudioChunkCallback = Callable[[str, np.ndarray, float], None]
"""callback(channel_id, audio_chunk, wall_clock_timestamp)"""


class ChannelCapture:
    """
    Captures audio from one input device and feeds chunks to a callback.

    Lifecycle: create → start() → ... → stop()

    In test mode (cfg.AUDIO_SOURCE = "file:///path"), reads from a WAV file
    instead of a live device.
    """

    def __init__(
        self,
        channel_id: str,
        device_index: int,
        on_chunk: AudioChunkCallback,
    ) -> None:
        self._channel_id = channel_id
        self._device_index = device_index
        self._on_chunk = on_chunk

        chunk_frames = int(cfg.CHUNK_SECONDS * cfg.SAMPLE_RATE)
        overlap_frames = int(cfg.OVERLAP_SECONDS * cfg.SAMPLE_RATE)
        # Buffer capacity = 30 seconds worth of audio
        capacity = cfg.SAMPLE_RATE * 30

        self._ring = RingBuffer(capacity, chunk_frames, overlap_frames)
        self._chunk_seconds = cfg.CHUNK_SECONDS
        self._sample_rate = cfg.SAMPLE_RATE

        self._raw_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"capture-{channel_id}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        if cfg.AUDIO_SOURCE and cfg.AUDIO_SOURCE.startswith("file://"):
            self._run_from_file(cfg.AUDIO_SOURCE[7:])
        else:
            self._run_from_device()

    def _run_from_device(self) -> None:
        def callback(indata: np.ndarray, frames: int, _time_info, _status) -> None:
            try:
                self._raw_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # Drop frames if consumer is too slow

        stream = sd.InputStream(
            device=self._device_index,
            channels=1,
            samplerate=self._sample_rate,
            dtype="float32",
            blocksize=cfg.CAPTURE_BLOCK_SIZE,
            callback=callback,
        )
        with stream:
            self._drain_queue_loop()

    def _run_from_file(self, path: str) -> None:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=False)
        if data.ndim == 2:
            data = data[:, 0]  # mono
        if sr != self._sample_rate:
            # Simple nearest-neighbor resample
            ratio = self._sample_rate / sr
            n_out = int(len(data) * ratio)
            indices = (np.arange(n_out) / ratio).astype(int)
            indices = np.clip(indices, 0, len(data) - 1)
            data = data[indices]

        block = cfg.CAPTURE_BLOCK_SIZE
        for i in range(0, len(data), block):
            if self._stop_event.is_set():
                return
            chunk = data[i : i + block]
            self._process_frames(chunk)
            # Simulate real-time pacing
            time.sleep(len(chunk) / self._sample_rate)

        flush_frames = int((cfg.OVERLAP_SECONDS + cfg.CHUNK_SECONDS) * self._sample_rate)
        remaining = flush_frames
        silence = np.zeros(block, dtype=np.float32)
        while remaining > 0 and not self._stop_event.is_set():
            n = min(block, remaining)
            self._process_frames(silence[:n])
            time.sleep(n / self._sample_rate)
            remaining -= n

        logger.info("Test audio source finished for channel %s", self._channel_id)
        while not self._stop_event.is_set():
            time.sleep(0.1)

    def _drain_queue_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                frames = self._raw_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            self._ring.write(frames)

            self._emit_ready_chunks()

    def _process_frames(self, frames: np.ndarray) -> None:
        self._ring.write(frames)
        self._emit_ready_chunks()

    def _emit_ready_chunks(self) -> None:
        while True:
            chunk = self._ring.next_chunk()
            if chunk is None:
                return
            wall_ts = time.time()
            try:
                self._on_chunk(self._channel_id, chunk, wall_ts)
            except Exception as exc:
                logger.exception("Audio chunk callback failed for channel %s: %s", self._channel_id, exc)
