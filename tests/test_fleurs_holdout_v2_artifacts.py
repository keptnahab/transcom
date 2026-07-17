from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import tarfile

import soundfile as sf

from evaluation.degradation_v1 import generate as degradation
from evaluation.import_fleurs import (
    load_metadata_with_repairs,
    sha256_bytes,
    sha256_file,
    verify_holdout_seal,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "evaluation/data/manifests"
RAW = ROOT / "evaluation/data/raw/human"
HUMAN_MANIFEST = MANIFESTS / "fleurs_de_test_holdout_v2.json"
HUMAN_SEAL = MANIFESTS / "fleurs_de_test_holdout_v2.seal.json"
HUMAN_AUDIO = RAW / "fleurs_de_test_holdout_v2"
DEGRADED = (
    ROOT
    / "evaluation/generated/degraded_v1/fleurs_de_test_holdout_v2-degraded-v1-3d62a12152ef"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_human_holdout_v2_seal_source_reference_and_license_bindings() -> None:
    manifest = _json(HUMAN_MANIFEST)
    seal = verify_holdout_seal(HUMAN_MANIFEST, HUMAN_AUDIO, HUMAN_SEAL)
    assert manifest["dataset_id"] == "fleurs_de_test_holdout_v2"
    assert manifest["official_split"] == "test"
    assert manifest["usage"] == "holdout"
    assert manifest["is_holdout"] is True
    assert len(manifest["clips"]) == seal["clip_count"] == 12
    assert manifest["selection"]["asr_outputs_used_for_selection"] is False
    assert manifest["selection"]["length_buckets"] == {
        "short": 4,
        "medium": 4,
        "long": 4,
    }
    assert manifest["reference_validation"] == {
        "metadata_rows_parsed": 862,
        "selected_rows_exactly_bound_to_tsv": True,
        "all_reference_fields_nonempty": True,
        "all_audio_frame_counts_match_tsv": True,
        "manual_audio_transcript_review": False,
    }

    archive_path = Path("/private/tmp/fleurs_de_test.tar.gz")
    metadata_path = Path("/private/tmp/fleurs_de_test.tsv")
    assert sha256_file(archive_path) == manifest["source"]["archive_sha256"]
    assert sha256_file(metadata_path) == manifest["source"]["metadata_sha256"]
    rows, repairs = load_metadata_with_repairs(metadata_path)
    by_filename = {row.audio_filename: row for row in rows}
    assert repairs == manifest["source"]["metadata_repairs"]

    with tarfile.open(archive_path, mode="r:gz") as archive:
        for clip in manifest["clips"]:
            row = by_filename[clip["fleurs_audio_filename"]]
            assert clip["fleurs_sentence_id"] == row.sentence_id
            assert clip["reference_text"] == row.raw_transcription
            assert clip["normalized_reference_text"] == row.normalized_transcription
            assert clip["word_count"] == row.word_count
            extracted = archive.extractfile(clip["archive_member"])
            assert extracted is not None
            original = extracted.read()
            copied = (ROOT / clip["data_path"]).read_bytes()
            assert copied == original
            assert sha256_bytes(original) == clip["sha256"]
            info = sf.info(ROOT / clip["data_path"])
            assert info.channels == 1 and info.samplerate == 16_000
            assert info.frames == row.sample_count

    license_record = manifest["license"]
    assert license_record["spdx_id"] == "CC-BY-4.0"
    attribution = ROOT / license_record["attribution_file"]
    text = attribution.read_text(encoding="utf-8")
    assert "fleurs_de_test_holdout_v2" in text
    assert "Creative Commons Attribution 4.0" in text


def test_human_holdout_v2_is_disjoint_from_dev_and_burned_holdout_v1() -> None:
    candidate = _json(HUMAN_MANIFEST)
    prior = [
        _json(MANIFESTS / "fleurs_de_dev_v1.json"),
        _json(MANIFESTS / "fleurs_de_test_holdout_v1.json"),
    ]
    for field in (
        "audio_id",
        "fleurs_audio_filename",
        "fleurs_sentence_id",
        "sha256",
    ):
        candidate_values = {str(clip[field]) for clip in candidate["clips"]}
        prior_values = {
            str(clip[field]) for manifest in prior for clip in manifest["clips"]
        }
        assert len(candidate_values) == 12
        assert candidate_values.isdisjoint(prior_values)

    expected_exclusions = {
        "fleurs_de_dev_v1": "dadfac0ee4be3470eb817e1841a3779a900a94561390cf07a3cd613e469b9052",
        "fleurs_de_test_holdout_v1": "c0ad5717ba6a2c5e6e9ef223c8f83bae21063cb84bce065da2e327d38a5c64db",
    }
    observed = {
        item["dataset_id"]: item["sha256"]
        for item in candidate["selection"]["excluded_manifests"]
    }
    assert observed == expected_exclusions


def test_degraded_counterpart_is_parent_bound_hash_verified_and_sealed() -> None:
    assert degradation.verify_derived(DEGRADED, verify_parent=True) == []
    derived = _json(DEGRADED / "manifest.json")
    parent = _json(HUMAN_MANIFEST)
    assert derived["parent"]["dataset_id"] == parent["dataset_id"]
    assert derived["parent"]["manifest_sha256"] == sha256_file(HUMAN_MANIFEST)
    assert derived["parent"]["seal"]["sha256"] == sha256_file(HUMAN_SEAL)
    assert derived["is_holdout"] is True
    assert derived["split"] == "holdout"
    assert len(derived["clips"]) == 60
    assert {clip["profile"] for clip in derived["clips"]} == {
        "broadband_noise",
        "ambient_noise",
        "telephone_8k_roundtrip",
        "soft_overdrive",
        "low_gain",
    }
    parent_hashes = {clip["sha256"] for clip in parent["clips"]}
    derived_hashes = {clip["sha256"] for clip in derived["clips"]}
    assert len(derived_hashes) == 60
    assert derived_hashes.isdisjoint(parent_hashes)
    prior = [
        _json(MANIFESTS / "fleurs_de_dev_v1.json"),
        _json(MANIFESTS / "fleurs_de_test_holdout_v1.json"),
    ]
    prior_hashes = {
        clip["sha256"] for manifest in prior for clip in manifest["clips"]
    }
    prior_ids = {
        str(clip["audio_id"]) for manifest in prior for clip in manifest["clips"]
    }
    assert derived_hashes.isdisjoint(prior_hashes)
    assert len({clip["derived_clip_id"] for clip in derived["clips"]}) == 60
    assert {
        str(clip["parent_clip"]["id"]) for clip in derived["clips"]
    }.isdisjoint(prior_ids)
    seal = _json(DEGRADED / "HOLDOUT_SEAL.json")
    assert seal["sealed"] is True
    assert len(seal["files"]) == 61
