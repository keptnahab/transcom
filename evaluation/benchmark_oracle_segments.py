#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Callable

import numpy as np
import soundfile as sf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import backend.config as cfg
from backend.transcription.engine import WhisperEngine
from evaluation.metrics import EditCounts, character_errors, word_errors


Timer = Callable[[], float]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _counts_dict(counts: EditCounts) -> dict:
    return {
        "substitutions": counts.substitutions,
        "deletions": counts.deletions,
        "insertions": counts.insertions,
        "errors": counts.errors,
        "reference_length": counts.reference_length,
        "rate": counts.rate,
    }


def _sum_counts(counts: list[EditCounts]) -> dict:
    substitutions = sum(item.substitutions for item in counts)
    deletions = sum(item.deletions for item in counts)
    insertions = sum(item.insertions for item in counts)
    reference_length = sum(item.reference_length for item in counts)
    errors = substitutions + deletions + insertions
    rate = errors / reference_length if reference_length else (0.0 if errors == 0 else 1.0)
    return {
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "errors": errors,
        "reference_length": reference_length,
        "rate": rate,
    }


def _transcript_text(segments: list) -> str:
    if not segments:
        return ""
    texts = [str(getattr(segment, "text", "") or "") for segment in segments]
    if all(bool(getattr(segment, "is_word", False)) for segment in segments):
        return "".join(texts).strip()
    return " ".join(text.strip() for text in texts if text.strip()).strip()


def _load_bound_audio(manifest_path: Path, audio_override: Path | None) -> tuple[dict, Path, str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest root must be an object: {manifest_path}")

    expected_hash = str(payload.get("audio_sha256") or "").strip().lower()
    if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
        raise ValueError(f"Manifest must contain a valid audio_sha256: {manifest_path}")

    if audio_override is None:
        audio_value = str(payload.get("audio_file") or "").strip()
        if not audio_value:
            raise ValueError(f"Manifest must contain audio_file when --audio is not supplied: {manifest_path}")
        candidate = Path(audio_value).expanduser()
        audio_path = candidate if candidate.is_absolute() else manifest_path.parent / candidate
    else:
        audio_path = audio_override.expanduser()
    audio_path = audio_path.resolve()
    if not audio_path.is_file():
        raise ValueError(f"Audio file does not exist: {audio_path}")

    actual_hash = sha256_file(audio_path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"Audio SHA-256 mismatch for {audio_path}: expected {expected_hash}, got {actual_hash}"
        )

    turns = payload.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"Manifest has no non-empty turns list: {manifest_path}")
    return payload, audio_path, actual_hash


