from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import time
import uuid

import backend.config as cfg


@dataclass
class SessionInfo:
    id: str
    name: str
    root_dir: str
    session_dir: str
    db_path: str
    created_at: float
    started_at: float | None = None
    stopped_at: float | None = None
    status: str = "setup"


class SessionManager:
    """Creates v1 session folders and writes lightweight metadata."""

    def __init__(self, default_root: str = cfg.DEFAULT_SESSION_ROOT) -> None:
        self._default_root = Path(default_root).expanduser()
        self._current: SessionInfo | None = None

    @property
    def current(self) -> SessionInfo | None:
        return self._current

    def create(self, root_dir: str | None = None, name: str | None = None) -> SessionInfo:
        root = Path(root_dir).expanduser() if root_dir else self._default_root
        root.mkdir(parents=True, exist_ok=True)

        now = time.time()
        session_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:6]
        session_name = name.strip() if name and name.strip() else f"TransCom {time.strftime('%Y-%m-%d %H.%M')}"
        session_dir = root / session_id
        (session_dir / "exports").mkdir(parents=True, exist_ok=True)
        (session_dir / "profiles").mkdir(parents=True, exist_ok=True)

        info = SessionInfo(
            id=session_id,
            name=session_name,
            root_dir=str(root),
            session_dir=str(session_dir),
            db_path=str(session_dir / "transcript.db"),
            created_at=now,
        )
        self._current = info
        self._write_metadata()
        return info

    def start(self) -> SessionInfo:
        info = self._require_current()
        if info.started_at is None:
            info.started_at = time.time()
        info.stopped_at = None
        info.status = "live"
        self._write_metadata()
        return info

    def stop(self) -> SessionInfo:
        info = self._require_current()
        info.stopped_at = time.time()
        info.status = "stopped"
        self._write_metadata()
        return info

    def to_dict(self) -> dict | None:
        return asdict(self._current) if self._current else None

    def list_sessions(self, limit: int | None = 20) -> list[dict]:
        """Return saved sessions from the active transcript folder, newest first."""
        root = self._active_root()
        if not root.exists():
            return []

        sessions: list[SessionInfo] = []
        for metadata_path in root.glob("*/session.json"):
            try:
                info = self._read_metadata(metadata_path, root)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            sessions.append(info)

        sessions.sort(key=lambda item: item.created_at, reverse=True)
        if limit is not None:
            sessions = sessions[:max(0, limit)]
        return [asdict(info) for info in sessions]

    def open(self, session_id: str) -> SessionInfo:
        """Open an existing local session without creating or deleting files."""
        session_id = str(session_id or "").strip()
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("Invalid transcript id")

        root = self._active_root().resolve()
        session_dir = (root / session_id).resolve()
        if session_dir.parent != root:
            raise ValueError("Transcript is outside the selected folder")

        info = self._read_metadata(session_dir / "session.json", root)
        info.status = "stopped"
        self._current = info
        self._write_metadata()
        return info

    def _require_current(self) -> SessionInfo:
        if self._current is None:
            return self.create()
        return self._current

    def _active_root(self) -> Path:
        if self._current is not None:
            return Path(self._current.root_dir).expanduser()
        return self._default_root

    @staticmethod
    def _read_metadata(path: Path, root: Path) -> SessionInfo:
        data = json.loads(path.read_text(encoding="utf-8"))
        session_dir = path.parent
        session_id = session_dir.name
        return SessionInfo(
            id=session_id,
            name=str(data.get("name") or session_id),
            root_dir=str(root),
            session_dir=str(session_dir),
            db_path=str(session_dir / "transcript.db"),
            created_at=float(data.get("created_at") or path.stat().st_mtime),
            started_at=float(data["started_at"]) if data.get("started_at") is not None else None,
            stopped_at=float(data["stopped_at"]) if data.get("stopped_at") is not None else None,
            status=str(data.get("status") or "stopped"),
        )

    def _write_metadata(self) -> None:
        if self._current is None:
            return
        path = Path(self._current.session_dir) / "session.json"
        path.write_text(json.dumps(asdict(self._current), indent=2), encoding="utf-8")
