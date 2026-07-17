import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from evaluation.degradation_v1 import generate as degradation


def write_test_wav(path: Path, seconds: float = 0.2) -> None:
    sample_count = int(degradation.SAMPLE_RATE * seconds)
    t = np.arange(sample_count, dtype=np.float64) / degradation.SAMPLE_RATE
    audio = 0.32 * np.sin(2.0 * np.pi * 440.0 * t)
    sf.write(str(path), audio, degradation.SAMPLE_RATE, subtype="PCM_16")


def write_parent_manifest(root: Path, split: str = "development") -> Path:
    audio_path = root / "parent.wav"
    write_test_wav(audio_path)
    manifest = {
        "schema_version": 1,
        "dataset_id": "tiny_parent_v1",
        "split": split,
        "usage": split,
        "is_holdout": False,
        "clips": [
            {
                "audio_id": "clip-001",
                "data_path": str(audio_path),
                "sha256": degradation.sha256_file(audio_path),
                "reference_text": "Bühne frei?",
            }
        ],
    }
    manifest_path = root / "parent.json"
    manifest_path.write_bytes(degradation.canonical_json_bytes(manifest))
    return manifest_path


def test_parent_clip_hash_is_mandatory_and_bound(tmp_path: Path) -> None:
    manifest_path = write_parent_manifest(tmp_path)
    _, clips, seal = degradation.load_and_verify_parent(manifest_path)

    assert seal is None
    assert clips[0]["sha256"] == degradation.sha256_file(tmp_path / "parent.wav")

    with (tmp_path / "parent.wav").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(degradation.DegradationError, match="hash mismatch"):
        degradation.load_and_verify_parent(manifest_path)


def test_profiles_are_deterministic_and_preserve_length() -> None:
    t = np.arange(3200, dtype=np.float64) / degradation.SAMPLE_RATE
    audio = 0.4 * np.sin(2.0 * np.pi * 700.0 * t)
    for profile in degradation.PROFILES:
        seed = degradation.derived_seed(17, "a" * 64, profile["name"])
        first, first_meta = degradation.apply_profile(audio, profile, seed)
        second, second_meta = degradation.apply_profile(audio, profile, seed)
        assert len(first) == len(audio)
        assert np.array_equal(first, second)
        assert first_meta == second_meta
        assert np.all(np.isfinite(first))


@pytest.mark.parametrize(
    ("noise_kind", "snr_db"), [("white", 15.0), ("ambient", 12.0)]
)
def test_noise_has_reproducible_requested_snr(
    noise_kind: str, snr_db: float
) -> None:
    rng = np.random.Generator(np.random.PCG64(123))
    audio = rng.normal(0.0, 0.08, size=16_000)
    output, metadata = degradation.add_noise(audio, noise_kind, snr_db, seed=99)

    assert len(output) == len(audio)
    assert metadata["requested_snr_db"] == snr_db
    assert metadata["measured_snr_db"] == pytest.approx(snr_db, abs=1e-9)
    assert metadata["seed"] == 99


def test_telephone_roundtrip_is_8k_and_returns_to_16k_length() -> None:
    t = np.arange(8000, dtype=np.float64) / degradation.SAMPLE_RATE
    audio = np.sin(2 * np.pi * 1000 * t) + 0.5 * np.sin(2 * np.pi * 6000 * t)
    output, metadata = degradation.telephone_roundtrip(audio, 300, 3400, 129)

    assert len(output) == len(audio)
    assert metadata["downsample_rate_hz"] == 8000
    assert metadata["upsample_rate_hz"] == 16000
    spectrum = np.abs(np.fft.rfft(output))
    frequencies = np.fft.rfftfreq(len(output), 1 / degradation.SAMPLE_RATE)
    level_1k = spectrum[np.argmin(np.abs(frequencies - 1000))]
    level_6k = spectrum[np.argmin(np.abs(frequencies - 6000))]
    assert level_1k > level_6k * 20


def test_overdrive_is_bounded_and_low_gain_is_exact() -> None:
    audio = np.linspace(-0.8, 0.8, 10_001)
    clipped, clip_meta = degradation.cautious_clip(audio, 0.95, 0.995, 1.03, 9.0)
    low, low_meta = degradation.apply_profile(
        audio, {"kind": "gain", "gain_db": -18.0}, seed=0
    )

    assert np.max(np.abs(clipped)) <= 0.95
    assert clip_meta["clipped_samples"] > 0
    assert clip_meta["clipped_sample_fraction"] < 0.02
    assert degradation.rms(low) / degradation.rms(audio) == pytest.approx(
        10 ** (-18 / 20), rel=1e-12
    )
    assert low_meta["gain_db"] == -18.0


