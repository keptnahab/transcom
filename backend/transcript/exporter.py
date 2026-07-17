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
            marker = ""
            if seg.get("requires_confirmation"):
                marker = "[CONFIRMED] " if seg.get("confirmation_acknowledged") else "[CONFIRM] "
            command = f"[COMMAND {seg['safety_command_id']}] " if seg.get("safety_command_id") else ""
            raw = ""
            if seg.get("raw_text") and seg["raw_text"] != seg["text"]:
                raw = f" [RAW: {seg['raw_text']}]"
            confirmation = ""
            if seg.get("safety_confirmation_used"):
                confirmation = (
                    f" [SAFETY-CONFIRM {seg.get('safety_confirmation_model') or 'unknown'}: "
                    f"{seg.get('safety_confirmation_raw_text') or ''}]"
                )
            f.write(
                f"[{_ts(seg['timestamp'])}]  {seg['channel_id'][:8]}  "
                f"{marker}{command}{seg['text']}{raw}{confirmation}\n"
            )


def _export_csv(segments: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "channel_id", "text", "confidence",
            "requires_confirmation", "confirmation_acknowledged",
            "confirmation_acknowledged_at", "confirmation_acknowledged_by",
            "raw_text", "safety_confirmation_raw_text", "safety_confirmation_model",
            "safety_confirmation_used", "safety_command_id", "safety_match_score",
            "safety_match_margin", "safety_rejection_reason",
            "safety_catalog_id", "safety_catalog_sha256",
        ])
        for seg in segments:
            writer.writerow([
                datetime.datetime.fromtimestamp(seg["timestamp"]).isoformat(),
                seg["channel_id"],
                seg["text"],
                f"{seg['confidence']:.3f}",
                bool(seg.get("requires_confirmation")),
                bool(seg.get("confirmation_acknowledged")),
                seg.get("confirmation_acknowledged_at") or "",
                seg.get("confirmation_acknowledged_by") or "",
                seg.get("raw_text") or "",
                seg.get("safety_confirmation_raw_text") or "",
                seg.get("safety_confirmation_model") or "",
                bool(seg.get("safety_confirmation_used")),
                seg.get("safety_command_id") or "",
                "" if seg.get("safety_match_score") is None else f"{seg['safety_match_score']:.4f}",
                "" if seg.get("safety_match_margin") is None else f"{seg['safety_match_margin']:.4f}",
                seg.get("safety_rejection_reason") or "",
                seg.get("safety_catalog_id") or "",
                seg.get("safety_catalog_sha256") or "",
            ])
