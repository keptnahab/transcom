#!/usr/bin/env python3
"""Derive deterministic degraded clips from a hash-bound parent manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf


HERE = Path(__file__).resolve().parent
EVALUATION_ROOT = HERE.parent
APP_ROOT = EVALUATION_ROOT.parent
OUTPUT_ROOT = EVALUATION_ROOT / "generated" / "degraded_v1"
SAMPLE_RATE = 16_000
BASE_SEED = 2_026_071_301
SCHEMA_VERSION = 1
SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")

PROFILES: Tuple[Dict[str, Any], ...] = (
    {"name": "broadband_noise", "kind": "noise", "noise": "white", "snr_db": 15.0},
    {"name": "ambient_noise", "kind": "noise", "noise": "ambient", "snr_db": 12.0},
    {
        "name": "telephone_8k_roundtrip",
        "kind": "telephone",
        "bandpass_low_hz": 300,
        "bandpass_high_hz": 3400,
        "roundtrip_rate_hz": 8000,
        "output_rate_hz": SAMPLE_RATE,
        "fir_taps": 129,
    },
    {
        "name": "soft_overdrive",
        "kind": "clip",
        "clip_limit": 0.95,
        "target_quantile": 0.995,
        "target_over_limit": 1.03,
        "max_gain_db": 9.0,
        "max_clipped_fraction": 0.01,
    },
    {"name": "low_gain", "kind": "gain", "gain_db": -18.0},
)


class DegradationError(RuntimeError):
    """Raised when input provenance or an output safety invariant fails."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def safe_id(value: str) -> str:
    result = SAFE_ID_RE.sub("-", value).strip(".-_")
    if not result:
        raise DegradationError(f"Value cannot form a safe id: {value!r}")
    return result[:120]


def degradation_config(seed: int = BASE_SEED) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "seed": int(seed),
        "sample_rate_hz": SAMPLE_RATE,
        "profiles": [dict(profile) for profile in PROFILES],
        "pcm_output": "signed 16-bit little-endian WAV",
    }


def config_hash(seed: int = BASE_SEED) -> str:
    return hashlib.sha256(canonical_json_bytes(degradation_config(seed))).hexdigest()


