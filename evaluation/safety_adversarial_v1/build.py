#!/usr/bin/env python3
"""Build the Dev-only adversarial Safety audio suite without running ASR."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
import wave

import numpy as np


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.synthesis_v2.generate import (  # noqa: E402
    available_voices,
    convert_source_to_pcm,
    make_intercom_variant,
    require_tool,
    run,
    trim_trailing_silence,
)


SPEC_PATH = HERE / "spec.json"
GENERATED_ROOT = PROJECT_ROOT / "evaluation/generated/safety_adversarial_v1/dev"
MANIFEST_DIR = PROJECT_ROOT / "evaluation/data/manifests"
MANIFESTS = {
    "clean": MANIFEST_DIR / "safety_adversarial_dev_clean_v1.json",
    "intercom": MANIFEST_DIR / "safety_adversarial_dev_intercom_v1.json",
}
REFERENCE_STATUS = "synthetic_source_pending_manual_audio_review"
SAMPLE_RATE = 16_000


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def load_spec() -> dict:
    data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "transcom-safety-adversarial-source-v1":
        raise BuildError("Unsupported source schema")
    if data.get("split") != "dev" or data.get("reference_status") != REFERENCE_STATUS:
        raise BuildError("Suite must remain Dev-only and pending manual audio review")
    rows = data.get("utterances")
    if not isinstance(rows, list) or len(rows) < 8:
        raise BuildError("At least eight adversarial utterances are required")
    ids = [str(row.get("id") or "") for row in rows]
    texts = [str(row.get("text") or "") for row in rows]
    if len(ids) != len(set(ids)) or len(texts) != len(set(texts)) or "" in ids + texts:
        raise BuildError("Utterance ids and texts must be non-empty and unique")
    required_actions = {
        "fallen", "auslassen", "sterben", "lösen",
        "verbinden", "betreten", "freigeben", "starten",
    }
    if {str(row.get("observed_action")) for row in rows} != required_actions:
        raise BuildError("The frozen changed-action coverage is incomplete")
    if len({str(row.get("voice")) for row in rows}) < 3:
        raise BuildError("At least three local German voices are required")
    for row in rows:
        if not 120 <= int(row.get("rate", 0)) <= 220:
            raise BuildError(f"Unsafe speech rate in {row.get('id')}")
        if row.get("observed_action") == row.get("canonical_action"):
            raise BuildError(f"Action was not changed in {row.get('id')}")
    return data


def wav_qa(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        if (
            handle.getnchannels() != 1
            or handle.getsampwidth() != 2
            or handle.getframerate() != SAMPLE_RATE
            or handle.getcomptype() != "NONE"
        ):
            raise BuildError(f"Not PCM16 mono 16 kHz: {path}")
        frames = handle.getnframes()
        payload = handle.readframes(frames)
    samples = np.frombuffer(payload, dtype="<i2")
    if not frames or samples.size != frames or not np.any(samples):
        raise BuildError(f"Empty or silent audio: {path}")
    peak = int(np.max(np.abs(samples.astype(np.int32))))
    if peak >= 32767:
        raise BuildError(f"Clipped audio: {path}")
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return {
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "sample_width_bits": 16,
        "codec": "pcm_s16le",
        "frames": frames,
        "duration_seconds": frames / SAMPLE_RATE,
        "peak_pcm16": peak,
        "rms_pcm16": rms,
    }


def clip_record(row: dict, variant: str, audio_path: Path, qa: dict) -> dict:
    return {
        "id": row["id"],
        "audio_id": row["id"],
        "data_path": audio_path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": sha256_file(audio_path),
        "reference_text": row["text"],
        "reference_status": REFERENCE_STATUS,
        "expected_command_id": None,
        "speaker_id": row["speaker"],
        "voice": row["voice"],
        "rate": row["rate"],
        "role": row["role"],
        "official_split": "dev",
        "variant": variant,
        "negative_type": "changed_action_verb",
        "canonical_command_id": row["canonical_command_id"],
        "canonical_text": row["canonical_text"],
        "observed_action": row["observed_action"],
        "canonical_action": row["canonical_action"],
        "categories": [
            "short",
            "safety_negative_ood",
            "adversarial",
            "changed_action_verb",
            "technical",
        ],
        "audio_qa": qa,
    }


def manifest(spec: dict, variant: str, clips: list[dict], ffmpeg: str) -> dict:
    return {
        "schema_version": 1,
        "dataset_id": f"{spec['dataset_id']}-{variant}",
        "dataset_name": f"Safety adversarial German Dev v1 ({variant})",
        "usage": "dev",
        "split": "dev",
        "official_split": "dev",
        "is_holdout": False,
        "language": "de",
        "group": f"synthetic_{variant}",
        "variant": variant,
        "scoring_authorized": False,
        "manual_audio_review_required": True,
        "reference_policy": (
            "Synthetic source text only; ASR scoring is forbidden until every audio file "
            "passes the hash-bound manual listening review."
        ),
        "source": {
            "spec": SPEC_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "spec_sha256": sha256_file(SPEC_PATH),
            "build_script": Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix(),
            "build_script_sha256": sha256_file(Path(__file__).resolve()),
            "platform": platform.platform(),
            "ffmpeg": subprocess.check_output(
                [ffmpeg, "-version"], text=True
            ).splitlines()[0],
        },
        "clips": clips,
    }


def _atomic_new_file(path: Path, payload: bytes) -> None:
    if path.exists():
        raise BuildError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        temporary = Path(tmp.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build() -> None:
    spec = load_spec()
    if GENERATED_ROOT.exists() or any(path.exists() for path in MANIFESTS.values()):
        raise BuildError("Refusing to overwrite an existing versioned suite")
    say = require_tool("say")
    ffmpeg = require_tool("ffmpeg")
    voices = available_voices(say)
    missing = sorted({row["voice"] for row in spec["utterances"]} - set(voices))
    if missing:
        raise BuildError(f"Required German voices are unavailable: {missing}")

    GENERATED_ROOT.parent.mkdir(parents=True, exist_ok=True)
    staging = GENERATED_ROOT.parent / f".{GENERATED_ROOT.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    clips = {"clean": [], "intercom": []}
    try:
        for row in spec["utterances"]:
            work = staging / ".work"
            source = work / f"{row['id']}.aiff"
            untrimmed = work / f"{row['id']}.wav"
            clean = staging / "clean" / f"{row['id']}.wav"
            intercom = staging / "intercom" / f"{row['id']}.wav"
            work.mkdir(exist_ok=True)
            run([
                say, "-v", row["voice"], "-r", str(row["rate"]),
                "-o", str(source), row["text"],
            ])
            convert_source_to_pcm(ffmpeg, source, untrimmed)
            trim_trailing_silence(untrimmed, clean, trailing_guard_ms=20)
            make_intercom_variant(ffmpeg, clean, intercom)
            clean_qa = wav_qa(clean)
            intercom_qa = wav_qa(intercom)
            if clean_qa["frames"] != intercom_qa["frames"]:
                raise BuildError(f"Variant frame mismatch for {row['id']}")
            clips["clean"].append(clip_record(row, "clean", clean, clean_qa))
            clips["intercom"].append(clip_record(row, "intercom", intercom, intercom_qa))
        shutil.rmtree(staging / ".work")

        # Records were created against staging paths; bind their immutable final paths.
        for variant in clips:
            for record in clips[variant]:
                record["data_path"] = (
                    GENERATED_ROOT / variant / f"{record['id']}.wav"
                ).relative_to(PROJECT_ROOT).as_posix()
        manifests = {
            variant: manifest(spec, variant, clips[variant], ffmpeg)
            for variant in ("clean", "intercom")
        }
        os.replace(staging, GENERATED_ROOT)
        for variant, path in MANIFESTS.items():
            _atomic_new_file(path, json_bytes(manifests[variant]))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    verify()
    for variant, path in MANIFESTS.items():
        print(f"{variant}: {path.relative_to(PROJECT_ROOT)} sha256={sha256_file(path)}")


def verify() -> None:
    spec = load_spec()
    for variant, path in MANIFESTS.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("scoring_authorized") is not False or data.get("split") != "dev":
            raise BuildError(f"Unsafe scoring/split state in {path}")
        rows = data.get("clips")
        if not isinstance(rows, list) or len(rows) != len(spec["utterances"]):
            raise BuildError(f"Unexpected clip count in {path}")
        for clip in rows:
            if clip.get("expected_command_id", "missing") is not None:
                raise BuildError(f"Negative clip expects a command: {clip.get('id')}")
            if clip.get("reference_status") != REFERENCE_STATUS:
                raise BuildError(f"Unexpected review status: {clip.get('id')}")
            audio = PROJECT_ROOT / clip["data_path"]
            if sha256_file(audio) != clip.get("sha256"):
                raise BuildError(f"Audio hash mismatch: {audio}")
            qa = wav_qa(audio)
            if qa != clip.get("audio_qa"):
                raise BuildError(f"Audio QA mismatch: {audio}")
            if clip.get("variant") != variant:
                raise BuildError(f"Variant mismatch: {clip.get('id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    args = parser.parse_args()
    try:
        build() if args.command == "build" else verify()
    except (BuildError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
