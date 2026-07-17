#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from backend.audio.capture import ChannelCapture
from backend.audio.segmentation import SpeechSegmenter
from backend.transcription.engine import WhisperEngine
from evaluation.metrics import EditCounts, character_errors, normalize_text, word_errors


Timer = Callable[[], float]


@dataclass
class _Job:
    audio: np.ndarray
    available_at: float
    vad_processing_seconds: float
    speech_start: float
    speech_end: float
    speech_id: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_project_path(value: object, root: Path, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing {label}")
    relative = Path(text)
    if relative.is_absolute():
        raise ValueError(f"{label} must be project-relative: {text}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes project root: {text}") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} does not exist: {candidate}")
    return candidate


def _valid_hash(value: object, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} must be a valid SHA-256")
    return digest


def _validate_fixture(manifest_path: Path, root: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("split") not in {"dev", "holdout"}:
        raise ValueError("Streaming latency fixture must be an explicit dev or holdout manifest")
    split = str(payload["split"])
    if split == "holdout":
        if payload.get("is_holdout") is not True:
            raise ValueError("Streaming latency holdout fixture must set is_holdout=true")
        seal = payload.get("source_holdout_seal")
        if not isinstance(seal, dict):
            raise ValueError("Streaming latency holdout fixture must bind a source holdout seal")
        seal_path = _safe_project_path(
            seal.get("path"), root, "source_holdout_seal path"
        )
        expected_seal_hash = _valid_hash(
            seal.get("sha256"), "source_holdout_seal sha256"
        )
        actual_seal_hash = sha256_file(seal_path)
        if actual_seal_hash != expected_seal_hash:
            raise ValueError(
                "Source holdout seal SHA-256 mismatch: "
                f"expected {expected_seal_hash}, got {actual_seal_hash}"
            )
    elif payload.get("is_holdout") not in {None, False}:
        raise ValueError("Streaming latency dev fixture cannot set is_holdout=true")

    source_path = _safe_project_path(payload.get("source_manifest"), root, "source_manifest")
    expected_source_hash = _valid_hash(payload.get("source_manifest_sha256"), "source_manifest_sha256")
    actual_source_hash = sha256_file(source_path)
    if actual_source_hash != expected_source_hash:
        raise ValueError(
            f"Source manifest SHA-256 mismatch: expected {expected_source_hash}, got {actual_source_hash}"
        )
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source_payload, dict):
        raise ValueError("Source manifest root must be an object")
    source_references: dict[str, tuple[str, str | None]] = {}
    source_clips = source_payload.get("clips") or source_payload.get("utterances") or []
    for source_clip in source_clips:
        if not isinstance(source_clip, dict):
            continue
        source_id = str(
            source_clip.get("audio_id")
            or source_clip.get("derived_clip_id")
            or source_clip.get("clip_id")
            or source_clip.get("id")
            or ""
        ).strip()
        nested_reference = (
            source_clip.get("reference")
            if isinstance(source_clip.get("reference"), dict)
            else {}
        )
        source_reference = str(
            source_clip.get("reference_text")
            or nested_reference.get("reference_text")
            or source_clip.get("text")
            or ""
        ).strip()
        source_status = source_clip.get("reference_status") or nested_reference.get(
            "reference_status"
        )
        if source_id and source_reference:
            source_references[source_id] = (source_reference, source_status)

    clips = payload.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("Streaming latency fixture must contain a non-empty clips list")
    validated = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            raise ValueError(f"Clip {index} must be an object")
        clip_id = str(
            clip.get("id")
            or clip.get("audio_id")
            or clip.get("derived_clip_id")
            or clip.get("clip_id")
            or ""
        ).strip()
        nested_reference = (
            clip.get("reference") if isinstance(clip.get("reference"), dict) else {}
        )
        reference = str(
            clip.get("reference_text") or nested_reference.get("reference_text") or ""
        ).strip()
        if not reference:
            raise ValueError(f"Clip {index} has empty reference_text")
        reference_status = clip.get("reference_status") or nested_reference.get(
            "reference_status"
        )
        source_reference = source_references.get(clip_id)
        if source_reference is not None:
            source_text, source_status = source_reference
            if source_text != reference:
                raise ValueError(f"Clip {index} reference_text differs from hash-bound source")
            if (
                reference_status is not None
                and source_status is not None
                and source_status != reference_status
            ):
                raise ValueError(
                    f"Clip {index} reference_status differs from hash-bound source"
                )
            if source_status is not None:
                reference_status = source_status
        path = _safe_project_path(clip.get("data_path"), root, f"clip {index} data_path")
        expected_hash = _valid_hash(clip.get("sha256"), f"clip {index} sha256")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Clip {index} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
            )
        info = sf.info(path)
        if info.channels != 1 or info.samplerate != cfg.SAMPLE_RATE:
            raise ValueError(
                f"Clip {index} must be mono {cfg.SAMPLE_RATE} Hz, got "
                f"{info.channels}ch {info.samplerate} Hz"
            )
        speech_end = float(clip.get("speech_end_seconds", info.frames / info.samplerate))
        duration = info.frames / info.samplerate
        if speech_end <= 0 or speech_end > duration + (1 / info.samplerate):
            raise ValueError(f"Clip {index} has invalid speech_end_seconds: {speech_end}")
        validated.append({
            "clip": clip,
            "reference_status": (
                str(reference_status).strip() if reference_status is not None else None
            ),
            "path": path,
            "sha256": actual_hash,
            "frames": int(info.frames),
            "duration": duration,
            "speech_end": speech_end,
        })
    return payload, validated


