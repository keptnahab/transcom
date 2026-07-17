from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.manual_review.review_core import (
    INHERITED_REFERENCE_STATUS,
    REVIEWED_REFERENCE_STATUS,
    ReviewError,
    ReviewProfile,
    append_decision,
    build_inherited_reviewed_manifest,
    build_reviewed_manifest,
    completion_summary,
    default_output_path,
    load_manifest,
    load_profiles,
    read_and_validate_log,
    sha256_file,
    write_reviewed_manifest,
)
from evaluation.manual_review.review_server import is_same_local_origin, session_payload


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _audio(root: Path, name: str, payload: bytes) -> tuple[str, str]:
    path = root / "audio" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path.relative_to(root)), hashlib.sha256(payload).hexdigest()


def _manual_fixture(tmp_path: Path, count: int = 2, scoring_authorized=None):
    clips = []
    for index in range(count):
        relative, audio_sha = _audio(tmp_path, f"source-{index}.wav", b"RIFF-source-" + bytes([index]))
        clips.append(
            {
                "audio_id": f"source-{index}",
                "data_path": relative,
                "reference_text": f"Geprüfte Testreferenz {index}.",
                "normalized_reference_text": f"geprüfte testreferenz {index}",
                "reference_status": "not_manually_reviewed",
                "sha256": audio_sha,
                "provenance": {"fixture": True, "index": index},
            }
        )
    manifest_path = tmp_path / "manifests" / "source_v1.json"
    manifest = {"schema_version": 1, "dataset_id": "fixture", "clips": clips}
    if scoring_authorized is not None:
        manifest["scoring_authorized"] = scoring_authorized
    _write_json(manifest_path, manifest)
    profile = ReviewProfile(
        profile_id="fixture_dev",
        label="Fixture Dev",
        group="human",
        split="dev",
        manifest_path=manifest_path,
        review_log_path=tmp_path / "logs" / "fixture_dev.jsonl",
    )
    return profile, load_manifest(profile)


def _time(second: int) -> datetime:
    return datetime(2026, 7, 13, 20, 0, second, tzinfo=timezone.utc)


def test_manual_review_is_append_only_has_no_implicit_pass_and_exports_only_when_currently_all_pass(tmp_path):
    profile, loaded = _manual_fixture(tmp_path)
    source_bytes = profile.manifest_path.read_bytes()

    with pytest.raises(ReviewError, match="not fully passed"):
        build_reviewed_manifest(loaded, tmp_path)

    first = append_decision(
        loaded,
        tmp_path,
        index=0,
        decision="PASS",
        note="Audio und Text stimmen überein.",
        reviewer_id="reviewer-01",
        now=lambda: _time(1),
    )
    failed = append_decision(
        loaded,
        tmp_path,
        index=1,
        decision="FAIL",
        note="Wortende fehlt.",
        reviewer_id="reviewer-01",
        now=lambda: _time(2),
    )
    assert failed["previous_event_sha256"] == first["event_sha256"]
    with pytest.raises(ReviewError, match="fail=1"):
        build_reviewed_manifest(loaded, tmp_path)

    corrected = append_decision(
        loaded,
        tmp_path,
        index=1,
        decision="PASS",
        note="Erneut vollständig angehört; Referenz stimmt.",
        reviewer_id="reviewer-02",
        now=lambda: _time(3),
    )
    log_bytes, events = read_and_validate_log(loaded)
    assert len(events) == 3
    assert corrected["previous_event_sha256"] == failed["event_sha256"]
    assert completion_summary(loaded, events) == {"total": 2, "pass": 2, "fail": 0, "pending": 0}

    reviewed, log_hash = build_reviewed_manifest(loaded, tmp_path)
    assert log_hash == hashlib.sha256(log_bytes).hexdigest()
    assert profile.manifest_path.read_bytes() == source_bytes
    for original, result in zip(loaded.clips, reviewed["clips"]):
        assert result["reference_status"] == REVIEWED_REFERENCE_STATUS
        assert result["review_log_hash"] == log_hash
        assert result["sha256"] == original["sha256"]
        assert result["reference_text"] == original["reference_text"]
        assert result["normalized_reference_text"] == original["normalized_reference_text"]
        assert result["provenance"] == original["provenance"]

    output = default_output_path(profile.manifest_path)
    first_output_hash = write_reviewed_manifest(output, reviewed, profile.manifest_path)
    assert first_output_hash == write_reviewed_manifest(output, reviewed, profile.manifest_path)
    assert output.name.endswith("_reviewed_v1.json")


