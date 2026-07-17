#!/usr/bin/env python3
"""Build versioned German synthetic ASR evaluation data without touching fixtures."""

from __future__ import annotations

import argparse
import audioop
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


HERE = Path(__file__).resolve().parent
EVALUATION_ROOT = HERE.parent
APP_ROOT = EVALUATION_ROOT.parent
SPEC_DIR = HERE / "specs"
GENERATED_ROOT = EVALUATION_ROOT / "generated" / "synthetic_v2"
PROTECTED_ROOTS = (
    EVALUATION_ROOT / "data" / "raw",
    APP_ROOT / "fixtures" / "audio",
)

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
CHANNELS = 1
TRIM_FRAME_MS = 10
TRIM_THRESHOLD_DBFS = -50.0
TRAILING_GUARD_MS = 20
INTERCOM_FILTER = (
    "highpass=f=120,lowpass=f=5000,"
    "acompressor=threshold=0.063:ratio=2:attack=10:release=150"
)
BUILD_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
VOICE_LINE_RE = re.compile(r"^(.*?)\s+([a-z]{2}_[A-Z]{2})\s+#\s*(.*)$")


class SynthesisError(RuntimeError):
    """Raised for unsafe or invalid generation requests."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def spec_path(split: str, spec_version: str = "v2") -> Path:
    if split not in {"dev", "holdout"}:
        raise SynthesisError(f"Unsupported split: {split}")
    if spec_version == "v2":
        return SPEC_DIR / f"{split}.json"
    if spec_version in {"v3", "v4", "v5", "v6", "v7", "v8", "v9"}:
        return SPEC_DIR / f"{split}_{spec_version}.json"
    raise SynthesisError(f"Unsupported spec version: {spec_version}")


def load_spec(split: str, spec_version: str = "v2") -> Dict[str, Any]:
    path = spec_path(split, spec_version)
    with path.open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    validate_spec(spec, expected_split=split)
    if spec["dataset_version"] != f"synthetic_de_{spec_version}":
        raise SynthesisError(
            f"Spec {path.name} has unexpected dataset_version {spec['dataset_version']!r}"
        )
    if spec_version in {"v7", "v8", "v9"}:
        validate_safety_catalog_binding(spec, spec_version)
    return spec


def validate_safety_catalog_binding(
    spec: Mapping[str, Any], spec_version: str = "v7"
) -> None:
    binding = spec.get("safety_catalog")
    if not isinstance(binding, Mapping):
        raise SynthesisError(f"{spec_version} spec must bind a safety catalog")
    relative = Path(str(binding.get("path", "")))
    if relative.is_absolute() or not relative.parts or relative.parts[0] != "evaluation":
        raise SynthesisError(
            f"{spec_version} safety catalog path must be project-relative"
        )
    path = (APP_ROOT / relative).resolve()
    if not is_relative_to(path, APP_ROOT.resolve()) or not path.is_file():
        raise SynthesisError(
            f"{spec_version} safety catalog path is missing or unsafe"
        )
    expected_hash = str(binding.get("sha256", ""))
    if sha256_file(path) != expected_hash:
        raise SynthesisError(f"{spec_version} safety catalog SHA-256 mismatch")
    with path.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    if catalog.get("catalog_id") != binding.get("catalog_id"):
        raise SynthesisError(f"{spec_version} safety catalog id mismatch")
    if spec_version in {"v8", "v9"}:
        if catalog.get("mode") != "closed_command":
            raise SynthesisError("v8 safety catalog must define closed_command mode")
        commands: Dict[str, Tuple[str, set[str]]] = {}
        for command in catalog.get("commands", []):
            command_id = str(command.get("command_id", ""))
            intent_id = str(command.get("intent_id", ""))
            phrases = {
                str(phrase) for phrase in command.get("allowed_phrases", [])
            }
            if (
                not command_id
                or not intent_id
                or not phrases
                or command_id in commands
                or "" in phrases
            ):
                raise SynthesisError("v8 safety catalog has invalid commands")
            commands[command_id] = (intent_id, phrases)
        safety_realizations: set[Tuple[str, str]] = set()
        negative_cases: Dict[str, str] = {}
        for item in spec.get("utterances", []):
            is_safety = "closed_command" in item.get("categories", [])
            if not is_safety:
                if "command_id" in item:
                    raise SynthesisError(
                        f"Open utterance {item.get('id')} must not bind command_id"
                    )
                is_negative = "safety_negative_ood" in item.get("categories", [])
                if is_negative:
                    if spec_version != "v9":
                        raise SynthesisError("Safety-negative OOD data requires v9")
                    if item.get("expected_command_id", "missing") is not None:
                        raise SynthesisError(
                            f"Negative utterance {item.get('id')} must expect null command_id"
                        )
                    case_id = str(item.get("negative_case_id", ""))
                    negative_type = str(item.get("negative_type", ""))
                    if not case_id or not negative_type or case_id in negative_cases:
                        raise SynthesisError("v9 has invalid or duplicate negative cases")
                    negative_cases[case_id] = negative_type
                elif spec_version == "v9" and "expected_command_id" in item:
                    raise SynthesisError(
                        f"Open utterance {item.get('id')} must omit expected_command_id"
                    )
                continue
            command_id = str(item.get("command_id", ""))
            if command_id not in commands:
                raise SynthesisError(
                    f"Utterance {item.get('id')} has an unapproved command_id"
                )
            intent_id, phrases = commands[command_id]
            if item.get("intent") != intent_id or item.get("text") not in phrases:
                raise SynthesisError(
                    f"Utterance {item.get('id')} does not match its closed command"
                )
            safety_realizations.add((command_id, str(item["text"])))
        catalog_realizations = {
            (command_id, phrase)
            for command_id, (_intent_id, phrases) in commands.items()
            for phrase in phrases
        }
        if safety_realizations != catalog_realizations:
            raise SynthesisError(
                "v8 split must realize every allowed safety phrase exactly once"
            )
        catalog_phrases = {phrase for _command_id, phrase in catalog_realizations}
        for item in spec.get("utterances", []):
            if "safety_negative_ood" in item.get("categories", []):
                if str(item["text"]) in catalog_phrases:
                    raise SynthesisError("v9 negative text is an allowed catalog phrase")
        if spec_version == "v9" and not negative_cases:
            raise SynthesisError("v9 must contain safety-negative OOD cases")
        return
    allowed = {str(item.get("id", "")) for item in catalog.get("allowed_intents", [])}
    if not allowed or "" in allowed:
        raise SynthesisError("v7 safety catalog has invalid intents")
    for item in spec.get("utterances", []):
        if item.get("intent") not in allowed:
            raise SynthesisError(f"Utterance {item.get('id')} has an unapproved intent")


def validate_spec(spec: Mapping[str, Any], expected_split: str = "") -> None:
    required = {
        "schema_version",
        "dataset_version",
        "split",
        "language",
        "pause_seconds",
        "utterances",
    }
    missing = required - set(spec)
    if missing:
        raise SynthesisError(f"Spec misses fields: {sorted(missing)}")
    if spec["schema_version"] != "2.0":
        raise SynthesisError("Only synthesis spec schema 2.0 is supported")
    if expected_split and spec["split"] != expected_split:
        raise SynthesisError(
            f"Expected split {expected_split!r}, got {spec['split']!r}"
        )
    if spec["split"] not in {"dev", "holdout"}:
        raise SynthesisError(f"Invalid split: {spec['split']!r}")
    pause_frames = float(spec["pause_seconds"]) * SAMPLE_RATE
    if pause_frames != int(pause_frames) or not 0.20 <= float(
        spec["pause_seconds"]
    ) <= 1.0:
        raise SynthesisError("pause_seconds must be 0.20..1.00 and sample-exact")
    utterances = spec["utterances"]
    if not isinstance(utterances, list) or not utterances:
        raise SynthesisError("utterances must be a non-empty list")
    ids: set[str] = set()
    texts: set[str] = set()
    voices: set[str] = set()
    categories: set[str] = set()
    for item in utterances:
        item_required = {
            "id",
            "speaker",
            "role",
            "voice",
            "rate",
            "text",
            "categories",
        }
        item_missing = item_required - set(item)
        if item_missing:
            raise SynthesisError(
                f"Utterance {item.get('id', '?')} misses {sorted(item_missing)}"
            )
        if item["id"] in ids or item["text"] in texts:
            raise SynthesisError(f"Duplicate id or text: {item['id']}")
        if not 120 <= int(item["rate"]) <= 220:
            raise SynthesisError(f"Unsafe speech rate in {item['id']}")
        if not item["text"].strip() or item["text"] != item["text"].strip():
            raise SynthesisError(f"Invalid whitespace in {item['id']}")
        if not isinstance(item["categories"], list) or not item["categories"]:
            raise SynthesisError(f"Missing categories in {item['id']}")
        ids.add(item["id"])
        texts.add(item["text"])
        voices.add(item["voice"])
        categories.update(item["categories"])
    missing_lengths = {"short", "medium", "long"} - categories
    if missing_lengths:
        raise SynthesisError(f"Missing length coverage: {sorted(missing_lengths)}")
    if len(voices) < 3:
        raise SynthesisError("Each split must use at least three voices")
    all_text = " ".join(texts)
    if not any(character in all_text for character in "äöüÄÖÜß"):
        raise SynthesisError("Spec must contain real German umlauts or ß")
    if spec["split"] == "holdout" and not spec.get("seal_after_generation"):
        raise SynthesisError("Holdout must request sealing after generation")


def validate_split_isolation(
    dev_spec: Mapping[str, Any], holdout_spec: Mapping[str, Any]
) -> None:
    def values(spec: Mapping[str, Any], field: str) -> set[str]:
        return {str(item[field]).casefold() for item in spec["utterances"]}

    fields = ["id", "speaker", "voice"]
    is_closed_suite = (
        dev_spec.get("dataset_version") in {"synthetic_de_v8", "synthetic_de_v9"}
        and dev_spec.get("dataset_version") == holdout_spec.get("dataset_version")
    )
    if (
        dev_spec.get("dataset_version") == "synthetic_de_v7"
        and holdout_spec.get("dataset_version") == "synthetic_de_v7"
    ) or is_closed_suite:
        fields.append("rate")
    if not is_closed_suite:
        fields.append("text")
    for field in fields:
        overlap = values(dev_spec, field) & values(holdout_spec, field)
        if overlap:
            raise SynthesisError(
                f"Dev/holdout leakage in {field}: {sorted(overlap)}"
            )
    if is_closed_suite:
        if dev_spec.get("safety_catalog") != holdout_spec.get("safety_catalog"):
            raise SynthesisError("v8 splits must bind the same frozen safety catalog")
        def safety_pairs(spec: Mapping[str, Any]) -> set[Tuple[str, str]]:
            return {
                (str(item.get("command_id", "")), str(item["text"]))
                for item in spec["utterances"]
                if "closed_command" in item.get("categories", [])
            }
        if safety_pairs(dev_spec) != safety_pairs(holdout_spec):
            raise SynthesisError("v8 safety commands must be identical across splits")
        def open_texts(spec: Mapping[str, Any]) -> set[str]:
            return {
                str(item["text"]).casefold()
                for item in spec["utterances"]
                if "open_dictation" in item.get("categories", [])
            }
        overlap = open_texts(dev_spec) & open_texts(holdout_spec)
        if overlap:
            raise SynthesisError(
                f"v8 Dev/holdout open-dictation leakage: {sorted(overlap)}"
            )
        if dev_spec.get("dataset_version") == "synthetic_de_v9":
            def negative_cases(spec: Mapping[str, Any]) -> Dict[str, Tuple[str, str]]:
                return {
                    str(item["negative_case_id"]): (
                        str(item["negative_type"]),
                        str(item["text"]).casefold(),
                    )
                    for item in spec["utterances"]
                    if "safety_negative_ood" in item.get("categories", [])
                }
            dev_negative = negative_cases(dev_spec)
            holdout_negative = negative_cases(holdout_spec)
            if set(dev_negative) != set(holdout_negative):
                raise SynthesisError("v9 negative case coverage differs across splits")
            for case_id in dev_negative:
                if dev_negative[case_id][0] != holdout_negative[case_id][0]:
                    raise SynthesisError(
                        f"v9 negative type differs for case {case_id}"
                    )
                if dev_negative[case_id][1] == holdout_negative[case_id][1]:
                    raise SynthesisError(
                        f"v9 negative text must be split-disjoint for case {case_id}"
                    )


def safe_build_destination(split: str, build_id: str) -> Path:
    if not BUILD_ID_RE.fullmatch(build_id):
        raise SynthesisError(
            "build-id must be 1..64 safe characters: letters, digits, dot, dash, underscore"
        )
    destination = (GENERATED_ROOT / split / build_id).resolve()
    generated_root = GENERATED_ROOT.resolve()
    if not is_relative_to(destination, generated_root):
        raise SynthesisError("Destination escaped the generated-data root")
    for protected in PROTECTED_ROOTS:
        if is_relative_to(destination, protected.resolve()):
            raise SynthesisError(f"Protected destination: {destination}")
    if destination.exists():
        marker = " (sealed holdout)" if (destination / "HOLDOUT_SEAL.json").exists() else ""
        raise SynthesisError(f"Refusing to overwrite existing build{marker}: {destination}")
    return destination


def run(command: Sequence[str], capture: bool = False) -> str:
    completed = subprocess.run(
        list(command),
        check=True,
        text=capture,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SynthesisError(f"Required tool not found: {name}")
    return path


def available_voices(say_path: str) -> Dict[str, Dict[str, str]]:
    output = run([say_path, "-v", "?"], capture=True)
    result: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        match = VOICE_LINE_RE.match(line)
        if match:
            name, locale, sample = match.groups()
            result[name.strip()] = {"locale": locale, "sample": sample.strip()}
    return result


def first_version_line(tool: str, args: Sequence[str]) -> str:
    output = run([tool, *args], capture=True)
    return output.splitlines()[0] if output else "unknown"


def collect_environment(spec: Mapping[str, Any]) -> Dict[str, Any]:
    say_path = require_tool("say")
    ffmpeg_path = require_tool("ffmpeg")
    voices = available_voices(say_path)
    requested = sorted({item["voice"] for item in spec["utterances"]})
    unavailable = [voice for voice in requested if voice not in voices]
    if unavailable:
        raise SynthesisError(f"Required voices are unavailable: {unavailable}")
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "mac_ver": platform.mac_ver()[0],
        },
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        },
        "tools": {
            "say": {
                "path": say_path,
                "requested_voices": {
                    voice: voices[voice] for voice in requested
                },
            },
            "ffmpeg": {
                "path": ffmpeg_path,
                "version": first_version_line(ffmpeg_path, ["-version"]),
            },
        },
    }


def wav_info(path: Path) -> Dict[str, Any]:
    with wave.open(str(path), "rb") as audio:
        return {
            "sample_rate": audio.getframerate(),
            "channels": audio.getnchannels(),
            "sample_width_bits": audio.getsampwidth() * 8,
            "frames": audio.getnframes(),
            "duration_seconds": audio.getnframes() / audio.getframerate(),
        }


def trim_trailing_silence(
    source: Path,
    destination: Path,
    trailing_guard_ms: int = TRAILING_GUARD_MS,
) -> Dict[str, int]:
    with wave.open(str(source), "rb") as audio:
        params = audio.getparams()
        frames = audio.readframes(audio.getnframes())
    if (
        params.nchannels != CHANNELS
        or params.sampwidth != SAMPLE_WIDTH
        or params.framerate != SAMPLE_RATE
    ):
        raise SynthesisError(f"Unexpected clean WAV format: {source}")
    frame_samples = SAMPLE_RATE * TRIM_FRAME_MS // 1000
    frame_bytes = frame_samples * SAMPLE_WIDTH
    threshold = int((2 ** (SAMPLE_WIDTH * 8 - 1) - 1) * 10 ** (TRIM_THRESHOLD_DBFS / 20))
    last_active_end = 0
    for start in range(0, len(frames), frame_bytes):
        block = frames[start : start + frame_bytes]
        if block and audioop.rms(block, SAMPLE_WIDTH) >= threshold:
            last_active_end = start + len(block)
    if last_active_end == 0:
        raise SynthesisError(f"Generated utterance contains no active audio: {source}")
    guard_bytes = SAMPLE_RATE * trailing_guard_ms // 1000 * SAMPLE_WIDTH
    keep_bytes = min(len(frames), last_active_end + guard_bytes)
    keep_bytes -= keep_bytes % SAMPLE_WIDTH
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as audio:
        audio.setparams(params)
        audio.writeframes(frames[:keep_bytes])
    return {
        "input_frames": len(frames) // SAMPLE_WIDTH,
        "output_frames": keep_bytes // SAMPLE_WIDTH,
        "trimmed_frames": (len(frames) - keep_bytes) // SAMPLE_WIDTH,
        "trailing_guard_ms": trailing_guard_ms,
    }


def final_frame_is_active(path: Path) -> bool:
    frame_samples = SAMPLE_RATE * TRIM_FRAME_MS // 1000
    with wave.open(str(path), "rb") as audio:
        if audio.getnframes() < frame_samples:
            return False
        audio.setpos(audio.getnframes() - frame_samples)
        block = audio.readframes(frame_samples)
    threshold = int(
        (2 ** (SAMPLE_WIDTH * 8 - 1) - 1) * 10 ** (TRIM_THRESHOLD_DBFS / 20)
    )
    return audioop.rms(block, SAMPLE_WIDTH) >= threshold


def verify_sample_exact_pauses(
    path: Path, timeline: Sequence[Tuple[int, int]], pause_frames: int
) -> List[str]:
    errors: List[str] = []
    with wave.open(str(path), "rb") as audio:
        if (
            audio.getnchannels() != CHANNELS
            or audio.getsampwidth() != SAMPLE_WIDTH
            or audio.getframerate() != SAMPLE_RATE
        ):
            return [f"unexpected combined WAV format: {path}"]
        for index in range(len(timeline) - 1):
            gap_start = timeline[index][1]
            gap_end = timeline[index + 1][0]
            if gap_end - gap_start != pause_frames:
                errors.append(
                    f"gap {index + 1} is {gap_end - gap_start} frames, expected {pause_frames}"
                )
                continue
            audio.setpos(gap_start)
            payload = audio.readframes(pause_frames)
            if len(payload) != pause_frames * SAMPLE_WIDTH or any(payload):
                errors.append(f"gap {index + 1} is not exact digital silence")
    return errors


def convert_source_to_pcm(ffmpeg: str, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def make_intercom_variant(ffmpeg: str, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-af",
            INTERCOM_FILTER,
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )


def concatenate_with_one_pause(
    parts: Sequence[Path], destination: Path, pause_frames: int
) -> List[Tuple[int, int]]:
    if not parts:
        raise SynthesisError("No parts to concatenate")
    silence = b"\x00" * pause_frames * SAMPLE_WIDTH
    destination.parent.mkdir(parents=True, exist_ok=True)
    timeline: List[Tuple[int, int]] = []
    cursor = 0
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(CHANNELS)
        output.setsampwidth(SAMPLE_WIDTH)
        output.setframerate(SAMPLE_RATE)
        for index, part in enumerate(parts):
            with wave.open(str(part), "rb") as audio:
                if (
                    audio.getnchannels() != CHANNELS
                    or audio.getsampwidth() != SAMPLE_WIDTH
                    or audio.getframerate() != SAMPLE_RATE
                ):
                    raise SynthesisError(f"Incompatible part: {part}")
                data = audio.readframes(audio.getnframes())
                part_frames = len(data) // SAMPLE_WIDTH
            start = cursor
            output.writeframesraw(data)
            cursor += part_frames
            timeline.append((start, cursor))
            if index + 1 < len(parts):
                output.writeframesraw(silence)
                cursor += pause_frames
    return timeline


def artifact_record(path: Path, build_root: Path) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": path.relative_to(build_root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix.casefold() == ".wav":
        record["audio"] = wav_info(path)
    return record


def write_references(
    build_root: Path, spec: Mapping[str, Any]
) -> Tuple[Path, Path]:
    jsonl_path = build_root / "references.jsonl"
    text_path = build_root / "reference.txt"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in spec["utterances"]:
            record = {
                "id": item["id"],
                "speaker": item["speaker"],
                "text": item["text"],
            }
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with text_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "\n".join(item["text"] for item in spec["utterances"]) + "\n"
        )
    return jsonl_path, text_path


def build_manifest(
    build_root: Path,
    destination: Path,
    build_id: str,
    spec: Mapping[str, Any],
    environment: Mapping[str, Any],
    utterance_records: Sequence[Mapping[str, Any]],
    timeline: Sequence[Tuple[int, int]],
    spec_version: str,
) -> Path:
    artifact_paths = sorted(
        path
        for path in build_root.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "HOLDOUT_SEAL.json"}
    )
    manifest = {
        "schema_version": "2.0",
        "dataset_version": spec["dataset_version"],
        "dataset_id": f"{spec['dataset_version']}-{spec['split']}-{build_id}",
        "split": spec["split"],
        "build_id": build_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "intended_destination": destination.relative_to(APP_ROOT).as_posix(),
        "holdout_sealed": spec["split"] == "holdout",
        "language": spec["language"],
        "configuration": {
            "spec_version": spec_version,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_width_bits": SAMPLE_WIDTH * 8,
            "pause_seconds": spec["pause_seconds"],
            "pause_frames": int(float(spec["pause_seconds"]) * SAMPLE_RATE),
            "trim_frame_ms": TRIM_FRAME_MS,
            "trim_threshold_dbfs": TRIM_THRESHOLD_DBFS,
            "trailing_guard_ms": int(
                spec.get("trailing_guard_ms", TRAILING_GUARD_MS)
            ),
            "intercom_filter": INTERCOM_FILTER,
        },
        "provenance": {
            "generator": {
                "path": Path(__file__).relative_to(APP_ROOT).as_posix(),
                "sha256": sha256_file(Path(__file__)),
            },
            "spec": {
                "path": spec_path(spec["split"], spec_version)
                .relative_to(APP_ROOT)
                .as_posix(),
                "sha256": sha256_file(spec_path(spec["split"], spec_version)),
            },
            "environment": environment,
            "limitations": [
                "macOS say output may change across OS or installed voice versions",
                "synthetic speech is supplementary and must not replace human holdout data",
            ],
        },
        "variants": {
            "source": "Original per-utterance AIFF emitted by macOS say",
            "clean": "Mono 16 kHz PCM, only resampled and trailing-silence-trimmed",
            "intercom": "Clean variant plus the fixed recorded intercom filter",
        },
        "utterances": [
            {
                **record,
                "start_frame": timeline[index][0],
                "end_frame": timeline[index][1],
                "start_seconds": timeline[index][0] / SAMPLE_RATE,
                "end_seconds": timeline[index][1] / SAMPLE_RATE,
            }
            for index, record in enumerate(utterance_records)
        ],
        "artifacts": [artifact_record(path, build_root) for path in artifact_paths],
    }
    if isinstance(spec.get("safety_catalog"), Mapping):
        manifest["provenance"]["safety_catalog"] = dict(spec["safety_catalog"])
    manifest_path = build_root / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest_path


def write_holdout_seal(build_root: Path) -> Path:
    if (build_root / "HOLDOUT_SEAL.json").exists():
        raise SynthesisError("Holdout is already sealed")
    files = sorted(
        path for path in build_root.rglob("*") if path.is_file()
    )
    seal = {
        "schema_version": "1.0",
        "sealed": True,
        "policy": "Any byte change invalidates this holdout build; never repair in place.",
        "files": [
            {
                "path": path.relative_to(build_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }
    seal_path = build_root / "HOLDOUT_SEAL.json"
    seal_path.write_bytes(canonical_json_bytes(seal))
    return seal_path


def verify_manifest(build_root: Path) -> List[str]:
    errors: List[str] = []
    manifest_path = build_root / "manifest.json"
    if not manifest_path.is_file():
        return ["missing manifest.json"]
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    expected_paths: set[str] = set()
    for record in manifest.get("artifacts", []):
        relative = record.get("path", "")
        expected_paths.add(relative)
        path = (build_root / relative).resolve()
        if not is_relative_to(path, build_root.resolve()):
            errors.append(f"artifact escapes build: {relative}")
        elif not path.is_file():
            errors.append(f"missing artifact: {relative}")
        else:
            if path.stat().st_size != record.get("bytes"):
                errors.append(f"size mismatch: {relative}")
            if sha256_file(path) != record.get("sha256"):
                errors.append(f"hash mismatch: {relative}")
    actual_paths = {
        path.relative_to(build_root).as_posix()
        for path in build_root.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "HOLDOUT_SEAL.json"}
    }
    for relative in sorted(actual_paths - expected_paths):
        errors.append(f"unmanifested artifact: {relative}")
    configuration = manifest.get("configuration", {})
    pause_frames = configuration.get("pause_frames")
    utterances = manifest.get("utterances", [])
    if isinstance(pause_frames, int) and len(utterances) > 1:
        timeline = [
            (int(item["start_frame"]), int(item["end_frame"]))
            for item in utterances
        ]
        for relative in ("audio/clean.wav", "audio/intercom.wav"):
            combined = build_root / relative
            if combined.is_file():
                errors.extend(
                    f"{relative}: {error}"
                    for error in verify_sample_exact_pauses(
                        combined, timeline, pause_frames
                    )
                )
    if configuration.get("spec_version") in {
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
    }:
        if configuration.get("trailing_guard_ms") != 0:
            errors.append(
                f"{configuration.get('spec_version')} must not retain an added trailing-silence guard"
            )
        for item in utterances:
            relative = item.get("paths", {}).get("clean")
            if relative and not final_frame_is_active(build_root / relative):
                errors.append(
                    f"{configuration.get('spec_version')} clean part has a full trailing silent frame: {relative}"
                )
    return errors


def verify_holdout_seal(build_root: Path) -> List[str]:
    seal_path = build_root / "HOLDOUT_SEAL.json"
    if not seal_path.is_file():
        return ["missing HOLDOUT_SEAL.json"]
    with seal_path.open("r", encoding="utf-8") as handle:
        seal = json.load(handle)
    errors: List[str] = []
    expected: set[str] = set()
    for record in seal.get("files", []):
        relative = record.get("path", "")
        expected.add(relative)
        path = (build_root / relative).resolve()
        if not is_relative_to(path, build_root.resolve()) or not path.is_file():
            errors.append(f"sealed file missing or unsafe: {relative}")
        else:
            if path.stat().st_size != record.get("bytes"):
                errors.append(f"sealed size mismatch: {relative}")
            if sha256_file(path) != record.get("sha256"):
                errors.append(f"sealed hash mismatch: {relative}")
    actual = {
        path.relative_to(build_root).as_posix()
        for path in build_root.rglob("*")
        if path.is_file() and path.name != "HOLDOUT_SEAL.json"
    }
    for relative in sorted(actual - expected):
        errors.append(f"file added after seal: {relative}")
    return errors


def verify_build(build_root: Path) -> List[str]:
    errors = verify_manifest(build_root)
    manifest_path = build_root / "manifest.json"
    if manifest_path.is_file():
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("split") == "holdout":
            errors.extend(verify_holdout_seal(build_root))
    return errors


def generate(
    split: str,
    build_id: str,
    confirm_holdout_seal: bool,
    spec_version: str = "v2",
) -> Path:
    dev_spec = load_spec("dev", spec_version)
    holdout_spec = load_spec("holdout", spec_version)
    validate_split_isolation(dev_spec, holdout_spec)
    spec = dev_spec if split == "dev" else holdout_spec
    if split == "holdout" and not confirm_holdout_seal:
        raise SynthesisError(
            "Holdout generation requires --confirm-holdout-seal; the completed build is immutable"
        )
    destination = safe_build_destination(split, build_id)
    environment = collect_environment(spec)
    say_path = environment["tools"]["say"]["path"]
    ffmpeg_path = environment["tools"]["ffmpeg"]["path"]

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{build_id}.tmp-{uuid.uuid4().hex}"
    if staging.exists():
        raise SynthesisError(f"Unexpected staging collision: {staging}")
    staging.mkdir()
    try:
        utterance_records: List[Dict[str, Any]] = []
        clean_parts: List[Path] = []
        intercom_parts: List[Path] = []
        for item in spec["utterances"]:
            source = staging / "source_aiff" / f"{item['id']}.aiff"
            untrimmed = staging / "parts" / "clean_untrimmed" / f"{item['id']}.wav"
            clean = staging / "parts" / "clean" / f"{item['id']}.wav"
            intercom = staging / "parts" / "intercom" / f"{item['id']}.wav"
            source.parent.mkdir(parents=True, exist_ok=True)
            run(
                [
                    say_path,
                    "-v",
                    item["voice"],
                    "-r",
                    str(item["rate"]),
                    "-o",
                    str(source),
                    item["text"],
                ]
            )
            convert_source_to_pcm(ffmpeg_path, source, untrimmed)
            trailing_guard_ms = int(
                spec.get("trailing_guard_ms", TRAILING_GUARD_MS)
            )
            trim = trim_trailing_silence(
                untrimmed, clean, trailing_guard_ms=trailing_guard_ms
            )
            if spec_version in {"v3", "v4", "v5", "v6", "v7", "v8", "v9"} and not final_frame_is_active(clean):
                raise SynthesisError(
                    f"{spec_version} trailing trim left a full silent frame in {item['id']}"
                )
            make_intercom_variant(ffmpeg_path, clean, intercom)
            if wav_info(clean)["frames"] != wav_info(intercom)["frames"]:
                raise SynthesisError(f"Variant duration mismatch for {item['id']}")
            clean_parts.append(clean)
            intercom_parts.append(intercom)
            utterance_records.append(
                {
                    "id": item["id"],
                    "speaker": item["speaker"],
                    "role": item["role"],
                    "voice": item["voice"],
                    "rate": item["rate"],
                    "text": item["text"],
                    "categories": item["categories"],
                    **({"intent": item["intent"]} if "intent" in item else {}),
                    **(
                        {"command_id": item["command_id"]}
                        if "command_id" in item
                        else {}
                    ),
                    **(
                        {"expected_command_id": item["expected_command_id"]}
                        if "expected_command_id" in item
                        else {}
                    ),
                    **(
                        {"negative_case_id": item["negative_case_id"]}
                        if "negative_case_id" in item
                        else {}
                    ),
                    **(
                        {"negative_type": item["negative_type"]}
                        if "negative_type" in item
                        else {}
                    ),
                    "trim": trim,
                    "paths": {
                        "source_aiff": source.relative_to(staging).as_posix(),
                        "clean_untrimmed": untrimmed.relative_to(staging).as_posix(),
                        "clean": clean.relative_to(staging).as_posix(),
                        "intercom": intercom.relative_to(staging).as_posix(),
                    },
                }
            )

        pause_frames = int(float(spec["pause_seconds"]) * SAMPLE_RATE)
        clean_timeline = concatenate_with_one_pause(
            clean_parts, staging / "audio" / "clean.wav", pause_frames
        )
        intercom_timeline = concatenate_with_one_pause(
            intercom_parts, staging / "audio" / "intercom.wav", pause_frames
        )
        if clean_timeline != intercom_timeline:
            raise SynthesisError("Clean and intercom timelines differ")
        for variant_name, combined in (
            ("clean", staging / "audio" / "clean.wav"),
            ("intercom", staging / "audio" / "intercom.wav"),
        ):
            pause_errors = verify_sample_exact_pauses(
                combined, clean_timeline, pause_frames
            )
            if pause_errors:
                raise SynthesisError(
                    f"{variant_name} pause verification failed: {pause_errors}"
                )
        write_references(staging, spec)
        build_manifest(
            staging,
            destination,
            build_id,
            spec,
            environment,
            utterance_records,
            clean_timeline,
            spec_version,
        )
        if split == "holdout":
            write_holdout_seal(staging)
        errors = verify_build(staging)
        if errors:
            raise SynthesisError("Generated build failed verification: " + "; ".join(errors))
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def plan(
    split: str, build_id: str, spec_version: str = "v2"
) -> Dict[str, Any]:
    dev_spec = load_spec("dev", spec_version)
    holdout_spec = load_spec("holdout", spec_version)
    validate_split_isolation(dev_spec, holdout_spec)
    spec = dev_spec if split == "dev" else holdout_spec
    destination = safe_build_destination(split, build_id)
    return {
        "operation": "plan-only; no files generated",
        "split": split,
        "spec_version": spec_version,
        "dataset_version": spec["dataset_version"],
        "build_id": build_id,
        "utterances": len(spec["utterances"]),
        "voices": sorted({item["voice"] for item in spec["utterances"]}),
        "destination": str(destination),
        "protected_roots": [str(path.resolve()) for path in PROTECTED_ROOTS],
        "will_overwrite_app_demo": False,
        "will_write_data_raw": False,
        "holdout_will_be_sealed": split == "holdout",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "build"):
        command = subparsers.add_parser(name)
        command.add_argument("--split", required=True, choices=("dev", "holdout"))
        command.add_argument("--build-id", required=True)
        command.add_argument(
            "--spec-version",
            choices=("v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9"),
            default="v2",
        )
        if name == "build":
            command.add_argument("--confirm-holdout-seal", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            print(
                json.dumps(
                    plan(args.split, args.build_id, args.spec_version),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "build":
            destination = generate(
                args.split,
                args.build_id,
                args.confirm_holdout_seal,
                args.spec_version,
            )
            print(f"Generated and verified: {destination}")
        else:
            errors = verify_build(args.path.resolve())
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print(f"Verified: {args.path.resolve()}")
    except (OSError, subprocess.CalledProcessError, SynthesisError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
