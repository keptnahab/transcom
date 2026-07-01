from __future__ import annotations
import numpy as np


class RingBuffer:
    """
    Fixed-capacity circular buffer for float32 audio frames.

    Audio is appended continuously via `write`. When enough frames have
    accumulated (`chunk_size` since the last read head), `next_chunk` returns
    a NumPy array of length `chunk_size + overlap_size` (overlap drawn from
    the frames that preceded the current chunk), then advances the read head
    by `chunk_size` frames — leaving `overlap_size` frames to be repeated at
    the start of the following chunk so Whisper never cuts a word at a
    boundary.
    """

    def __init__(self, capacity: int, chunk_size: int, overlap_size: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap_size < 0:
            raise ValueError("overlap_size must not be negative")
        if chunk_size + overlap_size > capacity:
            raise ValueError("chunk_size + overlap_size must fit within capacity")
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._chunk_size = chunk_size
        self._overlap_size = overlap_size
        self._write_pos = 0   # absolute frame count written
        self._read_pos = 0    # absolute frame count consumed (read head)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, frames: np.ndarray) -> None:
        """Append mono float32 frames. Wraps if needed."""
        frames = np.asarray(frames, dtype=np.float32).ravel()
        n = len(frames)
        if n == 0:
            return
        if n > self._capacity:
            # Keep only the last `capacity` frames
            frames = frames[-self._capacity :]
            n = self._capacity

        start = self._write_pos % self._capacity
        end = start + n
        if end <= self._capacity:
            self._buf[start:end] = frames
        else:
            split = self._capacity - start
            self._buf[start:] = frames[:split]
            self._buf[: end - self._capacity] = frames[split:]
        self._write_pos += n

    def next_chunk(self) -> np.ndarray | None:
        """
        Return the next `overlap + chunk` window if enough data is available,
        otherwise None. Advances the read head by `chunk_size` frames.

        The returned array is always a new copy (safe to hand to another thread).
        """
        available = self._write_pos - self._read_pos
        needed = self._chunk_size + self._overlap_size
        if self._read_pos < self._overlap_size:
            # Not enough history yet for the leading overlap on the very first chunk
            actual_overlap = self._read_pos
        else:
            actual_overlap = self._overlap_size

        total_needed_for_chunk = self._chunk_size + actual_overlap
        if available < total_needed_for_chunk:
            return None

        start_abs = self._read_pos - actual_overlap
        length = actual_overlap + self._chunk_size
        chunk = self._read_at(start_abs, length)

        self._read_pos += self._chunk_size
        return chunk

    @property
    def buffered_frames(self) -> int:
        """Frames written but not yet consumed."""
        return self._write_pos - self._read_pos

    def reset(self) -> None:
        self._buf[:] = 0
        self._write_pos = 0
        self._read_pos = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_at(self, abs_pos: int, length: int) -> np.ndarray:
        """Read `length` frames starting at absolute position `abs_pos`."""
        start = abs_pos % self._capacity
        end = start + length
        if end <= self._capacity:
            return self._buf[start:end].copy()
        split = self._capacity - start
        return np.concatenate([self._buf[start:], self._buf[: length - split]])
