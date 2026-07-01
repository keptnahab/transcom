from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from backend.audio.capture import ChannelCapture


_DEFAULT_COLORS = [
    "#3498db", "#e74c3c", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#e91e63",
]
_color_idx = 0


def _next_color() -> str:
    global _color_idx
    color = _DEFAULT_COLORS[_color_idx % len(_DEFAULT_COLORS)]
    _color_idx += 1
    return color


@dataclass
class Channel:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "New Channel"
    device_index: int = 0
    color: str = field(default_factory=_next_color)
    label: str = ""
    is_active: bool = False
    _capture: object = field(default=None, repr=False, compare=False)  # ChannelCapture | None

    def __post_init__(self):
        if not self.label:
            self.label = self.name[:4].upper()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "device_index": self.device_index,
            "color": self.color,
            "label": self.label,
            "is_active": self.is_active,
        }
