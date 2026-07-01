from __future__ import annotations
import logging
from typing import Callable

from backend.channels.channel import Channel
from backend.audio.capture import ChannelCapture, AudioChunkCallback

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    CRUD for channels and lifecycle management of their ChannelCapture threads.

    `on_chunk` is the callback forwarded to each ChannelCapture — it should
    submit audio to the TranscriptionPool.
    """

    def __init__(self, on_chunk: AudioChunkCallback) -> None:
        self._on_chunk = on_chunk
        self._channels: dict[str, Channel] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_channel(
        self,
        name: str,
        device_index: int,
        color: str | None = None,
        label: str | None = None,
    ) -> Channel:
        ch = Channel(name=name, device_index=device_index)
        if color:
            ch.color = color
        if label:
            ch.label = label
        self._channels[ch.id] = ch
        logger.info("Channel created: %s (%s)", ch.name, ch.id)
        return ch

    def update_channel(
        self,
        id_: str,
        name: str | None = None,
        device_index: int | None = None,
        color: str | None = None,
        label: str | None = None,
    ) -> Channel:
        ch = self._get(id_)
        if name is not None:
            ch.name = name
        if device_index is not None:
            if ch.is_active:
                self._stop_capture(ch)
            ch.device_index = device_index
        if color is not None:
            ch.color = color
        if label is not None:
            ch.label = label
        return ch

    def delete_channel(self, id_: str) -> None:
        ch = self._get(id_)
        if ch.is_active:
            self._stop_capture(ch)
        del self._channels[id_]
        logger.info("Channel deleted: %s", id_)

    def list_channels(self) -> list[Channel]:
        return list(self._channels.values())

    def get_channel(self, id_: str) -> Channel:
        return self._get(id_)

    # ------------------------------------------------------------------
    # Capture lifecycle
    # ------------------------------------------------------------------

    def start_channel(self, id_: str) -> Channel:
        ch = self._get(id_)
        if ch.is_active:
            return ch
        self._start_capture(ch)
        return ch

    def stop_channel(self, id_: str) -> Channel:
        ch = self._get(id_)
        if not ch.is_active:
            return ch
        self._stop_capture(ch)
        return ch

    def stop_all(self) -> None:
        for ch in list(self._channels.values()):
            if ch.is_active:
                self._stop_capture(ch)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, id_: str) -> Channel:
        ch = self._channels.get(id_)
        if ch is None:
            raise KeyError(f"Channel not found: {id_}")
        return ch

    def _start_capture(self, ch: Channel) -> None:
        capture = ChannelCapture(
            channel_id=ch.id,
            device_index=ch.device_index,
            on_chunk=self._on_chunk,
        )
        capture.start()
        ch._capture = capture
        ch.is_active = True
        logger.info("Capture started: %s", ch.id)

    def _stop_capture(self, ch: Channel) -> None:
        if ch._capture is not None:
            ch._capture.stop()
            ch._capture = None
        ch.is_active = False
        logger.info("Capture stopped: %s", ch.id)
