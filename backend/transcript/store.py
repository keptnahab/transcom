from __future__ import annotations
from difflib import SequenceMatcher
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

import backend.config as cfg

_DEDUP_WINDOW_SECONDS = 12.0
_DEDUP_SIMILARITY = 0.86


class TranscriptStore:
    """
    Dual-layer transcript storage: in-memory list (fast access) + SQLite (persistence).

    All public methods are thread-safe.
    """

    _CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS segments (
        segment_id   TEXT PRIMARY KEY,
        channel_id   TEXT NOT NULL,
        text         TEXT NOT NULL,
        timestamp    REAL NOT NULL,
        confidence   REAL NOT NULL DEFAULT 1.0,
        requires_confirmation INTEGER NOT NULL DEFAULT 0,
        confirmation_acknowledged INTEGER NOT NULL DEFAULT 0,
        confirmation_acknowledged_at REAL,
        confirmation_acknowledged_by TEXT,
        raw_text TEXT,
        safety_confirmation_raw_text TEXT,
        safety_confirmation_model TEXT,
        safety_confirmation_used INTEGER NOT NULL DEFAULT 0,
        safety_command_id TEXT,
        safety_match_score REAL,
        safety_match_margin REAL,
        safety_rejection_reason TEXT,
        safety_catalog_id TEXT,
        safety_catalog_sha256 TEXT,
        speaker_id   TEXT,
        speaker_name TEXT,
        speaker_color TEXT,
        speaker_confidence REAL NOT NULL DEFAULT 0.0,
        corrected_speaker_id TEXT,
        corrected_speaker_name TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_segments_ts ON segments (timestamp);
    CREATE INDEX IF NOT EXISTS idx_segments_ch ON segments (channel_id);
    CREATE TABLE IF NOT EXISTS confirmation_events (
        event_id TEXT PRIMARY KEY,
        segment_id TEXT NOT NULL,
        acknowledged_at REAL NOT NULL,
        acknowledged_by TEXT NOT NULL,
        text TEXT NOT NULL,
        raw_text TEXT,
        safety_confirmation_raw_text TEXT,
        safety_confirmation_model TEXT,
        safety_confirmation_used INTEGER NOT NULL DEFAULT 0,
        safety_command_id TEXT,
        safety_catalog_id TEXT,
        safety_catalog_sha256 TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_confirmation_events_segment
        ON confirmation_events (segment_id, acknowledged_at);
    """

    def __init__(self, db_path: str = cfg.DB_PATH) -> None:
        self._lock = threading.Lock()
        self._segments: list[dict] = []
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        for stmt in self._CREATE_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._db.execute(stmt)
        self._migrate()
        self._db.commit()
        self._load_from_db()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_segment(
        self,
        channel_id: str,
        text: str,
        timestamp: float,
        confidence: float = 1.0,
        requires_confirmation: bool = False,
        raw_text: str | None = None,
        safety_confirmation_raw_text: str | None = None,
        safety_confirmation_model: str | None = None,
        safety_confirmation_used: bool = False,
        safety_command_id: str | None = None,
        safety_match_score: float | None = None,
        safety_match_margin: float | None = None,
        safety_rejection_reason: str | None = None,
        safety_catalog_id: str | None = None,
        safety_catalog_sha256: str | None = None,
        speaker_id: str | None = None,
        speaker_name: str | None = None,
        speaker_color: str | None = None,
        speaker_confidence: float = 0.0,
    ) -> dict:
        if not text.strip():
            return {}
        seg = {
            "segment_id": str(uuid.uuid4()),
            "channel_id": channel_id,
            "text": text.strip(),
            "timestamp": timestamp,
            "confidence": confidence,
            "requires_confirmation": bool(requires_confirmation),
            "confirmation_acknowledged": False,
            "confirmation_acknowledged_at": None,
            "confirmation_acknowledged_by": None,
            "raw_text": raw_text.strip() if raw_text and raw_text.strip() else None,
            "safety_confirmation_raw_text": (
                safety_confirmation_raw_text.strip()
                if safety_confirmation_raw_text and safety_confirmation_raw_text.strip()
                else None
            ),
            "safety_confirmation_model": safety_confirmation_model,
            "safety_confirmation_used": bool(safety_confirmation_used),
            "safety_command_id": safety_command_id,
            "safety_match_score": safety_match_score,
            "safety_match_margin": safety_match_margin,
            "safety_rejection_reason": safety_rejection_reason,
            "safety_catalog_id": safety_catalog_id,
            "safety_catalog_sha256": safety_catalog_sha256,
            "speaker_id": speaker_id,
            "speaker_name": speaker_name,
            "speaker_color": speaker_color,
            "speaker_confidence": speaker_confidence,
            "corrected_speaker_id": None,
            "corrected_speaker_name": None,
        }
        with self._lock:
            duplicate = self._find_recent_duplicate(seg)
            if duplicate is not None:
                if len(seg["text"]) > len(duplicate["text"]):
                    self._replace_segment_text(duplicate, seg)
                    return dict(duplicate)
                if seg["requires_confirmation"] and not duplicate["requires_confirmation"]:
                    duplicate["requires_confirmation"] = True
                    duplicate["confirmation_acknowledged"] = False
                    duplicate["confirmation_acknowledged_at"] = None
                    duplicate["confirmation_acknowledged_by"] = None
                    self._db.execute(
                        """UPDATE segments SET requires_confirmation = 1,
                           confirmation_acknowledged = 0,
                           confirmation_acknowledged_at = NULL,
                           confirmation_acknowledged_by = NULL
                           WHERE segment_id = ?""",
                        (duplicate["segment_id"],),
                    )
                    self._db.commit()
                    return dict(duplicate)
                return {}
            self._segments.append(seg)
            self._db.execute(
                """
                INSERT INTO segments (
                    segment_id, channel_id, text, timestamp, confidence, requires_confirmation,
                    confirmation_acknowledged, confirmation_acknowledged_at,
                    confirmation_acknowledged_by, raw_text,
                    safety_confirmation_raw_text, safety_confirmation_model,
                    safety_confirmation_used, safety_command_id, safety_match_score,
                    safety_match_margin, safety_rejection_reason,
                    safety_catalog_id, safety_catalog_sha256,
                    speaker_id, speaker_name, speaker_color, speaker_confidence,
                    corrected_speaker_id, corrected_speaker_name
                ) VALUES (
                    :segment_id, :channel_id, :text, :timestamp, :confidence, :requires_confirmation,
                    :confirmation_acknowledged, :confirmation_acknowledged_at,
                    :confirmation_acknowledged_by, :raw_text,
                    :safety_confirmation_raw_text, :safety_confirmation_model,
                    :safety_confirmation_used, :safety_command_id, :safety_match_score,
                    :safety_match_margin, :safety_rejection_reason,
                    :safety_catalog_id, :safety_catalog_sha256,
                    :speaker_id, :speaker_name, :speaker_color, :speaker_confidence,
                    :corrected_speaker_id, :corrected_speaker_name
                )
                """,
                seg,
            )
            self._db.commit()
        return seg

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_all(self, since: float | None = None) -> list[dict]:
        with self._lock:
            if since is None:
                return list(self._segments)
            return [s for s in self._segments if s["timestamp"] >= since]

    def search(self, query: str) -> list[dict]:
        if not query.strip():
            return self.get_all()
        q = query.strip().lower()
        with self._lock:
            return [s for s in self._segments if q in s["text"].lower()]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> None:
        with self._lock:
            self._segments.clear()
            self._db.execute("DELETE FROM confirmation_events")
            self._db.execute("DELETE FROM segments")
            self._db.commit()

    def correct_speaker(self, segment_id: str, speaker_id: str | None, speaker_name: str | None) -> dict:
        with self._lock:
            for seg in self._segments:
                if seg["segment_id"] == segment_id:
                    seg["corrected_speaker_id"] = speaker_id
                    seg["corrected_speaker_name"] = speaker_name
                    self._db.execute(
                        """
                        UPDATE segments
                        SET corrected_speaker_id = ?, corrected_speaker_name = ?
                        WHERE segment_id = ?
                        """,
                        (speaker_id, speaker_name, segment_id),
                    )
                    self._db.commit()
                    return dict(seg)
        raise KeyError(f"Segment not found: {segment_id}")

    def acknowledge_confirmation(self, segment_id: str, acknowledged_by: str = "system") -> dict:
        """Record an explicit operator acknowledgement for a flagged segment."""
        with self._lock:
            for seg in self._segments:
                if seg["segment_id"] != segment_id:
                    continue
                if not seg["requires_confirmation"]:
                    raise ValueError("Segment does not require confirmation")
                actor = str(acknowledged_by or "").strip()
                if not actor:
                    raise ValueError("Confirmation requires an actor")
                acknowledged_at = time.time()
                seg["confirmation_acknowledged"] = True
                seg["confirmation_acknowledged_at"] = acknowledged_at
                seg["confirmation_acknowledged_by"] = actor
                self._db.execute(
                    """
                    UPDATE segments
                    SET confirmation_acknowledged = 1,
                        confirmation_acknowledged_at = ?, confirmation_acknowledged_by = ?
                    WHERE segment_id = ?
                    """,
                    (acknowledged_at, actor, segment_id),
                )
                self._db.execute(
                    """
                    INSERT INTO confirmation_events (
                        event_id, segment_id, acknowledged_at, acknowledged_by,
                        text, raw_text, safety_confirmation_raw_text,
                        safety_confirmation_model, safety_confirmation_used,
                        safety_command_id, safety_catalog_id, safety_catalog_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), segment_id, acknowledged_at, actor,
                        seg["text"], seg.get("raw_text"),
                        seg.get("safety_confirmation_raw_text"),
                        seg.get("safety_confirmation_model"),
                        int(bool(seg.get("safety_confirmation_used"))),
                        seg.get("safety_command_id"),
                        seg.get("safety_catalog_id"), seg.get("safety_catalog_sha256"),
                    ),
                )
                self._db.commit()
                return dict(seg)
        raise KeyError(f"Segment not found: {segment_id}")

    def get_confirmation_events(self, segment_id: str | None = None) -> list[dict]:
        with self._lock:
            if segment_id is None:
                cur = self._db.execute(
                    """SELECT event_id, segment_id, acknowledged_at, acknowledged_by, text,
                              raw_text, safety_confirmation_raw_text,
                              safety_confirmation_model, safety_confirmation_used,
                              safety_command_id, safety_catalog_id, safety_catalog_sha256
                       FROM confirmation_events ORDER BY acknowledged_at"""
                )
            else:
                cur = self._db.execute(
                    """SELECT event_id, segment_id, acknowledged_at, acknowledged_by, text,
                              raw_text, safety_confirmation_raw_text,
                              safety_confirmation_model, safety_confirmation_used,
                              safety_command_id, safety_catalog_id, safety_catalog_sha256
                       FROM confirmation_events WHERE segment_id = ? ORDER BY acknowledged_at""",
                    (segment_id,),
                )
            keys = (
                "event_id", "segment_id", "acknowledged_at", "acknowledged_by", "text",
                "raw_text", "safety_confirmation_raw_text", "safety_confirmation_model",
                "safety_confirmation_used", "safety_command_id", "safety_catalog_id",
                "safety_catalog_sha256",
            )
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self._db.close()

    def reopen(self, db_path: str) -> None:
        with self._lock:
            self._db.close()
            self._segments.clear()
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            for stmt in self._CREATE_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    self._db.execute(stmt)
            self._migrate()
            self._db.commit()
            self._load_from_db()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_from_db(self) -> None:
        cur = self._db.execute(
            """
            SELECT segment_id, channel_id, text, timestamp, confidence, requires_confirmation,
                   confirmation_acknowledged, confirmation_acknowledged_at,
                   confirmation_acknowledged_by, raw_text,
                   safety_confirmation_raw_text, safety_confirmation_model,
                   safety_confirmation_used, safety_command_id, safety_match_score,
                   safety_match_margin, safety_rejection_reason,
                   safety_catalog_id, safety_catalog_sha256,
                   speaker_id, speaker_name, speaker_color, speaker_confidence,
                   corrected_speaker_id, corrected_speaker_name
            FROM segments ORDER BY timestamp
            """
        )
        self._segments = [
            {
                "segment_id": r[0],
                "channel_id": r[1],
                "text": r[2],
                "timestamp": r[3],
                "confidence": r[4],
                "requires_confirmation": bool(r[5]),
                "confirmation_acknowledged": bool(r[6]),
                "confirmation_acknowledged_at": r[7],
                "confirmation_acknowledged_by": r[8],
                "raw_text": r[9],
                "safety_confirmation_raw_text": r[10],
                "safety_confirmation_model": r[11],
                "safety_confirmation_used": bool(r[12]),
                "safety_command_id": r[13],
                "safety_match_score": r[14],
                "safety_match_margin": r[15],
                "safety_rejection_reason": r[16],
                "safety_catalog_id": r[17],
                "safety_catalog_sha256": r[18],
                "speaker_id": r[19],
                "speaker_name": r[20],
                "speaker_color": r[21],
                "speaker_confidence": r[22],
                "corrected_speaker_id": r[23],
                "corrected_speaker_name": r[24],
            }
            for r in cur.fetchall()
        ]

    def _migrate(self) -> None:
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(segments)").fetchall()}
        columns = {
            "speaker_id": "TEXT",
            "requires_confirmation": "INTEGER NOT NULL DEFAULT 0",
            "confirmation_acknowledged": "INTEGER NOT NULL DEFAULT 0",
            "confirmation_acknowledged_at": "REAL",
            "confirmation_acknowledged_by": "TEXT",
            "raw_text": "TEXT",
            "safety_confirmation_raw_text": "TEXT",
            "safety_confirmation_model": "TEXT",
            "safety_confirmation_used": "INTEGER NOT NULL DEFAULT 0",
            "safety_command_id": "TEXT",
            "safety_match_score": "REAL",
            "safety_match_margin": "REAL",
            "safety_rejection_reason": "TEXT",
            "safety_catalog_id": "TEXT",
            "safety_catalog_sha256": "TEXT",
            "speaker_name": "TEXT",
            "speaker_color": "TEXT",
            "speaker_confidence": "REAL NOT NULL DEFAULT 0.0",
            "corrected_speaker_id": "TEXT",
            "corrected_speaker_name": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                self._db.execute(f"ALTER TABLE segments ADD COLUMN {name} {definition}")
        event_existing = {
            row[1] for row in self._db.execute("PRAGMA table_info(confirmation_events)").fetchall()
        }
        event_columns = {
            "safety_confirmation_raw_text": "TEXT",
            "safety_confirmation_model": "TEXT",
            "safety_confirmation_used": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in event_columns.items():
            if name not in event_existing:
                self._db.execute(f"ALTER TABLE confirmation_events ADD COLUMN {name} {definition}")

    def _find_recent_duplicate(self, seg: dict) -> dict | None:
        # Every safety-mode utterance is operationally significant, including
        # an immediate repetition and an unresolved attempt.
        if seg.get("safety_match_score") is not None:
            return None
        text = self._normalize_text(seg["text"])
        if not text:
            return None
        for existing in reversed(self._segments):
            if existing["channel_id"] != seg["channel_id"]:
                continue
            if abs(seg["timestamp"] - existing["timestamp"]) > _DEDUP_WINDOW_SECONDS:
                break
            if existing.get("safety_match_score") is not None:
                continue
            other = self._normalize_text(existing["text"])
            if not other:
                continue
            if text == other or text in other or other in text:
                return existing
            if SequenceMatcher(None, text, other).ratio() >= _DEDUP_SIMILARITY:
                return existing
        return None

    def _replace_segment_text(self, existing: dict, replacement: dict) -> None:
        requires_confirmation = bool(
            existing.get("requires_confirmation") or replacement.get("requires_confirmation")
        )
        for key in (
            "text",
            "confidence",
            "raw_text",
            "safety_confirmation_raw_text",
            "safety_confirmation_model",
            "safety_confirmation_used",
            "safety_command_id",
            "safety_match_score",
            "safety_match_margin",
            "safety_rejection_reason",
            "safety_catalog_id",
            "safety_catalog_sha256",
            "speaker_id",
            "speaker_name",
            "speaker_color",
            "speaker_confidence",
        ):
            existing[key] = replacement[key]
        existing["requires_confirmation"] = requires_confirmation
        # A changed transcript must be acknowledged again, even if the shorter
        # predecessor had already been reviewed.
        existing["confirmation_acknowledged"] = False
        existing["confirmation_acknowledged_at"] = None
        existing["confirmation_acknowledged_by"] = None
        self._db.execute(
            """
            UPDATE segments
            SET text = ?, confidence = ?, requires_confirmation = ?, confirmation_acknowledged = 0,
                confirmation_acknowledged_at = NULL, confirmation_acknowledged_by = NULL,
                raw_text = ?, safety_confirmation_raw_text = ?,
                safety_confirmation_model = ?, safety_confirmation_used = ?,
                safety_command_id = ?, safety_match_score = ?,
                safety_match_margin = ?, safety_rejection_reason = ?,
                safety_catalog_id = ?, safety_catalog_sha256 = ?,
                speaker_id = ?, speaker_name = ?,
                speaker_color = ?, speaker_confidence = ?
            WHERE segment_id = ?
            """,
            (
                existing["text"],
                existing["confidence"],
                int(existing["requires_confirmation"]),
                existing["raw_text"],
                existing["safety_confirmation_raw_text"],
                existing["safety_confirmation_model"],
                int(bool(existing["safety_confirmation_used"])),
                existing["safety_command_id"],
                existing["safety_match_score"],
                existing["safety_match_margin"],
                existing["safety_rejection_reason"],
                existing["safety_catalog_id"],
                existing["safety_catalog_sha256"],
                existing["speaker_id"],
                existing["speaker_name"],
                existing["speaker_color"],
                existing["speaker_confidence"],
                existing["segment_id"],
            ),
        )
        self._db.commit()

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", "", text.lower(), flags=re.UNICODE)).strip()
