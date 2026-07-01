from __future__ import annotations
import sounddevice as sd
from typing import TypedDict


class AudioDevice(TypedDict):
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool


def list_input_devices() -> list[AudioDevice]:
    """Return all audio devices that have at least one input channel."""
    devices = sd.query_devices()
    default_input_idx = sd.default.device[0]

    result: list[AudioDevice] = []
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] < 1:
            continue
        result.append(
            AudioDevice(
                index=idx,
                name=dev["name"],
                max_input_channels=dev["max_input_channels"],
                default_sample_rate=float(dev["default_samplerate"]),
                is_default=(idx == default_input_idx),
            )
        )
    return result