def test_complete_manual_review_authorizes_explicitly_blocked_source_manifest(tmp_path):
    _, loaded = _manual_fixture(tmp_path, count=1, scoring_authorized=False)
    append_decision(
        loaded,
        tmp_path,
        index=0,
        decision="PASS",
        note="Vollständig angehört.",
        reviewer_id="reviewer-01",
        now=lambda: _time(1),
    )

    reviewed, log_hash = build_reviewed_manifest(loaded, tmp_path)

    assert loaded.data["scoring_authorized"] is False
    assert reviewed["scoring_authorized"] is True
    assert reviewed["scoring_authorization"] == {
        "basis": REVIEWED_REFERENCE_STATUS,
        "review_log_sha256": log_hash,
        "authorized_clip_count": 1,
    }


def test_fail_requires_note_and_reviewer_and_audio_bytes_are_verified(tmp_path):
    _, loaded = _manual_fixture(tmp_path, count=1)
    with pytest.raises(ReviewError, match="FAIL decision requires"):
        append_decision(
            loaded,
            tmp_path,
            index=0,
            decision="FAIL",
            note="",
            reviewer_id="reviewer",
        )
    with pytest.raises(ReviewError, match="Reviewer id"):
        append_decision(
            loaded,
            tmp_path,
            index=0,
            decision="PASS",
            note="",
            reviewer_id="reviewer with spaces",
        )
    audio_path = tmp_path / loaded.clips[0]["data_path"]
    audio_path.write_bytes(b"changed")
    with pytest.raises(ReviewError, match="Audio hash mismatch"):
        append_decision(
            loaded,
            tmp_path,
            index=0,
            decision="PASS",
            note="",
            reviewer_id="reviewer",
        )


