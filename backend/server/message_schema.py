"""
All WebSocket message types as TypedDicts.

Envelope: {"type": str, "id": str | None, "payload": dict}

Inbound  = frontend → backend
Outbound = backend → frontend
"""
from __future__ import annotations
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class Message(TypedDict):
    type: str
    id: str | None
    payload: dict[str, Any]


def make(type_: str, payload: dict[str, Any], id_: str | None = None) -> dict:
    return {"type": type_, "id": id_, "payload": payload}


# ---------------------------------------------------------------------------
# Inbound payload types
# ---------------------------------------------------------------------------

class AddChannelPayload(TypedDict):
    name: str
    device_index: int
    color: str        # CSS hex, e.g. "#e74c3c"
    label: str | None # short tag, e.g. "CH1"


class UpdateChannelPayload(TypedDict):
    id: str
    name: str | None
    color: str | None
    label: str | None


class ChannelIdPayload(TypedDict):
    id: str


class SearchPayload(TypedDict):
    query: str


class ExportPayload(TypedDict):
    format: str   # "txt" or "csv"
    path: str


# ---------------------------------------------------------------------------
# Outbound payload types
# ---------------------------------------------------------------------------

class DeviceInfo(TypedDict):
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool


class ChannelInfo(TypedDict):
    id: str
    name: str
    device_index: int
    color: str
    label: str
    is_active: bool


class SegmentInfo(TypedDict):
    segment_id: str
    channel_id: str
    text: str
    timestamp: float   # Unix epoch seconds (absolute)
    confidence: float
    requires_confirmation: bool
    confirmation_acknowledged: bool
    confirmation_acknowledged_at: float | None
    confirmation_acknowledged_by: str | None
    raw_text: str | None
    safety_confirmation_raw_text: str | None
    safety_confirmation_model: str | None
    safety_confirmation_used: bool
    safety_command_id: str | None
    safety_match_score: float | None
    safety_match_margin: float | None
    safety_rejection_reason: str | None
    safety_catalog_id: str | None
    safety_catalog_sha256: str | None


class InitStatePayload(TypedDict):
    devices: list[DeviceInfo]
    channels: list[ChannelInfo]
    segments: list[SegmentInfo]


class ErrorPayload(TypedDict):
    message: str
    code: str | None
