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
        speaker_id   TEXT,
        speaker_name TEXT,
        speaker_color TEXT,
        speaker_confidence REAL NOT NULL DEFAULT 0.0,
        corrected_speaker_id TEXT,
        corrected_speaker_name TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_segments_ts ON segments (timestamp);
    CREATE INDEX IF NOT EXISTS idx_segments_ch ON segments (channel_id);
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
                return {}
            self._segments.append(seg)
            self._db.execute(
                """
                INSERT INTO segments (
                    segment_id, channel_id, text, timestamp, confidence,
                    speaker_id, speaker_name, speaker_color, speaker_confidence,
                    corrected_speaker_id, corrected_speaker_name
                ) VALUES (
                    :segment_id, :channel_id, :text, :timestamp, :confidence,
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
            SELECT segment_id, channel_id, text, timestamp, confidence,
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
                "speaker_id": r[5],
                "speaker_name": r[6],
                "speaker_color": r[7],
                "speaker_confidence": r[8],
                "corrected_speaker_id": r[9],
                "corrected_speaker_name": r[10],
            }
            for r in cur.fetchall()
        ]

    def _migrate(self) -> None:
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(segments)").fetchall()}
        columns = {
            "speaker_id": "TEXT",
            "speaker_name": "TEXT",
            "speaker_color": "TEXT",
            "speaker_confidence": "REAL NOT NULL DEFAULT 0.0",
            "corrected_speaker_id": "TEXT",
            "corrected_speaker_name": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                self._db.execute(f"ALTER TABLE segments ADD COLUMN {name} {definition}")

    def _find_recent_duplicate(self, seg: dict) -> dict | None:
        text = self._normalize_text(seg["text"])
        if not text:
            return None
        for existing in reversed(self._segments):
            if existing["channel_id"] != seg["channel_id"]:
                continue
            if abs(seg["timestamp"] - existing["timestamp"]) > _DEDUP_WINDOW_SECONDS:
                break
            other = self._normalize_text(existing["text"])
            if not other:
                continue
            if text == other or text in other or other in text:
                return existing
            if SequenceMatcher(None, text, other).ratio() >= _DEDUP_SIMILARITY:
                return existing
        return None

    def _replace_segment_text(self, existing: dict, replacement: dict) -> None:
        for key in (
            "text",
            "confidence",
            "speaker_id",
            "speaker_name",
            "speaker_color",
            "speaker_confidence",
        ):
            existing[key] = replacement[key]
        self._db.execute(
            """
            UPDATE segments
            SET text = ?, confidence = ?, speaker_id = ?, speaker_name = ?,
                speaker_color = ?, speaker_confidence = ?
            WHERE segment_id = ?
            """,
            (
                existing["text"],
                existing["confidence"],
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
