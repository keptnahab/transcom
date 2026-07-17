from __future__ import annotations

import hashlib
import json
from pathlib import Path
import wave

import numpy as np
import pytest

from evaluation.benchmark_clip_suite import _validate_manifest
from evaluation.manual_review.review_core import load_profiles


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evaluation/safety_adversarial_v1"
SPEC = SUITE / "spec.json"
BUILD = SUITE / "build.py"
MANIFESTS = (
    ROOT / "evaluation/data/manifests/safety_adversarial_dev_clean_v1.json",
    ROOT / "evaluation/data/manifests/safety_adversarial_dev_intercom_v1.json",
)
PENDING = "synthetic_source_pending_manual_audio_review"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_has_frozen_unique_changed_action_coverage():
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    rows = data["utterances"]

    assert data["split"] == "dev"
    assert data["reference_status"] == PENDING
    assert len(rows) == 8
    assert len({row["id"] for row in rows}) == 8
    assert len({row["text"] for row in rows}) == 8
    assert len({row["voice"] for row in rows}) >= 3
    assert len({row["rate"] for row in rows}) >= 3
    assert {row["observed_action"] for row in rows} == {
        "fallen", "auslassen", "sterben", "lösen",
        "verbinden", "betreten", "freigeben", "starten",
    }
    assert all(row["observed_action"] != row["canonical_action"] for row in rows)


@pytest.mark.parametrize("manifest_path", MANIFESTS)
def test_pending_manifest_is_hash_bound_pcm16_dev_only_and_not_scoreable(manifest_path):
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["usage"] == data["split"] == data["official_split"] == "dev"
    assert data["is_holdout"] is False
    assert data["scoring_authorized"] is False
    assert data["manual_audio_review_required"] is True
    assert data["source"]["spec_sha256"] == sha256_file(SPEC)
    assert data["source"]["build_script_sha256"] == sha256_file(BUILD)
    assert len(data["clips"]) == 8

    for clip in data["clips"]:
        assert clip["expected_command_id"] is None
        assert clip["reference_status"] == PENDING
        assert "safety_negative_ood" in clip["categories"]
        assert "changed_action_verb" in clip["categories"]
        path = ROOT / clip["data_path"]
        assert path.is_relative_to(ROOT / "evaluation/generated/safety_adversarial_v1/dev")
        assert "holdout" not in path.parts
        assert sha256_file(path) == clip["sha256"]
        with wave.open(str(path), "rb") as audio:
            assert audio.getnchannels() == 1
            assert audio.getframerate() == 16_000
            assert audio.getsampwidth() == 2
            assert audio.getcomptype() == "NONE"
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        assert samples.size > 0
        assert np.any(samples)
        assert int(np.max(np.abs(samples.astype(np.int32)))) < 32767

    with pytest.raises(ValueError, match="forbids ASR scoring"):
        _validate_manifest(manifest_path, ROOT)


def test_suite_is_registered_for_hash_bound_manual_review():
    profiles = load_profiles(
        ROOT / "evaluation/manual_review/profiles_v1.json",
        ROOT,
    )
    clean = profiles["safety_adversarial_clean_dev_v1"]
    intercom = profiles["safety_adversarial_intercom_dev_v1"]
    assert clean.manifest_path == MANIFESTS[0]
    assert clean.mode == "manual"
    assert clean.reviewed_output_path is not None
    assert intercom.manifest_path == MANIFESTS[1]
    assert intercom.mode == "inherited"
    assert intercom.parent_profile_id == clean.profile_id
    assert intercom.transformation_manifest_path == MANIFESTS[1]
    assert intercom.reviewed_output_path is not None