def test_build_preserves_split_parent_hash_and_original(
    tmp_path: Path, monkeypatch
) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    manifest_path = write_parent_manifest(parent_root, split="development")
    parent_audio = parent_root / "parent.wav"
    before_hash = degradation.sha256_file(parent_audio)
    before_manifest_hash = degradation.sha256_file(manifest_path)
    output_root = tmp_path / "outputs"
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", output_root)

    destination = degradation.build(manifest_path, seed=41)

    assert degradation.sha256_file(parent_audio) == before_hash
    assert degradation.sha256_file(manifest_path) == before_manifest_hash
    derived = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert derived["split"] == "development"
    assert derived["is_holdout"] is False
    assert derived["parent"]["manifest_sha256"] == before_manifest_hash
    assert len(derived["clips"]) == len(degradation.PROFILES)
    assert {item["parent_clip"]["sha256"] for item in derived["clips"]} == {
        before_hash
    }
    assert {item["profile"] for item in derived["clips"]} == {
        profile["name"] for profile in degradation.PROFILES
    }
    assert all(item["processing_provenance"] for item in derived["clips"])
    assert degradation.verify_derived(destination) == []

    snapshot = {
        path.relative_to(destination).as_posix(): (
            degradation.sha256_file(path),
            path.stat().st_mtime_ns,
        )
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert degradation.verify_derived(destination) == []
    assert snapshot == {
        path.relative_to(destination).as_posix(): (
            degradation.sha256_file(path),
            path.stat().st_mtime_ns,
        )
        for path in destination.rglob("*")
        if path.is_file()
    }
    with pytest.raises(degradation.DegradationError, match="Refusing to overwrite"):
        degradation.build(manifest_path, seed=41)


def test_output_audio_hashes_repeat_in_independent_roots(
    tmp_path: Path, monkeypatch
) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    manifest_path = write_parent_manifest(parent_root)
    first_root = tmp_path / "first"
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", first_root)
    first = degradation.build(manifest_path, seed=55)
    first_hashes = {
        path.relative_to(first).as_posix(): degradation.sha256_file(path)
        for path in first.rglob("*.wav")
    }

    second_root = tmp_path / "second"
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", second_root)
    second = degradation.build(manifest_path, seed=55)
    second_hashes = {
        path.relative_to(second).as_posix(): degradation.sha256_file(path)
        for path in second.rglob("*.wav")
    }
    assert first_hashes == second_hashes


def test_unsealed_holdout_parent_is_rejected(tmp_path: Path) -> None:
    manifest_path = write_parent_manifest(tmp_path, split="holdout")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["is_holdout"] = True
    manifest_path.write_bytes(degradation.canonical_json_bytes(manifest))

    with pytest.raises(degradation.DegradationError, match="seal missing"):
        degradation.load_and_verify_parent(manifest_path)


def test_official_test_split_is_explicitly_normalized_to_holdout() -> None:
    manifest = {
        "official_split": "test",
        "usage": "holdout",
        "is_holdout": True,
    }

    assert degradation.logical_split(manifest) == "holdout"


def test_sealed_holdout_is_preserved_and_derived_output_is_sealed(
    tmp_path: Path, monkeypatch
) -> None:
    parent_root = tmp_path / "sealed-parent"
    parent_root.mkdir()
    audio_path = parent_root / "clean.wav"
    write_test_wav(audio_path)
    manifest = {
        "schema_version": "2.0",
        "dataset_id": "sealed_holdout_v1",
        "split": "holdout",
        "is_holdout": True,
        "artifacts": [
            {
                "path": "clean.wav",
                "bytes": audio_path.stat().st_size,
                "sha256": degradation.sha256_file(audio_path),
            }
        ],
        "utterances": [
            {
                "id": "holdout-001",
                "text": "Versiegelte Referenz.",
                "paths": {"clean": "clean.wav"},
            }
        ],
    }
    manifest_path = parent_root / "manifest.json"
    manifest_path.write_bytes(degradation.canonical_json_bytes(manifest))
    sealed_files = [manifest_path, audio_path]
    seal = {
        "schema_version": 1,
        "sealed": True,
        "files": [
            {
                "path": path.relative_to(parent_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": degradation.sha256_file(path),
            }
            for path in sealed_files
        ],
    }
    (parent_root / "HOLDOUT_SEAL.json").write_bytes(
        degradation.canonical_json_bytes(seal)
    )
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", tmp_path / "outputs")

    with pytest.raises(degradation.DegradationError, match="requires"):
        degradation.build(manifest_path, seed=66)
    destination = degradation.build(
        manifest_path, seed=66, confirm_holdout_derivation=True
    )

    derived = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert derived["split"] == "holdout"
    assert derived["is_holdout"] is True
    assert derived["parent"]["seal"]["sha256"]
    assert (destination / "HOLDOUT_SEAL.json").is_file()
    assert degradation.verify_derived(destination) == []


def test_verify_detects_derived_artifact_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    manifest_path = write_parent_manifest(parent_root)
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", tmp_path / "outputs")
    destination = degradation.build(manifest_path, seed=61)
    artifact = next(destination.rglob("*.wav"))

    with artifact.open("ab") as handle:
        handle.write(b"tampered")

    errors = degradation.verify_derived(destination)
    assert any("size mismatch" in error or "hash mismatch" in error for error in errors)


def test_verify_rechecks_parent_clip_bytes(tmp_path: Path, monkeypatch) -> None:
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    manifest_path = write_parent_manifest(parent_root)
    monkeypatch.setattr(degradation, "OUTPUT_ROOT", tmp_path / "outputs")
    destination = degradation.build(manifest_path, seed=71)

    with (parent_root / "parent.wav").open("ab") as handle:
        handle.write(b"parent changed")

    assert any(
        "parent verification failed" in error
        for error in degradation.verify_derived(destination)
    )