def resolve_manifest_path(value: str, manifest_path: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.parts and candidate.parts[0] == "evaluation":
        return (APP_ROOT / candidate).resolve()
    return (manifest_path.parent / candidate).resolve()


def logical_split(manifest: Mapping[str, Any]) -> str:
    if is_holdout(manifest):
        return "holdout"
    value = manifest.get("split")
    if value is None:
        value = manifest.get("official_split")
    if value is None:
        value = manifest.get("usage")
    if value is None:
        raise DegradationError("Parent manifest has no split/official_split/usage")
    return str(value)


def is_holdout(manifest: Mapping[str, Any]) -> bool:
    if "is_holdout" in manifest:
        return bool(manifest["is_holdout"])
    return str(manifest.get("usage", manifest.get("split", ""))).casefold() in {
        "holdout",
        "test",
    }


def _artifact_hash_map(manifest: Mapping[str, Any]) -> Dict[str, str]:
    return {
        str(item["path"]): str(item["sha256"])
        for item in manifest.get("artifacts", [])
        if "path" in item and "sha256" in item
    }


def select_parent_clips(
    manifest: Mapping[str, Any], manifest_path: Path, variant: str = "clean"
) -> List[Dict[str, Any]]:
    clips: List[Dict[str, Any]] = []
    artifact_hashes = _artifact_hash_map(manifest)
    if manifest.get("clips"):
        for index, item in enumerate(manifest["clips"], start=1):
            path_value = item.get("data_path") or item.get("audio_file") or item.get("path")
            expected_hash = item.get("sha256") or item.get("audio_sha256")
            if not path_value or not expected_hash:
                raise DegradationError(f"Parent clip {index} lacks path or SHA-256")
            clip_id = item.get("audio_id") or item.get("id") or Path(path_value).stem
            clips.append(
                {
                    "id": str(clip_id),
                    "path": resolve_manifest_path(str(path_value), manifest_path),
                    "manifest_path": str(path_value),
                    "sha256": str(expected_hash),
                    "reference": {
                        key: item[key]
                        for key in (
                            "reference_text",
                            "normalized_reference_text",
                            "reference_status",
                        )
                        if key in item
                    },
                }
            )
    elif manifest.get("utterances"):
        for index, item in enumerate(manifest["utterances"], start=1):
            paths = item.get("paths", {})
            path_value = paths.get(variant)
            if not path_value:
                raise DegradationError(
                    f"Parent utterance {item.get('id', index)} lacks variant {variant!r}"
                )
            expected_hash = artifact_hashes.get(str(path_value))
            if not expected_hash:
                raise DegradationError(
                    f"Parent artifact hash missing for {path_value}"
                )
            clips.append(
                {
                    "id": str(item.get("id", index)),
                    "path": resolve_manifest_path(str(path_value), manifest_path),
                    "manifest_path": str(path_value),
                    "sha256": expected_hash,
                    "reference": {
                        "reference_text": item["text"]
                    }
                    if "text" in item
                    else {},
                }
            )
    elif manifest.get("audio_file"):
        path_value = str(manifest["audio_file"])
        expected_hash = manifest.get("audio_sha256")
        if not expected_hash:
            raise DegradationError("Single-audio parent lacks audio_sha256")
        clips.append(
            {
                "id": str(manifest.get("audio_id", Path(path_value).stem)),
                "path": resolve_manifest_path(path_value, manifest_path),
                "manifest_path": path_value,
                "sha256": str(expected_hash),
                "reference": {},
            }
        )
    else:
        raise DegradationError("Unsupported parent manifest: no clips, utterances, or audio_file")

    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for clip in clips:
        if clip["id"] in seen_ids or clip["path"] in seen_paths:
            raise DegradationError(f"Duplicate parent clip: {clip['id']}")
        if not re.fullmatch(r"[0-9a-f]{64}", clip["sha256"]):
            raise DegradationError(f"Invalid parent SHA-256 for {clip['id']}")
        if not clip["path"].is_file():
            raise DegradationError(f"Parent clip does not exist: {clip['path']}")
        actual_hash = sha256_file(clip["path"])
        if actual_hash != clip["sha256"]:
            raise DegradationError(
                f"Parent clip hash mismatch for {clip['id']}: {actual_hash}"
            )
        seen_ids.add(clip["id"])
        seen_paths.add(clip["path"])
    return clips


def _verify_fleurs_style_seal(
    manifest: Mapping[str, Any], manifest_path: Path, clips: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    seal_info = manifest.get("holdout_seal")
    if not isinstance(seal_info, Mapping) or not seal_info.get("required"):
        raise DegradationError("Holdout parent does not require a seal")
    seal_path = resolve_manifest_path(str(seal_info.get("path", "")), manifest_path)
    if not seal_path.is_file():
        raise DegradationError(f"Holdout seal missing: {seal_path}")
    with seal_path.open("r", encoding="utf-8") as handle:
        seal = json.load(handle)
    manifest_hash = sha256_file(manifest_path)
    if seal.get("manifest_sha256") != manifest_hash:
        raise DegradationError("Holdout seal does not bind the current parent manifest")
    sealed_by_name = {
        str(item["filename"]): str(item["sha256"])
        for item in seal.get("clips", [])
    }
    for clip in clips:
        if sealed_by_name.get(clip["path"].name) != clip["sha256"]:
            raise DegradationError(f"Holdout seal misses parent clip {clip['id']}")
    return {"path": str(seal_path), "sha256": sha256_file(seal_path)}


def _verify_tree_style_seal(manifest_path: Path) -> Dict[str, Any]:
    seal_path = manifest_path.parent / "HOLDOUT_SEAL.json"
    if not seal_path.is_file():
        raise DegradationError(f"Holdout seal missing: {seal_path}")
    with seal_path.open("r", encoding="utf-8") as handle:
        seal = json.load(handle)
    expected_paths: set[str] = set()
    for record in seal.get("files", []):
        expected_paths.add(str(record.get("path", "")))
        path = (manifest_path.parent / record.get("path", "")).resolve()
        if not is_relative_to(path, manifest_path.parent.resolve()) or not path.is_file():
            raise DegradationError(f"Sealed parent file missing: {record.get('path')}")
        if path.stat().st_size != record.get("bytes") or sha256_file(path) != record.get(
            "sha256"
        ):
            raise DegradationError(f"Sealed parent file changed: {record.get('path')}")
    actual_paths = {
        path.relative_to(manifest_path.parent).as_posix()
        for path in manifest_path.parent.rglob("*")
        if path.is_file() and path.name != "HOLDOUT_SEAL.json"
    }
    unsealed = actual_paths - expected_paths
    if unsealed:
        raise DegradationError(
            f"Files were added to sealed parent: {sorted(unsealed)}"
        )
    return {"path": str(seal_path), "sha256": sha256_file(seal_path)}


def load_and_verify_parent(
    manifest_path: Path, variant: str = "clean"
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise DegradationError(f"Parent manifest does not exist: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not manifest.get("dataset_id"):
        raise DegradationError("Parent manifest lacks dataset_id")
    clips = select_parent_clips(manifest, manifest_path, variant=variant)
    seal: Optional[Dict[str, Any]] = None
    if is_holdout(manifest):
        if manifest.get("holdout_seal"):
            seal = _verify_fleurs_style_seal(manifest, manifest_path, clips)
        else:
            seal = _verify_tree_style_seal(manifest_path)
    return manifest, clips, seal


def derived_dataset_id(parent_dataset_id: str, seed: int = BASE_SEED) -> str:
    return safe_id(f"{parent_dataset_id}-degraded-v1-{config_hash(seed)[:12]}")


def safe_destination(dataset_id: str) -> Path:
    destination = (OUTPUT_ROOT / safe_id(dataset_id)).resolve()
    if not is_relative_to(destination, OUTPUT_ROOT.resolve()):
        raise DegradationError("Derived output escaped evaluation/generated/degraded_v1")
    if destination.exists():
        raise DegradationError(f"Refusing to overwrite derived dataset: {destination}")
    return destination


def read_audio(path: Path) -> np.ndarray:
    audio, sample_rate = sf.read(str(path), dtype="float64", always_2d=False)
    if sample_rate != SAMPLE_RATE:
        raise DegradationError(f"Expected 16 kHz parent audio, got {sample_rate}: {path}")
    if audio.ndim != 1:
        raise DegradationError(f"Expected mono parent audio: {path}")
    if not len(audio) or not np.all(np.isfinite(audio)):
        raise DegradationError(f"Invalid samples in parent audio: {path}")
    return np.clip(audio, -1.0, 1.0)


def write_audio(path: Path, audio: np.ndarray) -> None:
    if audio.ndim != 1 or not np.all(np.isfinite(audio)):
        raise DegradationError(f"Invalid derived audio for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(
        str(path),
        np.clip(audio, -0.999969, 0.999969),
        SAMPLE_RATE,
        format="WAV",
        subtype="PCM_16",
    )


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def active_rms(audio: np.ndarray) -> float:
    frame = SAMPLE_RATE // 50
    usable = len(audio) // frame * frame
    if not usable:
        value = rms(audio)
        if value <= 0:
            raise DegradationError("Cannot degrade silent audio")
        return value
    framed = audio[:usable].reshape(-1, frame)
    levels = np.sqrt(np.mean(np.square(framed), axis=1))
    active = framed[levels >= 10 ** (-45.0 / 20.0)]
    value = rms(active.reshape(-1)) if len(active) else rms(audio)
    if value <= 0:
        raise DegradationError("Cannot degrade silent audio")
    return value


def derived_seed(base_seed: int, clip_hash: str, profile_name: str) -> int:
    payload = f"{base_seed}:{clip_hash}:{profile_name}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _ambient_noise(length: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(length)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(length, d=1.0 / SAMPLE_RATE)
    shaping = 1.0 / np.sqrt(np.maximum(frequencies, 35.0))
    shaping[frequencies > 5500.0] *= 0.25
    shaping[0] = 0.0
    colored = np.fft.irfft(spectrum * shaping, n=length)
    t = np.arange(length, dtype=np.float64) / SAMPLE_RATE
    phases = rng.uniform(0.0, 2.0 * np.pi, size=3)
    hum = (
        np.sin(2.0 * np.pi * 50.0 * t + phases[0])
        + 0.35 * np.sin(2.0 * np.pi * 100.0 * t + phases[1])
        + 0.12 * np.sin(2.0 * np.pi * 250.0 * t + phases[2])
    )
    return colored + 0.18 * hum


def add_noise(
    audio: np.ndarray, noise_kind: str, snr_db: float, seed: int
) -> Tuple[np.ndarray, Dict[str, Any]]:
    rng = np.random.Generator(np.random.PCG64(seed))
    if noise_kind == "white":
        noise = rng.standard_normal(len(audio))
    elif noise_kind == "ambient":
        noise = _ambient_noise(len(audio), rng)
    else:
        raise DegradationError(f"Unsupported noise kind: {noise_kind}")
    noise -= np.mean(noise)
    raw_noise_rms = rms(noise)
    speech_rms = active_rms(audio)
    target_noise_rms = speech_rms / (10 ** (snr_db / 20.0))
    noise *= target_noise_rms / raw_noise_rms
    mixed = audio + noise
    common_gain = min(1.0, 0.98 / max(float(np.max(np.abs(mixed))), 1e-12))
    output = mixed * common_gain
    measured_snr = 20.0 * math.log10(
        (speech_rms * common_gain) / (rms(noise * common_gain) + 1e-15)
    )
    return output, {
        "noise_kind": noise_kind,
        "seed": seed,
        "rng": "numpy.random.PCG64",
        "requested_snr_db": snr_db,
        "measured_snr_db": measured_snr,
        "snr_reference": "RMS of 20 ms frames above -45 dBFS",
        "active_speech_rms": speech_rms,
        "noise_rms": rms(noise),
        "common_anti_clip_gain": common_gain,
    }


def _lowpass_kernel(cutoff_hz: float, taps: int) -> np.ndarray:
    if taps % 2 != 1:
        raise DegradationError("FIR tap count must be odd")
    center = (taps - 1) / 2.0
    n = np.arange(taps, dtype=np.float64) - center
    normalized = cutoff_hz / SAMPLE_RATE
    kernel = 2.0 * normalized * np.sinc(2.0 * normalized * n)
    kernel *= np.hamming(taps)
    kernel /= np.sum(kernel)
    return kernel


def telephone_roundtrip(
    audio: np.ndarray, low_hz: int, high_hz: int, taps: int
) -> Tuple[np.ndarray, Dict[str, Any]]:
    bandpass = _lowpass_kernel(high_hz, taps) - _lowpass_kernel(low_hz, taps)
    filtered = np.convolve(audio, bandpass, mode="same")
    at_8k = filtered[::2]
    positions_8k = np.arange(len(at_8k), dtype=np.float64) * 2.0
    positions_16k = np.arange(len(audio), dtype=np.float64)
    restored = np.interp(positions_16k, positions_8k, at_8k)
    anti_clip_gain = min(1.0, 0.98 / max(float(np.max(np.abs(restored))), 1e-12))
    return restored * anti_clip_gain, {
        "bandpass_low_hz": low_hz,
        "bandpass_high_hz": high_hz,
        "fir_taps": taps,
        "downsample_rate_hz": 8000,
        "upsample_rate_hz": SAMPLE_RATE,
        "downsample_method": "FIR anti-alias then decimate by 2",
        "upsample_method": "deterministic linear interpolation",
        "anti_clip_gain": anti_clip_gain,
    }


def cautious_clip(
    audio: np.ndarray,
    clip_limit: float,
    target_quantile: float,
    target_over_limit: float,
    max_gain_db: float,
    max_clipped_fraction: float = 0.01,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    quantile = float(np.quantile(np.abs(audio), target_quantile))
    if quantile <= 0:
        raise DegradationError("Cannot overdrive silent audio")
    max_gain = 10 ** (max_gain_db / 20.0)
    gain = min(max_gain, clip_limit * target_over_limit / quantile)
    driven = audio * gain
    clipped = np.abs(driven) > clip_limit
    if float(np.mean(clipped)) > max_clipped_fraction:
        limiting_quantile = float(
            np.quantile(np.abs(audio), 1.0 - max_clipped_fraction)
        )
        gain = min(
            gain,
            clip_limit / max(limiting_quantile, 1e-15) * (1.0 + 1e-12),
        )
        driven = audio * gain
        clipped = np.abs(driven) > clip_limit
    output = np.clip(driven, -clip_limit, clip_limit)
    return output, {
        "clip_limit": clip_limit,
        "target_quantile": target_quantile,
        "target_over_limit": target_over_limit,
        "max_gain_db": max_gain_db,
        "max_clipped_fraction": max_clipped_fraction,
        "actual_gain": gain,
        "actual_gain_db": 20.0 * math.log10(gain),
        "clipped_sample_fraction": float(np.mean(clipped)),
        "clipped_samples": int(np.sum(clipped)),
    }


def apply_profile(
    audio: np.ndarray, profile: Mapping[str, Any], seed: int
) -> Tuple[np.ndarray, Dict[str, Any]]:
    if profile["kind"] == "noise":
        return add_noise(audio, profile["noise"], float(profile["snr_db"]), seed)
    if profile["kind"] == "telephone":
        return telephone_roundtrip(
            audio,
            int(profile["bandpass_low_hz"]),
            int(profile["bandpass_high_hz"]),
            int(profile["fir_taps"]),
        )
    if profile["kind"] == "clip":
        return cautious_clip(
            audio,
            float(profile["clip_limit"]),
            float(profile["target_quantile"]),
            float(profile["target_over_limit"]),
            float(profile["max_gain_db"]),
            float(profile["max_clipped_fraction"]),
        )
    if profile["kind"] == "gain":
        gain = 10 ** (float(profile["gain_db"]) / 20.0)
        return audio * gain, {"gain_db": float(profile["gain_db"]), "gain": gain}
    raise DegradationError(f"Unsupported profile kind: {profile['kind']}")


def audio_record(path: Path, root: Path) -> Dict[str, Any]:
    info = sf.info(str(path))
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "sample_rate_hz": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
        "duration_seconds": info.duration,
        "format": info.format,
        "subtype": info.subtype,
    }


def write_holdout_seal(root: Path) -> Path:
    seal_path = root / "HOLDOUT_SEAL.json"
    if seal_path.exists():
        raise DegradationError("Derived holdout is already sealed")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    seal = {
        "schema_version": 1,
        "sealed": True,
        "policy": "Any byte change invalidates this derived holdout; never repair in place.",
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }
    seal_path.write_bytes(canonical_json_bytes(seal))
    return seal_path


def verify_seal(root: Path) -> List[str]:
    seal_path = root / "HOLDOUT_SEAL.json"
    if not seal_path.is_file():
        return ["missing HOLDOUT_SEAL.json"]
    with seal_path.open("r", encoding="utf-8") as handle:
        seal = json.load(handle)
    errors: List[str] = []
    expected: set[str] = set()
    for record in seal.get("files", []):
        relative = str(record.get("path", ""))
        expected.add(relative)
        path = (root / relative).resolve()
        if not is_relative_to(path, root.resolve()) or not path.is_file():
            errors.append(f"sealed file missing or unsafe: {relative}")
        elif path.stat().st_size != record.get("bytes"):
            errors.append(f"sealed size mismatch: {relative}")
        elif sha256_file(path) != record.get("sha256"):
            errors.append(f"sealed hash mismatch: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "HOLDOUT_SEAL.json"
    }
    for relative in sorted(actual - expected):
        errors.append(f"file added after seal: {relative}")
    return errors


def verify_derived(
    root: Path, verify_parent: bool = True, require_directory_name: bool = True
) -> List[str]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return ["missing manifest.json"]
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    errors: List[str] = []
    if require_directory_name and manifest.get("dataset_id") != root.name:
        errors.append("dataset_id does not match directory name")
    expected_paths: set[str] = set()
    for clip in manifest.get("clips", []):
        relative = str(clip.get("path", ""))
        expected_paths.add(relative)
        path = (root / relative).resolve()
        if not is_relative_to(path, root) or not path.is_file():
            errors.append(f"missing or unsafe artifact: {relative}")
        elif path.stat().st_size != clip.get("bytes"):
            errors.append(f"size mismatch: {relative}")
        elif sha256_file(path) != clip.get("sha256"):
            errors.append(f"hash mismatch: {relative}")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.wav")
        if path.is_file()
    }
    for relative in sorted(actual_paths - expected_paths):
        errors.append(f"unmanifested WAV: {relative}")
    if manifest.get("is_holdout"):
        errors.extend(verify_seal(root))
    if verify_parent:
        parent = manifest.get("parent", {})
        parent_path_value = parent.get("manifest_path")
        if not parent_path_value:
            errors.append("missing parent manifest path")
        else:
            parent_path = Path(parent_path_value)
            if not parent_path.is_absolute():
                parent_path = APP_ROOT / parent_path
            if not parent_path.is_file():
                errors.append("parent manifest missing")
            elif sha256_file(parent_path) != parent.get("manifest_sha256"):
                errors.append("parent manifest hash mismatch")
            else:
                try:
                    parent_manifest, parent_clips, _seal = load_and_verify_parent(
                        parent_path,
                        variant=str(manifest.get("source_variant", "clean")),
                    )
                    parent_hashes = {
                        str(item["id"]): str(item["sha256"])
                        for item in parent_clips
                    }
                    if logical_split(parent_manifest) != manifest.get("split"):
                        errors.append("derived split differs from parent split")
                    if is_holdout(parent_manifest) != bool(manifest.get("is_holdout")):
                        errors.append("derived holdout status differs from parent")
                    for clip in manifest.get("clips", []):
                        bound = clip.get("parent_clip", {})
                        if parent_hashes.get(str(bound.get("id"))) != bound.get(
                            "sha256"
                        ):
                            errors.append(
                                f"parent clip binding mismatch: {bound.get('id')}"
                            )
                except (DegradationError, OSError, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"parent verification failed: {exc}")
    return errors


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    if is_relative_to(resolved, APP_ROOT.resolve()):
        return resolved.relative_to(APP_ROOT.resolve()).as_posix()
    return str(resolved)


def build(
    parent_manifest_path: Path,
    variant: str = "clean",
    seed: int = BASE_SEED,
    confirm_holdout_derivation: bool = False,
) -> Path:
    parent_manifest_path = parent_manifest_path.resolve()
    parent, parent_clips, parent_seal = load_and_verify_parent(
        parent_manifest_path, variant=variant
    )
    holdout = is_holdout(parent)
    if holdout and not confirm_holdout_derivation:
        raise DegradationError(
            "Holdout derivation requires --confirm-holdout-derivation and produces a sealed output"
        )
    dataset_id = derived_dataset_id(str(parent["dataset_id"]), seed)
    destination = safe_destination(dataset_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{dataset_id}.tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        records: List[Dict[str, Any]] = []
        configuration_sha256 = config_hash(seed)
        generator_sha256 = sha256_file(Path(__file__))
        for parent_clip in parent_clips:
            audio = read_audio(parent_clip["path"])
            clip_id = safe_id(parent_clip["id"])
            for profile in PROFILES:
                per_clip_seed = derived_seed(seed, parent_clip["sha256"], profile["name"])
                degraded, measured = apply_profile(audio, profile, per_clip_seed)
                output_path = staging / "clips" / profile["name"] / f"{clip_id}.wav"
                write_audio(output_path, degraded)
                record = audio_record(output_path, staging)
                record.update(
                    {
                        "derived_clip_id": f"{clip_id}--{profile['name']}",
                        "profile": profile["name"],
                        "parameters": {**profile, **measured},
                        "processing_provenance": {
                            "generator_sha256": generator_sha256,
                            "configuration_sha256": configuration_sha256,
                            "base_seed": seed,
                            "per_clip_profile_seed": per_clip_seed,
                            "numpy": np.__version__,
                            "soundfile": sf.__version__,
                            "libsndfile": getattr(
                                sf, "__libsndfile_version__", "unknown"
                            ),
                        },
                        "parent_clip": {
                            "id": parent_clip["id"],
                            "manifest_path": parent_clip["manifest_path"],
                            "sha256": parent_clip["sha256"],
                        },
                        "reference": parent_clip["reference"],
                    }
                )
                records.append(record)
        config = degradation_config(seed)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "dataset_family": "degraded_v1",
            "generated_at_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "split": logical_split(parent),
            "usage": parent.get("usage"),
            "official_split": parent.get("official_split"),
            "is_holdout": holdout,
            "source_variant": variant,
            "parent": {
                "dataset_id": parent["dataset_id"],
                "manifest_path": _display_path(parent_manifest_path),
                "manifest_sha256": sha256_file(parent_manifest_path),
                "seal": parent_seal,
                "clip_count": len(parent_clips),
            },
            "degradation": {
                "configuration": config,
                "configuration_sha256": configuration_sha256,
                "generator_path": _display_path(Path(__file__)),
                "generator_sha256": generator_sha256,
            },
            "tool_provenance": {
                "python": platform.python_version(),
                "python_executable": sys.executable,
                "platform": platform.platform(),
                "numpy": np.__version__,
                "soundfile": sf.__version__,
                "libsndfile": getattr(sf, "__libsndfile_version__", "unknown"),
            },
            "clips": records,
        }
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        if holdout:
            write_holdout_seal(staging)
        errors = verify_derived(
            staging, verify_parent=True, require_directory_name=False
        )
        if errors:
            raise DegradationError("Derived dataset failed verification: " + "; ".join(errors))
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def plan(parent_manifest_path: Path, variant: str, seed: int) -> Dict[str, Any]:
    parent, clips, seal = load_and_verify_parent(parent_manifest_path, variant=variant)
    dataset_id = derived_dataset_id(str(parent["dataset_id"]), seed)
    destination = safe_destination(dataset_id)
    return {
        "operation": "plan-only; no output files generated",
        "parent_dataset_id": parent["dataset_id"],
        "parent_manifest_sha256": sha256_file(parent_manifest_path),
        "parent_clips": len(clips),
        "split": logical_split(parent),
        "is_holdout": is_holdout(parent),
        "parent_seal_verified": seal is not None,
        "source_variant": variant,
        "profiles": [profile["name"] for profile in PROFILES],
        "derived_clips": len(clips) * len(PROFILES),
        "dataset_id": dataset_id,
        "destination": str(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "build"):
        command = subparsers.add_parser(name)
        command.add_argument("parent_manifest", type=Path)
        command.add_argument("--variant", default="clean")
        command.add_argument("--seed", type=int, default=BASE_SEED)
        if name == "build":
            command.add_argument("--confirm-holdout-derivation", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            print(
                json.dumps(
                    plan(args.parent_manifest, args.variant, args.seed),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "build":
            destination = build(
                args.parent_manifest,
                variant=args.variant,
                seed=args.seed,
                confirm_holdout_derivation=args.confirm_holdout_derivation,
            )
            print(f"Generated and verified: {destination}")
        else:
            errors = verify_derived(args.dataset, verify_parent=True)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print(f"Verified: {args.dataset.resolve()}")
    except (DegradationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