def _reviewed_reference_status(value: object) -> bool:
    status = str(value or "").strip().lower().replace("-", "_")
    if not status or "reviewed" not in status:
        return False
    tokens = set(status.split("_"))
    return not (
        tokens
        & {
            "not",
            "un",
            "unreviewed",
            "never",
            "pending",
            "unchecked",
            "unverified",
            "false",
        }
    ) and not any(
        marker in status
        for marker in ("notreviewed", "not_reviewed", "not_manually_reviewed")
    )


def _require_reviewed_scoring_references(validated_clips: list[dict]) -> None:
    failures = [
        {
            "index": index,
            "clip_id": validated["clip"].get("id"),
            "reference_status": validated.get("reference_status"),
        }
        for index, validated in enumerate(validated_clips, start=1)
        if not _reviewed_reference_status(validated.get("reference_status"))
    ]
    if failures:
        raise ValueError(
            "Streaming latency scoring requires reviewed reference provenance; "
            f"first invalid clip: {failures[0]}"
        )


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


def _run_clip(
    validated: dict,
    recognizer,
    *,
    language: str | None,
    timer: Timer,
    segmenter_factory: Callable[[], object],
) -> dict:
    audio, sample_rate = sf.read(validated["path"], dtype="float32", always_2d=False)
    if audio.ndim != 1 or sample_rate != cfg.SAMPLE_RATE:
        raise ValueError(f"Clip changed after validation: {validated['path']}")
    audio = np.asarray(audio, dtype=np.float32)
    segmenter = segmenter_factory()
    jobs: list[_Job] = []
    available_samples = 0
    capture_worker_available_at = 0.0

    def collect_segment(segment, available_at: float, vad_processing_seconds: float) -> None:
        jobs.append(_Job(
            audio=np.asarray(segment.audio, dtype=np.float32).copy(),
            available_at=available_at,
            vad_processing_seconds=vad_processing_seconds,
            speech_start=float(getattr(segment, "stream_start", 0.0)),
            speech_end=float(getattr(segment, "stream_end", 0.0)),
            speech_id=getattr(segment, "speech_id", None),
        ))

    def on_chunk(_channel_id: str, chunk: np.ndarray, _wall_ts: float) -> None:
        nonlocal capture_worker_available_at
        logical_available_at = available_samples / sample_rate
        vad_start = timer()
        segments = segmenter.segment(chunk)
        vad_processing_seconds = timer() - vad_start
        available_at = max(logical_available_at, capture_worker_available_at) + vad_processing_seconds
        capture_worker_available_at = available_at
        for segment in segments:
            collect_segment(segment, available_at, vad_processing_seconds)

    capture = ChannelCapture("latency-benchmark", 0, on_chunk)
    flush_seconds = cfg.CHUNK_SECONDS + max(cfg.OVERLAP_SECONDS, cfg.VAD_MIN_SILENCE_SECONDS)
    simulated_stream = np.concatenate([
        audio,
        np.zeros(int(round(flush_seconds * sample_rate)), dtype=np.float32),
    ])
    block_size = cfg.CAPTURE_BLOCK_SIZE
    for offset in range(0, len(simulated_stream), block_size):
        block = simulated_stream[offset : offset + block_size]
        available_samples += len(block)
        capture._process_frames(block)
    logical_flush_at = available_samples / sample_rate
    vad_start = timer()
    flushed_segments = segmenter.flush()
    vad_processing_seconds = timer() - vad_start
    flush_available_at = max(logical_flush_at, capture_worker_available_at) + vad_processing_seconds
    for segment in flushed_segments:
        collect_segment(segment, flush_available_at, vad_processing_seconds)

    worker_available_at = 0.0
    first_usable_emit = None
    total_inference = 0.0
    hypotheses = []
    raw_hypotheses = []
    job_results = []
    for job in jobs:
        inference_start = timer()
        segments = recognizer.transcribe(job.audio, language=language)
        inference_seconds = timer() - inference_start
        total_inference += inference_seconds
        hypothesis = _transcript_text(segments)
        raw_hypothesis = _raw_transcript_text(segments)
        detected_command_ids = sorted({
            str(getattr(segment, "safety_command_id", "") or "").strip()
            for segment in segments
            if str(getattr(segment, "safety_command_id", "") or "").strip()
        })
        confidences = [
            float(segment.confidence)
            for segment in segments
            if getattr(segment, "confidence", None) is not None
        ]
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
        worker_start = max(job.available_at, worker_available_at)
        emit_at = worker_start + inference_seconds
        worker_available_at = emit_at
        if normalize_text(hypothesis):
            hypotheses.append(hypothesis)
            raw_hypotheses.append(raw_hypothesis)
            if first_usable_emit is None:
                first_usable_emit = emit_at
        job_results.append({
            "speech_id": job.speech_id,
            "vad_speech_start_seconds": job.speech_start,
            "vad_speech_end_seconds": job.speech_end,
            "audio_seconds": len(job.audio) / sample_rate,
            "available_at_seconds": job.available_at,
            "vad_processing_seconds": job.vad_processing_seconds,
            "worker_start_seconds": worker_start,
            "inference_seconds": inference_seconds,
            "emit_at_seconds": emit_at,
            "hypothesis": hypothesis,
            "raw_hypothesis": raw_hypothesis,
            "detected_command_id": detected_command_ids[0] if len(detected_command_ids) == 1 else None,
            "detected_command_ids": detected_command_ids,
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
            "language_used": str(getattr(recognizer, "last_language", "") or ""),
        })

    hypothesis = " ".join(hypotheses).strip()
    raw_hypothesis = " ".join(raw_hypotheses).strip()
    detected_command_ids = sorted({
        command_id
        for job in job_results
        for command_id in job.get("detected_command_ids", [])
    })
    clip = validated["clip"]
    reference = str(clip["reference_text"]).strip()
    word_counts = word_errors(reference, raw_hypothesis)
    character_counts = character_errors(reference, raw_hypothesis)
    canonical_word_counts = word_errors(reference, hypothesis)
    canonical_character_counts = character_errors(reference, hypothesis)
    speech_end = validated["speech_end"]
    return {
        "clip_id": clip.get("id"),
        "data_path": str(clip["data_path"]),
        "audio_sha256": validated["sha256"],
        "reference": reference,
        "reference_status": validated["reference_status"],
        "hypothesis": hypothesis,
        "raw_hypothesis": raw_hypothesis,
        "expected_command_id": clip.get("expected_command_id") or clip.get("command_id"),
        "detected_command_id": detected_command_ids[0] if len(detected_command_ids) == 1 else None,
        "detected_command_ids": detected_command_ids,
        "safety_confirmation_used": any(
            bool(job.get("safety_confirmation_used")) for job in job_results
        ),
        "safety_confirmation_raw_texts": sorted({
            text
            for job in job_results
            for text in job.get("safety_confirmation_raw_texts", [])
        }),
        "safety_confirmation_models": sorted({
            model
            for job in job_results
            for model in job.get("safety_confirmation_models", [])
        }),
        "requires_confirmation": bool(job_results) and all(
            bool(job.get("requires_confirmation")) for job in job_results
        ),
        "speech_end_seconds": speech_end,
        "first_usable_emit_seconds": first_usable_emit,
        "end_to_emit_seconds": None if first_usable_emit is None else first_usable_emit - speech_end,
        "jobs": len(jobs),
        "total_inference_seconds": total_inference,
        "real_time_factor": total_inference / speech_end,
        "word_error_rate": word_counts.rate,
        "character_error_rate": character_counts.rate,
        "canonical_word_error_rate": canonical_word_counts.rate,
        "canonical_character_error_rate": canonical_character_counts.rate,
        "word_errors": _counts_dict(word_counts),
        "character_errors": _counts_dict(character_counts),
        "language_mode": language or "auto",
        "languages_used": sorted({job["language_used"] for job in job_results if job["language_used"]}),
        "job_results": job_results,
        "_word_counts": word_counts,
        "_character_counts": character_counts,
        "_canonical_word_counts": canonical_word_counts,
        "_canonical_character_counts": canonical_character_counts,
    }


