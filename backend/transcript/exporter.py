from __future__ import annotations
import csv
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.transcript.store import TranscriptStore


def export(store: TranscriptStore, fmt: str, path: str) -> None:
    segments = store.get_all()
    if fmt == "csv":
        _export_csv(segments, path)
    else:
        _export_txt(segments, path)


def _ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _export_txt(segments: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"[{_ts(seg['timestamp'])}]  {seg['channel_id'][:8]}  {seg['text']}\n")


def _export_csv(segments: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "channel_id", "text", "confidence"])
        for seg in segments:
            writer.writerow([
                datetime.datetime.fromtimestamp(seg["timestamp"]).isoformat(),
                seg["channel_id"],
                seg["text"],
                f"{seg['confidence']:.3f}",
            ])
