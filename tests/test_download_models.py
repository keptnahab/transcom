from pathlib import Path

import backend.config as cfg
from scripts import download_models


def _fake_cache(tmp_path: Path, calls: list[dict]):
    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        snapshot = tmp_path / kwargs["revision"]
        snapshot.mkdir(exist_ok=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
        return str(snapshot)

    return fake_snapshot_download


def test_required_model_matrix_contains_all_three_pinned_roles() -> None:
    snapshots = download_models.required_model_snapshots()

    assert [(item.repository, item.revision) for item in snapshots] == [
        (cfg.MLX_MODEL_REPOSITORY, cfg.MLX_MODEL_REVISION),
        (cfg.MLX_SHORT_MODEL_REPOSITORY, cfg.MLX_SHORT_MODEL_REVISION),
        (
            cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY,
            cfg.SAFETY_CONFIRMATION_MODEL_REVISION,
        ),
    ]
    assert len({item.repository for item in snapshots}) == 3
    assert all(len(item.revision) == 40 for item in snapshots)


def test_default_mode_downloads_each_exact_revision(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        download_models, "snapshot_download", _fake_cache(tmp_path, calls)
    )

    assert download_models.main([]) == 0
    assert calls == [
        {
            "repo_id": item.repository,
            "revision": item.revision,
            "local_files_only": False,
        }
        for item in download_models.required_model_snapshots()
    ]


def test_verify_only_is_strictly_local(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        download_models, "snapshot_download", _fake_cache(tmp_path, calls)
    )

    assert download_models.main(["--verify-only"]) == 0
    assert len(calls) == 3
    assert all(call["local_files_only"] is True for call in calls)


def test_full_commit_pin_and_resolved_revision_are_enforced(tmp_path: Path) -> None:
    invalid = download_models.ModelSnapshot("bad", "org/model", "main")
    try:
        download_models._validate_pin(invalid)
    except RuntimeError as exc:
        assert "not pinned" in str(exc)
    else:
        raise AssertionError("A mutable model revision must be rejected")

    pinned = download_models.required_model_snapshots()[0]
    wrong = tmp_path / "wrong-revision"
    wrong.mkdir()
    (wrong / "weights.safetensors").write_bytes(b"test")
    try:
        download_models._validate_local_snapshot(str(wrong), pinned)
    except RuntimeError as exc:
        assert "revision mismatch" in str(exc).lower()
    else:
        raise AssertionError("A mismatched local snapshot must be rejected")


def test_setup_and_setup_doc_cover_offline_hybrid_matrix() -> None:
    root = Path(__file__).resolve().parents[1]
    setup = (root / "scripts/setup.sh").read_text(encoding="utf-8")
    documentation = (root / "BASE/Handoff/08_SETUP.md").read_text(
        encoding="utf-8"
    )

    assert "HF_HUB_OFFLINE=1" in setup
    assert "scripts/download_models.py\" --verify-only" in setup
    for snapshot in download_models.required_model_snapshots():
        assert snapshot.repository in documentation
        assert snapshot.revision in documentation
    assert "0.15-s" in documentation
    assert "0.35 s" in documentation
    assert "12 CPU threads" in documentation
    assert "Safety Mode is disabled by default" in documentation