def test_manifest_and_review_log_tampering_are_rejected(tmp_path):
    profile, loaded = _manual_fixture(tmp_path, count=1)
    append_decision(
        loaded,
        tmp_path,
        index=0,
        decision="PASS",
        note="",
        reviewer_id="reviewer",
        now=lambda: _time(1),
    )
    event = json.loads(profile.review_log_path.read_text(encoding="utf-8"))
    event["note"] = "nachträglich verändert"
    profile.review_log_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(ReviewError, match="hash is invalid"):
        read_and_validate_log(loaded)

    # Restore a fresh fixture, then prove the manifest hash binding is also enforced.
    other_profile, other_loaded = _manual_fixture(tmp_path / "other", count=1)
    append_decision(
        other_loaded,
        tmp_path / "other",
        index=0,
        decision="PASS",
        note="",
        reviewer_id="reviewer",
        now=lambda: _time(1),
    )
    manifest = json.loads(other_profile.manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_id"] = "changed"
    _write_json(other_profile.manifest_path, manifest)
    changed = load_manifest(other_profile)
    with pytest.raises(ReviewError, match="different manifest"):
        read_and_validate_log(changed)


def test_inherited_review_requires_reproducible_parent_pass_and_binds_transform_and_seal(tmp_path):
    parent_profile, parent_loaded = _manual_fixture(tmp_path, count=1)
    append_decision(
        parent_loaded,
        tmp_path,
        index=0,
        decision="PASS",
        note="bewusst angehört",
        reviewer_id="reviewer",
        now=lambda: _time(1),
    )
    parent_reviewed, parent_log_hash = build_reviewed_manifest(parent_loaded, tmp_path)
    write_reviewed_manifest(default_output_path(parent_profile.manifest_path), parent_reviewed, parent_profile.manifest_path)

    transform_path = tmp_path / "transforms" / "transform.json"
    _write_json(transform_path, {"tool": "fixture-transform", "configuration_sha256": "a" * 64})
    transform_hash = sha256_file(transform_path)
    seal_path = tmp_path / "transforms" / "HOLDOUT_SEAL.json"
    _write_json(
        seal_path,
        {
            "sealed": True,
            "files": [
                {
                    "path": transform_path.name,
                    "bytes": transform_path.stat().st_size,
                    "sha256": transform_hash,
                }
            ],
        },
    )
    derived_relative, derived_sha = _audio(tmp_path, "derived.wav", b"RIFF-derived")
    parent_clip = parent_loaded.clips[0]
    derived_manifest_path = tmp_path / "manifests" / "derived_v1.json"
    _write_json(
        derived_manifest_path,
        {
            "schema_version": 1,
            "scoring_authorized": False,
            "source_manifest": str(transform_path.relative_to(tmp_path)),
            "source_manifest_sha256": transform_hash,
            "clips": [
                {
                    "derived_clip_id": "source-0--noise",
                    "data_path": derived_relative,
                    "sha256": derived_sha,
                    "reference": {
                        "reference_text": parent_clip["reference_text"],
                        "normalized_reference_text": parent_clip["normalized_reference_text"],
                        "reference_status": "parent_not_manually_reviewed",
                    },
                    "parent_clip": {"id": "source-0", "sha256": parent_clip["sha256"]},
                    "processing_provenance": {"generator_sha256": "b" * 64},
                }
            ],
        },
    )
    derived_profile = ReviewProfile(
        profile_id="derived_dev",
        label="Derived Dev",
        group="degraded",
        split="dev",
        manifest_path=derived_manifest_path,
        review_log_path=tmp_path / "logs" / "unused.jsonl",
        mode="inherited",
        parent_profile_id=parent_profile.profile_id,
        transformation_manifest_path=transform_path,
        seal_path=seal_path,
    )
    derived_loaded = load_manifest(derived_profile)

    inherited, inherited_log_hash = build_inherited_reviewed_manifest(
        derived_loaded,
        parent_loaded,
        parent_reviewed,
        tmp_path,
    )
    result = inherited["clips"][0]
    evidence = result["manual_review_inheritance"]
    assert inherited_log_hash == parent_log_hash
    assert result["reference"]["reference_status"] == INHERITED_REFERENCE_STATUS
    assert result["review_log_hash"] == parent_log_hash
    assert result["reference"]["reference_text"] == parent_clip["reference_text"]
    assert result["sha256"] == derived_sha
    assert result["processing_provenance"] == {"generator_sha256": "b" * 64}
    assert evidence["parent_audio_sha256"] == parent_clip["sha256"]
    assert evidence["parent_review_log_sha256"] == parent_log_hash
    assert evidence["transformation_manifest_sha256"] == transform_hash
    assert evidence["seal_sha256"] == sha256_file(seal_path)
    assert inherited["scoring_authorized"] is True
    assert inherited["scoring_authorization"] == {
        "basis": INHERITED_REFERENCE_STATUS,
        "parent_review_log_sha256": parent_log_hash,
        "transformation_manifest_sha256": transform_hash,
        "authorized_clip_count": 1,
    }

    stale_parent = json.loads(json.dumps(parent_reviewed))
    stale_parent["clips"][0]["review_log_hash"] = "0" * 64
    with pytest.raises(ReviewError, match="not reproducible"):
        build_inherited_reviewed_manifest(
            derived_loaded,
            parent_loaded,
            stale_parent,
            tmp_path,
        )


def test_inheritance_rejects_changed_reference_parent_hash_or_unbound_seal(tmp_path):
    parent_profile, parent_loaded = _manual_fixture(tmp_path, count=1)
    append_decision(
        parent_loaded,
        tmp_path,
        index=0,
        decision="PASS",
        note="",
        reviewer_id="reviewer",
        now=lambda: _time(1),
    )
    parent_reviewed, _ = build_reviewed_manifest(parent_loaded, tmp_path)
    transform_path = tmp_path / "transform-root" / "transform.json"
    _write_json(transform_path, {"transform": True})
    transform_hash = sha256_file(transform_path)
    seal_path = transform_path.parent / "seal.json"
    _write_json(
        seal_path,
        {
            "sealed": True,
            "files": [
                {
                    "path": transform_path.name,
                    "bytes": transform_path.stat().st_size,
                    "sha256": "0" * 64,
                }
            ],
        },
    )
    relative, derived_sha = _audio(tmp_path, "bad-derived.wav", b"bad-derived")
    derived_path = tmp_path / "derived.json"
    _write_json(
        derived_path,
        {
            "source_manifest": str(transform_path.relative_to(tmp_path)),
            "source_manifest_sha256": transform_hash,
            "clips": [
                {
                    "id": "source-0",
                    "data_path": relative,
                    "sha256": derived_sha,
                    "reference_text": "Andere Referenz.",
                    "reference_status": "unreviewed",
                }
            ],
        },
    )
    derived_profile = ReviewProfile(
        profile_id="derived_dev",
        label="Derived",
        group="synthetic_intercom",
        split="dev",
        manifest_path=derived_path,
        review_log_path=tmp_path / "unused.jsonl",
        mode="inherited",
        parent_profile_id=parent_profile.profile_id,
        transformation_manifest_path=transform_path,
        seal_path=seal_path,
    )
    with pytest.raises(ReviewError, match="file changed"):
        build_inherited_reviewed_manifest(
            load_manifest(derived_profile),
            parent_loaded,
            parent_reviewed,
            tmp_path,
        )
    _write_json(
        seal_path,
        {
            "sealed": True,
            "files": [
                {
                    "path": transform_path.name,
                    "bytes": transform_path.stat().st_size,
                    "sha256": transform_hash,
                }
            ],
        },
    )
    with pytest.raises(ReviewError, match="changed the parent reference"):
        build_inherited_reviewed_manifest(
            load_manifest(derived_profile),
            parent_loaded,
            parent_reviewed,
            tmp_path,
        )


def test_shipped_profiles_separate_manual_sources_from_derived_inheritance_and_ui_has_no_default(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    profiles = load_profiles(
        project_root / "evaluation" / "manual_review" / "profiles_v1.json",
        project_root,
    )
    assert {profile.profile_id for profile in profiles.values() if profile.mode == "manual"} == {
        "synthetic_clean_dev_v9",
        "synthetic_clean_holdout_v9",
        "human_dev_v1",
        "human_holdout_v2",
        "safety_adversarial_clean_dev_v1",
    }
    assert {profile.profile_id for profile in profiles.values() if profile.mode == "inherited"} == {
        "synthetic_intercom_dev_v9",
        "synthetic_intercom_holdout_v9",
        "degraded_dev_v1",
        "degraded_holdout_v2",
        "safety_adversarial_intercom_dev_v1",
    }
    for profile in profiles.values():
        assert profile.split in {"dev", "holdout"}
        assert profile.manifest_path.is_file()
        assert profile.reviewed_output_path
        assert profile.reviewed_output_path.name.endswith("_reviewed_v1.json")
        assert "reviewed_manifests" in profile.reviewed_output_path.parts
        if profile.mode == "inherited":
            assert profile.parent_profile_id
            assert profile.transformation_manifest_path
            assert profile.transformation_manifest_path.is_file()
            if profile.split == "holdout":
                assert profile.seal_path and profile.seal_path.is_file()
                assert not profile.reviewed_output_path.is_relative_to(profile.seal_path.parent)

    html = (project_root / "evaluation" / "manual_review" / "static" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="pass-button"' in html and 'id="fail-button"' in html
    assert 'id="pass-button" class="button pass-button" disabled' in html
    assert 'id="fail-button" class="button fail-button" disabled' in html
    assert "checked" not in html.lower()


def test_local_ui_session_starts_pending_and_decisions_require_same_origin(tmp_path):
    _, loaded = _manual_fixture(tmp_path, count=1)
    session = session_payload(loaded)
    assert session["summary"] == {"total": 1, "pass": 0, "fail": 0, "pending": 1}
    assert session["items"][0]["decision"] is None
    assert is_same_local_origin("127.0.0.1:8765", "http://127.0.0.1:8765")
    assert not is_same_local_origin("127.0.0.1:8765", "http://malicious.invalid")
    assert not is_same_local_origin("127.0.0.1:8765", None)
