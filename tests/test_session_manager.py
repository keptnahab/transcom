from backend.session.manager import SessionManager
import pytest


def test_session_create_writes_folder_and_metadata(tmp_path):
    manager = SessionManager(default_root=str(tmp_path))
    info = manager.create(name="Show A")
    assert info.name == "Show A"
    assert (tmp_path / info.id / "session.json").exists()
    assert (tmp_path / info.id / "exports").exists()
    assert (tmp_path / info.id / "profiles").exists()


def test_session_start_stop(tmp_path):
    manager = SessionManager(default_root=str(tmp_path))
    manager.create()
    started = manager.start()
    assert started.status == "live"
    stopped = manager.stop()
    assert stopped.status == "stopped"
    assert stopped.stopped_at is not None


def test_session_list_and_open(tmp_path):
    manager = SessionManager(default_root=str(tmp_path))
    first = manager.create(name="Erstes Transkript")
    second = manager.create(name="Zweites Transkript")

    sessions = manager.list_sessions()
    assert [item["id"] for item in sessions] == [second.id, first.id]
    assert sessions[0]["name"] == "Zweites Transkript"

    opened = manager.open(first.id)
    assert opened.id == first.id
    assert opened.name == "Erstes Transkript"
    assert opened.status == "stopped"
    assert manager.current == opened


def test_session_open_rejects_path_traversal(tmp_path):
    manager = SessionManager(default_root=str(tmp_path))
    with pytest.raises(ValueError):
        manager.open("../outside")
