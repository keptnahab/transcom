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

    def _require_current(self) -> SessionInfo:
        if self._current is None:
            return self.create()
        return self._current

    def _write_metadata(self) -> None:
        if self._current is None:
            return
        path = Path(self._current.session_dir) / "session.json"
        path.write_text(json.dumps(asdict(self._current), indent=2), encoding="utf-8")
