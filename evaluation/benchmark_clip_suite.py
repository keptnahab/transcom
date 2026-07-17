#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
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
from evaluation.metrics import EditCounts, character_errors, semantic_word_errors, word_errors


Timer = Callable[[], float]
GROUP_FIELDS = ("length_bucket", "gender", "official_split", "profile", "voice", "role")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _transcript_text(segments: list) -> str:
    if not segments:
        return ""
    texts = [str(getattr(segment, "text", "") or "") for segment in segments]
    if all(bool(getattr(segment, "is_word", False)) for segment in segments):
        return "".join(texts).strip()
    return " ".join(text.strip() for text in texts if text.strip()).strip()


def _raw_transcript_text(segments: list) -> str:
    if not segments:
        return ""
    if any(getattr(segment, "raw_text", None) is None for segment in segments):
        raise ValueError("Recognizer segment missing pre-normalization raw_text")
    texts = [str(segment.raw_text or "") for segment in segments]
    if all(bool(getattr(segment, "is_word", False)) for segment in segments):
        return "".join(texts).strip()
    return " ".join(text.strip() for text in texts if text.strip()).strip()


def _valid_hash(value: object) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Clip must contain a valid sha256")
    return digest


def _safe_data_path(value: object, project_root: Path, base_dir: Path | None = None) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Clip must contain data_path")
    relative = Path(text)
    if relative.is_absolute():
        raise ValueError(f"Clip data_path must be project-relative: {text}")
    root = project_root.resolve()
    candidate = ((base_dir or root) / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Clip data_path escapes project root: {text}") from exc
    if not candidate.is_file():
        raise ValueError(f"Clip audio file does not exist: {candidate}")
    return candidate


def _validate_manifest(manifest_path: Path, project_root: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest root must be an object: {manifest_path}")
    if payload.get("scoring_authorized") is False:
        raise ValueError(
            "Manifest forbids ASR scoring until its manual audio review has fully passed"
        )
    clips = payload.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError(f"Manifest has no non-empty clips list: {manifest_path}")

    validated = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            raise ValueError(f"Clip {index} must be an object")
        nested_reference = clip.get("reference") if isinstance(clip.get("reference"), dict) else {}
        reference = str(clip.get("reference_text") or nested_reference.get("reference_text") or "").strip()
        if not reference:
            raise ValueError(f"Clip {index} has empty reference_text")
        expected_hash = _valid_hash(clip.get("sha256"))
        raw_path = clip.get("data_path")
        path_base = None
        if not str(raw_path or "").strip():
            raw_path = clip.get("path")
            path_base = manifest_path.parent
        audio_path = _safe_data_path(raw_path, project_root, base_dir=path_base)
        actual_hash = sha256_file(audio_path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Clip {index} SHA-256 mismatch for {audio_path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        info = sf.info(audio_path)
        if info.channels != 1:
            raise ValueError(f"Clip {index} must be mono, got {info.channels} channels: {audio_path}")
        if info.samplerate != cfg.SAMPLE_RATE:
            raise ValueError(
                f"Clip {index} must be {cfg.SAMPLE_RATE} Hz, got {info.samplerate} Hz: {audio_path}"
            )
        if info.frames <= 0:
            raise ValueError(f"Clip {index} contains no audio frames: {audio_path}")
        validated.append({
            "manifest_clip": clip,
            "reference_text": reference,
            "reference_status": clip.get("reference_status") or nested_reference.get("reference_status"),
            "report_data_path": str(audio_path.relative_to(project_root.resolve())),
            "audio_path": audio_path,
            "audio_sha256": actual_hash,
            "frames": int(info.frames),
            "duration_seconds": float(info.frames / info.samplerate),
        })
    return payload, validated


def _sum_counts(items: list[EditCounts]) -> dict:
    substitutions = sum(item.substitutions for item in items)
    deletions = sum(item.deletions for item in items)
    insertions = sum(item.insertions for item in items)
    reference_length = sum(item.reference_length for item in items)
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


def _counts_dict(item: EditCounts) -> dict:
    return {
        "substitutions": item.substitutions,
        "deletions": item.deletions,
        "insertions": item.insertions,
        "errors": item.errors,
        "reference_length": item.reference_length,
        "rate": item.rate,
    }


def _aggregate(results: list[dict]) -> dict:
    word_micro = _sum_counts([result["_word_counts"] for result in results])
    character_micro = _sum_counts([result["_character_counts"] for result in results])
    semantic_word_micro = _sum_counts([result["_semantic_word_counts"] for result in results])
    canonical_word_micro = _sum_counts([result["_canonical_word_counts"] for result in results])
    canonical_character_micro = _sum_counts(
        [result["_canonical_character_counts"] for result in results]
    )
    total_audio = sum(result["audio_seconds"] for result in results)
    total_inference = sum(result["inference_seconds"] for result in results)
    command_results = [
        result for result in results if result.get("expected_command_id") is not None
    ]
    command_exact = sum(
        result.get("detected_command_id") == result.get("expected_command_id")
        for result in command_results
    )
    return {
        "clip_count": len(results),
        "micro": {
            "word_error_rate": word_micro["rate"],
            "character_error_rate": character_micro["rate"],
            "word_errors": word_micro,
            "character_errors": character_micro,
            "semantic_word_error_rate": semantic_word_micro["rate"],
            "semantic_word_errors": semantic_word_micro,
        },
        "canonical_micro": {
            "word_error_rate": canonical_word_micro["rate"],
            "character_error_rate": canonical_character_micro["rate"],
            "word_errors": canonical_word_micro,
            "character_errors": canonical_character_micro,
        },
        "macro": {
            "word_error_rate": sum(result["word_error_rate"] for result in results) / len(results),
            "character_error_rate": sum(result["character_error_rate"] for result in results) / len(results),
        },
        "total_audio_seconds": total_audio,
        "total_inference_seconds": total_inference,
        "real_time_factor": total_inference / total_audio,
        "command_id_exact": {
            "correct": command_exact,
            "total": len(command_results),
            "accuracy": command_exact / len(command_results) if command_results else None,
        },
    }


def _group_results(results: list[dict]) -> dict:
    grouped = {}
    for field in GROUP_FIELDS:
        values: dict[str, list[dict]] = {}
        for result in results:
            key = str(result.get(field) or "unknown")
            values.setdefault(key, []).append(result)
        grouped[field] = {key: _aggregate(items) for key, items in sorted(values.items())}
    categories: dict[str, list[dict]] = {}
    for result in results:
        for category in result.get("categories") or []:
            categories.setdefault(str(category), []).append(result)
    grouped["category"] = {key: _aggregate(items) for key, items in sorted(categories.items())}
    return grouped


def run_benchmark(
    manifest: str | Path,
    *,
    language: str | None = None,
    engine=None,
    project_root: str | Path = PROJECT_ROOT,
    timer: Timer = time.perf_counter,
) -> dict:
    manifest_path = Path(manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f"Manifest does not exist: {manifest_path}")
    root = Path(project_root).expanduser().resolve()

    # Validate every path, hash, channel count, and sample rate before even
    # constructing/loading the recognizer. A late invalid clip must not produce
    # a partial benchmark or spend model resources.
    payload, validated_clips = _validate_manifest(manifest_path, root)

    recognizer = engine if engine is not None else WhisperEngine.get()
    load_start = timer()
    recognizer.load()
    model_load_seconds = timer() - load_start
    fixed_language = language.strip().lower() if language and language.strip() else None

    internal_results = []
    for index, validated in enumerate(validated_clips, start=1):
        clip = validated["manifest_clip"]
        audio, sample_rate = sf.read(validated["audio_path"], dtype="float32", always_2d=False)
        if audio.ndim != 1 or sample_rate != cfg.SAMPLE_RATE:
            raise ValueError(f"Clip changed after validation: {validated['audio_path']}")
        audio = np.asarray(audio, dtype=np.float32)
        inference_start = timer()
        segments = recognizer.transcribe(audio, language=fixed_language)
        inference_seconds = timer() - inference_start
        hypothesis = _transcript_text(segments)
        raw_hypothesis = _raw_transcript_text(segments)
        detected_command_ids = sorted({
            str(getattr(segment, "safety_command_id", "") or "").strip()
            for segment in segments
            if str(getattr(segment, "safety_command_id", "") or "").strip()
        })
        match_scores = [
            float(getattr(segment, "safety_match_score"))
            for segment in segments
            if getattr(segment, "safety_match_score", None) is not None
        ]
        match_margins = [
            float(getattr(segment, "safety_match_margin"))
            for segment in segments
            if getattr(segment, "safety_match_margin", None) is not None
        ]
        rejection_reasons = sorted({
            str(getattr(segment, "safety_rejection_reason", "") or "")
            for segment in segments
            if str(getattr(segment, "safety_rejection_reason", "") or "")
        })
        confirmation_raw_texts = sorted({
            str(getattr(segment, "safety_confirmation_raw_text", "") or "").strip()
            for segment in segments
            if str(getattr(segment, "safety_confirmation_raw_text", "") or "").strip()
        })
        confirmation_models = sorted({
            str(getattr(segment, "safety_confirmation_model", "") or "").strip()
            for segment in segments
            if str(getattr(segment, "safety_confirmation_model", "") or "").strip()
        })
        confidences = [
            float(segment.confidence)
            for segment in segments
            if getattr(segment, "confidence", None) is not None
        ]
        reference = validated["reference_text"]
        word_counts = word_errors(reference, raw_hypothesis)
        character_counts = character_errors(reference, raw_hypothesis)
        semantic_counts = semantic_word_errors(reference, raw_hypothesis)
        canonical_word_counts = word_errors(reference, hypothesis)
        canonical_character_counts = character_errors(reference, hypothesis)
        audio_seconds = len(audio) / sample_rate
        internal_results.append({
            "clip_index": index,
            "audio_id": clip.get("audio_id", clip.get("derived_clip_id", index)),
            "data_path": validated["report_data_path"],
            "audio_sha256": validated["audio_sha256"],
            "speaker_id": clip.get("speaker_id"),
            "length_bucket": clip.get("length_bucket"),
            "gender": clip.get("gender"),
            "official_split": clip.get("official_split", payload.get("official_split")),
            "profile": clip.get("profile"),
            "voice": clip.get("voice"),
            "role": clip.get("role"),
            "categories": list(clip.get("categories") or []),
            "reference_status": validated["reference_status"],
            "requested_language": fixed_language or "auto",
            "language_used": str(getattr(recognizer, "last_language", "") or ""),
            "audio_samples": len(audio),
            "audio_seconds": audio_seconds,
            "inference_seconds": inference_seconds,
            "real_time_factor": inference_seconds / audio_seconds,
            "reference": reference,
            "hypothesis": hypothesis,
            "raw_hypothesis": raw_hypothesis,
            "expected_command_id": clip.get("expected_command_id") or clip.get("command_id"),
            "detected_command_id": detected_command_ids[0] if len(detected_command_ids) == 1 else None,
            "detected_command_ids": detected_command_ids,
            "safety_match_score": max(match_scores) if match_scores else None,
            "safety_match_margin": min(match_margins) if match_margins else None,
            "safety_rejection_reasons": rejection_reasons,
            "safety_confirmation_raw_texts": confirmation_raw_texts,
            "safety_confirmation_models": confirmation_models,
            "safety_confirmation_used": any(
                bool(getattr(segment, "safety_confirmation_used", False)) for segment in segments
            ),
            "mean_asr_confidence": (
                sum(confidences) / len(confidences) if confidences else None
            ),
            "minimum_asr_confidence": min(confidences) if confidences else None,
            "requires_confirmation": any(
                bool(getattr(segment, "requires_confirmation", False)) for segment in segments
            ),
            "word_error_rate": word_counts.rate,
            "character_error_rate": character_counts.rate,
            "semantic_word_error_rate": semantic_counts.rate,
            "canonical_word_error_rate": canonical_word_counts.rate,
            "canonical_character_error_rate": canonical_character_counts.rate,
            "word_errors": _counts_dict(word_counts),
            "character_errors": _counts_dict(character_counts),
            "_word_counts": word_counts,
            "_character_counts": character_counts,
            "_semantic_word_counts": semantic_counts,
            "_canonical_word_counts": canonical_word_counts,
            "_canonical_character_counts": canonical_character_counts,
        })

    aggregate = _aggregate(internal_results)
    groups = _group_results(internal_results)
    clip_results = [
        {key: value for key, value in result.items() if not key.startswith("_")}
        for result in internal_results
    ]
    status = recognizer.status() if hasattr(recognizer, "status") else {}
    return {
        "benchmark": "hash-bound-clip-suite",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "project_root": str(root),
        "dataset_id": payload.get("dataset_id"),
        "dataset_name": payload.get("dataset_name"),
        "manifest_language": payload.get("language"),
        "language_mode": fixed_language or "auto",
        "languages_used": sorted({result["language_used"] for result in clip_results if result["language_used"]}),
        "all_clip_hashes_verified": True,
        "model": status,
        "recognition_config": {
            "initial_prompt": cfg.WHISPER_INITIAL_PROMPT,
            "hotwords": cfg.WHISPER_HOTWORDS,
            "german_spoken_number_normalization": cfg.GERMAN_SPOKEN_NUMBER_NORMALIZATION,
            "confirm_short_seconds": cfg.ASR_CONFIRM_SHORT_SECONDS,
            "edge_padding_seconds": cfg.ASR_EDGE_PADDING_SECONDS,
            "edge_padding_max_seconds": cfg.ASR_EDGE_PADDING_MAX_SECONDS,
            "domain_glossary_terms": list(cfg.DOMAIN_GLOSSARY_TERMS),
            "safety_command_mode": cfg.SAFETY_COMMAND_MODE,
            "safety_command_catalog": cfg.SAFETY_COMMAND_CATALOG,
            "safety_command_min_score": cfg.SAFETY_COMMAND_MIN_SCORE,
            "safety_command_min_margin": cfg.SAFETY_COMMAND_MIN_MARGIN,
            "beam_size": cfg.WHISPER_BEAM_SIZE,
            "no_speech_threshold": cfg.WHISPER_NO_SPEECH_THRESHOLD,
            "language_switch_min_probability": cfg.WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY,
            "language_stickiness_ratio": cfg.WHISPER_LANGUAGE_STICKINESS_RATIO,
            "language_switch_margin": cfg.WHISPER_LANGUAGE_SWITCH_MARGIN,
        },
        "model_load_seconds": model_load_seconds,
        **aggregate,
        "groups": groups,
        "clip_results": clip_results,
    }


def main(argv: list[str] | None = None, *, engine=None) -> dict:
    parser = argparse.ArgumentParser(
        description="Benchmark Whisper directly on a hash-bound manifest clip suite."
    )
    parser.add_argument("manifest", type=Path, help="Manifest containing a non-empty clips list")
    parser.add_argument("--language", help="Force one language for every clip (default: engine auto mode)")
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path")
    args = parser.parse_args(argv)

    report = run_benchmark(args.manifest, language=args.language, engine=engine)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return report


if __name__ == "__main__":
    main()