def run_benchmark(
    manifest: str | Path,
    *,
    language: str | None = None,
    engine=None,
    timer: Timer = time.perf_counter,
    segmenter_factory: Callable[[], object] | None = None,
    project_root: str | Path = PROJECT_ROOT,
) -> dict:
    manifest_path = Path(manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f"Manifest does not exist: {manifest_path}")
    root = Path(project_root).expanduser().resolve()
    payload, validated_clips = _validate_fixture(manifest_path, root)
    _require_reviewed_scoring_references(validated_clips)

    recognizer = engine if engine is not None else WhisperEngine.get()
    load_start = timer()
    recognizer.load()
    model_load_seconds = timer() - load_start
    fixed_language = language.strip().lower() if language and language.strip() else None
    factory = segmenter_factory or (lambda: SpeechSegmenter(sample_rate=cfg.SAMPLE_RATE))

    internal = [
        _run_clip(
            clip,
            recognizer,
            language=fixed_language,
            timer=timer,
            segmenter_factory=factory,
        )
        for clip in validated_clips
    ]
    word_micro = _sum_counts([result["_word_counts"] for result in internal])
    character_micro = _sum_counts([result["_character_counts"] for result in internal])
    canonical_word_micro = _sum_counts([result["_canonical_word_counts"] for result in internal])
    canonical_character_micro = _sum_counts(
        [result["_canonical_character_counts"] for result in internal]
    )
    visible = [
        {key: value for key, value in result.items() if not key.startswith("_")}
        for result in internal
    ]
    emitted = [result["end_to_emit_seconds"] for result in visible if result["end_to_emit_seconds"] is not None]
    total_speech = sum(result["speech_end_seconds"] for result in visible)
    total_inference = sum(result["total_inference_seconds"] for result in visible)
    status = recognizer.status() if hasattr(recognizer, "status") else {}
    return {
        "benchmark": "simulated-realtime-short-utterance-latency",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "fixture_id": payload.get("fixture_id"),
        "source_manifest": payload.get("source_manifest"),
        "split": payload["split"],
        "all_hashes_verified": True,
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
        "language_mode": fixed_language or "auto",
        "simulation": {
            "sample_rate": cfg.SAMPLE_RATE,
            "capture_block_size": cfg.CAPTURE_BLOCK_SIZE,
            "chunk_seconds": cfg.CHUNK_SECONDS,
            "configured_overlap_seconds": cfg.OVERLAP_SECONDS,
            "vad_min_silence_seconds": cfg.VAD_MIN_SILENCE_SECONDS,
            "vad_pre_roll_seconds": cfg.VAD_CONTEXT_PRE_ROLL_SECONDS,
            "vad_post_roll_seconds": cfg.VAD_CONTEXT_POST_ROLL_SECONDS,
            "feed_mode": "logical-real-time-by-sample-availability",
            "worker_model": "single-serialized-worker",
        },
        "clips": len(visible),
        "jobs": sum(result["jobs"] for result in visible),
        "successful_first_emits": len(emitted),
        "mean_end_to_emit_seconds": sum(emitted) / len(emitted) if emitted else None,
        "max_end_to_emit_seconds": max(emitted) if emitted else None,
        "total_speech_seconds": total_speech,
        "total_inference_seconds": total_inference,
        "real_time_factor": total_inference / total_speech,
        "word_error_rate": word_micro["rate"],
        "character_error_rate": character_micro["rate"],
        "canonical_word_error_rate": canonical_word_micro["rate"],
        "canonical_character_error_rate": canonical_character_micro["rate"],
        "word_errors": word_micro,
        "character_errors": character_micro,
        "clip_results": visible,
    }


def main(argv: list[str] | None = None, *, engine=None) -> dict:
    parser = argparse.ArgumentParser(
        description="Measure simulated real-time Capture→VAD→ASR latency on hash-bound short dev clips."
    )
    parser.add_argument("manifest", type=Path, help="Hash-bound short-utterance dev fixture")
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
