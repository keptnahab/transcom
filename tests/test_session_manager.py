from backend.session.manager import SessionManager


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