def _turn_bounds(turn: dict, index: int, sample_rate: int, sample_count: int) -> tuple[float, float, int, int]:
    if not isinstance(turn, dict):
        raise ValueError(f"Turn {index} must be an object")
    try:
        start_seconds = float(turn["start_seconds"])
        end_seconds = float(turn["end_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Turn {index} must contain numeric start_seconds/end_seconds") from exc
    if not math.isfinite(start_seconds) or not math.isfinite(end_seconds):
        raise ValueError(f"Turn {index} contains non-finite boundaries")
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError(f"Turn {index} has invalid boundaries: {start_seconds}..{end_seconds}")

    start_sample = int(round(start_seconds * sample_rate))
    end_sample = int(round(end_seconds * sample_rate))
    if start_sample < 0 or end_sample <= start_sample or end_sample > sample_count:
        duration = sample_count / sample_rate
        raise ValueError(
            f"Turn {index} boundaries fall outside audio duration {duration:.6f}s: "
            f"{start_seconds}..{end_seconds}"
        )
    return start_seconds, end_seconds, start_sample, end_sample


def run_benchmark(
    manifest: str | Path,
    *,
    audio: str | Path | None = None,
    language: str | None = None,
    engine=None,
    timer: Timer = time.perf_counter,
) -> dict:
    manifest_path = Path(manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f"Manifest does not exist: {manifest_path}")
    audio_override = Path(audio) if audio is not None else None
    payload, audio_path, audio_hash = _load_bound_audio(manifest_path, audio_override)

    source_audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
    if source_audio.ndim != 1:
        raise ValueError(f"Oracle benchmark requires mono audio, got {source_audio.ndim} dimensions")
    if sample_rate != cfg.SAMPLE_RATE:
        raise ValueError(f"Expected {cfg.SAMPLE_RATE} Hz audio, got {sample_rate}")
    source_audio = np.asarray(source_audio, dtype=np.float32)

    recognizer = engine if engine is not None else WhisperEngine.get()
    load_start = timer()
    recognizer.load()
    model_load_seconds = timer() - load_start

    fixed_language = language.strip().lower() if language and language.strip() else None
    turn_results = []
    word_count_results: list[EditCounts] = []
    character_count_results: list[EditCounts] = []
    total_inference_seconds = 0.0
    total_segment_seconds = 0.0

    for index, turn in enumerate(payload["turns"], start=1):
        start_seconds, end_seconds, start_sample, end_sample = _turn_bounds(
            turn, index, sample_rate, len(source_audio)
        )
        reference = str(turn.get("text") or "").strip()
        if not reference:
            raise ValueError(f"Turn {index} has empty reference text")

        segment_audio = source_audio[start_sample:end_sample].copy()
        inference_start = timer()
        segments = recognizer.transcribe(segment_audio, language=fixed_language)
        inference_seconds = timer() - inference_start
        hypothesis = _transcript_text(segments)
        word_counts = word_errors(reference, hypothesis)
        character_counts = character_errors(reference, hypothesis)
        duration_seconds = len(segment_audio) / sample_rate
        total_inference_seconds += inference_seconds
        total_segment_seconds += duration_seconds
        word_count_results.append(word_counts)
        character_count_results.append(character_counts)

        turn_results.append({
            "turn": turn.get("turn", index),
            "speaker": turn.get("speaker"),
            "reference_language": turn.get("language"),
            "requested_language": fixed_language or "auto",
            "language_used": str(getattr(recognizer, "last_language", "") or ""),
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "start_sample": start_sample,
            "end_sample": end_sample,
            "audio_samples": len(segment_audio),
            "audio_seconds": duration_seconds,
            "inference_seconds": inference_seconds,
            "real_time_factor": inference_seconds / duration_seconds,
            "reference": reference,
            "hypothesis": hypothesis,
            "word_errors": _counts_dict(word_counts),
            "character_errors": _counts_dict(character_counts),
        })

    status = recognizer.status() if hasattr(recognizer, "status") else {}
    report = {
        "benchmark": "oracle-reference-turns",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "audio": str(audio_path),
        "audio_sha256": audio_hash,
        "audio_binding_verified": True,
        "sample_rate": sample_rate,
        "source_duration_seconds": len(source_audio) / sample_rate,
        "turns": len(turn_results),
        "language_mode": fixed_language or "auto",
        "languages_used": sorted({turn["language_used"] for turn in turn_results if turn["language_used"]}),
        "model": status,
        "model_load_seconds": model_load_seconds,
        "total_oracle_audio_seconds": total_segment_seconds,
        "total_inference_seconds": total_inference_seconds,
        "real_time_factor": total_inference_seconds / total_segment_seconds,
        "word_errors": _sum_counts(word_count_results),
        "character_errors": _sum_counts(character_count_results),
        "word_error_rate": _sum_counts(word_count_results)["rate"],
        "character_error_rate": _sum_counts(character_count_results)["rate"],
        "turn_results": turn_results,
    }
    return report


def main(argv: list[str] | None = None, *, engine=None) -> dict:
    parser = argparse.ArgumentParser(
        description="Benchmark Whisper on hash-bound oracle reference turns without capture, VAD, or stabilization."
    )
    parser.add_argument("manifest", type=Path, help="Hash-bound turn manifest")
    parser.add_argument("--audio", type=Path, help="Override manifest audio_file; hash must still match")
    parser.add_argument("--language", help="Force one language for every oracle turn (default: engine auto mode)")
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path")
    args = parser.parse_args(argv)

    report = run_benchmark(
        args.manifest,
        audio=args.audio,
        language=args.language,
        engine=engine,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return report


if __name__ == "__main__":
    main()
