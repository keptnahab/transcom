#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import backend.config as cfg
from backend.audio.ring_buffer import RingBuffer
from backend.audio.segmentation import SpeechSegmenter
from backend.speaker.service import SpeakerService
from backend.transcript.store import TranscriptStore
from backend.transcript.stabilizer import TimedText, TimedWordStabilizer, TranscriptStabilizer
from backend.transcription.engine import WhisperEngine
from evaluation.metrics import character_errors, normalize_text, semantic_word_errors, word_errors


EXPECTED_TRANSCRIPT = (
    "Hallo Regie, dies ist Anna auf Kanal eins. "
    "Wir testen jetzt die lokale Transkription mit einem gemischten Intercom Signal. "
    "Copy that. This is Daniel from stage management. "
    "The next cue is in ten seconds, please stand by. "
    "Danke. Bitte pruefen, ob der Sprecherwechsel im Transkript sichtbar bleibt. "
    "Confirmed. The offline viewer should show timestamps, speaker names, and the current text."
)
LEGACY_AUDIO_SHA256 = "a28d74c92dfc6c322eb18176034f0a2b70d4b2d8b0ffd94f375de69fe3c2fb17"


def word_error_rate(reference: str, hypothesis: str) -> float:
    return word_errors(reference, hypothesis).rate


def char_similarity(reference: str, hypothesis: str) -> float:
    return 1.0 - character_errors(reference, hypothesis).rate


def accepted_segment_text(stabilizer: TranscriptStabilizer, channel_id: str, segment) -> str:
    if getattr(segment, "safety_match_score", None) is not None:
        return str(segment.text or "").strip()
    return stabilizer.accept(channel_id, segment.text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_reference(
    audio_path: Path,
    audio_sha256: str,
    manifest_path: Path | None,
) -> tuple[str, str, bool]:
    candidate = manifest_path
    explicit_manifest = candidate is not None
    if candidate is None and audio_path.with_suffix(".json").exists():
        candidate = audio_path.with_suffix(".json")
    if candidate is None:
        if audio_sha256 != LEGACY_AUDIO_SHA256:
            raise ValueError(
                "No reference manifest is bound to this audio. Pass --reference-manifest; "
                f"audio SHA-256 is {audio_sha256}."
            )
        return EXPECTED_TRANSCRIPT, "legacy-embedded-reference", True

    payload = json.loads(candidate.read_text(encoding="utf-8"))
    expected_hash = str(payload.get("audio_sha256") or "").lower()
    if expected_hash and expected_hash != audio_sha256:
        raise ValueError(
            f"Reference manifest hash mismatch: expected {expected_hash}, got {audio_sha256}"
        )
    if not expected_hash and not explicit_manifest:
        raise ValueError(
            f"Implicit sidecar manifest must contain audio_sha256: {candidate}"
        )
    turns = payload.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"Reference manifest has no non-empty turns list: {candidate}")
    texts = [str(turn.get("text") or "").strip() for turn in turns]
    if not all(texts):
        raise ValueError(f"Reference manifest contains an empty turn text: {candidate}")
    return " ".join(texts), str(candidate.resolve()), bool(expected_hash)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="?", default=str(cfg.PROJECT_ROOT / "fixtures" / "audio" / "intercom_test_feed.wav"))
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--reference-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    audio_sha256 = sha256_file(audio_path)
    reference_text, reference_source, reference_binding_verified = load_reference(
        audio_path, audio_sha256, args.reference_manifest
    )
    audio, sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio[:, 0]
    if sr != cfg.SAMPLE_RATE:
        raise ValueError(f"Expected {cfg.SAMPLE_RATE} Hz audio, got {sr}")
    source_duration_seconds = len(audio) / cfg.SAMPLE_RATE
    flush = np.zeros(int((cfg.OVERLAP_SECONDS + cfg.CHUNK_SECONDS) * cfg.SAMPLE_RATE), dtype=np.float32)
    audio = np.concatenate([audio, flush])

    segmenter = SpeechSegmenter(sample_rate=cfg.SAMPLE_RATE)
    engine = WhisperEngine.get()
    speaker_service = SpeakerService()
    stabilizer = TranscriptStabilizer()
    timed_stabilizer = TimedWordStabilizer()
    if args.warmup:
        engine.load()
    store = TranscriptStore(db_path=args.db)

    chunk_size = int(cfg.CHUNK_SECONDS * cfg.SAMPLE_RATE)
    # Mirror ChannelCapture: the stateful VAD consumes contiguous audio once.
    # The configured legacy overlap is intentionally not used at capture time.
    capture_overlap_size = 0
    ring = RingBuffer(cfg.SAMPLE_RATE * 30, chunk_size, capture_overlap_size)
    jobs = []
    first_emit_at = None
    first_emit_simulated = None
    simulated_worker_available = 0.0
    segments_with_text = 0
    empty_segments = 0

    block_size = int(0.1 * cfg.SAMPLE_RATE)
    stream_origin_ts = 0.0
    for offset in range(0, len(audio), block_size):
        block = audio[offset : offset + block_size]
        available_at = (offset + len(block)) / cfg.SAMPLE_RATE
        ring.write(block)
        while True:
            chunk = ring.next_chunk()
            if chunk is None:
                break
            if len(chunk) > chunk_size:
                chunk = chunk[-chunk_size:]
            for speech in segmenter.segment(chunk):
                speaker = speaker_service.match_audio(speech.audio)
                start = time.perf_counter()
                segments = engine.transcribe(speech.audio)
                infer_seconds = time.perf_counter() - start
                completed_at = max(available_at, simulated_worker_available) + infer_seconds
                simulated_worker_available = completed_at
                emitted = []
                word_segments = [seg for seg in segments if getattr(seg, "is_word", False)]
                speech_start_ts = stream_origin_ts + speech.stream_start
                speech_end_ts = stream_origin_ts + speech.stream_end
                if word_segments and len(word_segments) == len(segments):
                    accepted = timed_stabilizer.accept(
                        "bench",
                        word_segments,
                        window_start_ts=speech_start_ts,
                        stable_until_ts=speech_end_ts,
                        is_final=speech.is_final,
                    )
                    if accepted is not None and accepted.text:
                        emitted.append((accepted, accepted.text))
                else:
                    for seg in segments:
                        text = accepted_segment_text(stabilizer, "bench", seg)
                        if text:
                            emitted.append((seg, text))
                jobs.append({
                    "speech_id": speech.speech_id,
                    "audio_seconds": speech.duration,
                    "infer_seconds": infer_seconds,
                    "language": engine.last_language,
                    "speaker": speaker.speaker_name,
                    "texts": [text for _seg, text in emitted],
                })
                if emitted and first_emit_at is None:
                    first_emit_at = speech_end_ts + infer_seconds
                    first_emit_simulated = completed_at
                if emitted:
                    segments_with_text += 1
                else:
                    empty_segments += 1
                for seg, text in emitted:
                    store.add_segment(
                        channel_id="bench",
                        text=text,
                        timestamp=seg.start if isinstance(seg, TimedText) else speech_start_ts + seg.start,
                        confidence=seg.confidence,
                        requires_confirmation=getattr(seg, "requires_confirmation", False),
                        raw_text=getattr(seg, "raw_text", None),
                        safety_confirmation_raw_text=getattr(seg, "safety_confirmation_raw_text", None),
                        safety_confirmation_model=getattr(seg, "safety_confirmation_model", None),
                        safety_confirmation_used=getattr(seg, "safety_confirmation_used", False),
                        safety_command_id=getattr(seg, "safety_command_id", None),
                        safety_match_score=getattr(seg, "safety_match_score", None),
                        safety_match_margin=getattr(seg, "safety_match_margin", None),
                        safety_rejection_reason=getattr(seg, "safety_rejection_reason", None),
                        safety_catalog_id=getattr(seg, "safety_catalog_id", None),
                        safety_catalog_sha256=getattr(seg, "safety_catalog_sha256", None),
                        speaker_id=speaker.speaker_id,
                        speaker_name=speaker.speaker_name,
                        speaker_color=speaker.speaker_color,
                        speaker_confidence=speaker.confidence,
                    )

    for speech in segmenter.flush():
        speaker = speaker_service.match_audio(speech.audio)
        start = time.perf_counter()
        segments = engine.transcribe(speech.audio)
        infer_seconds = time.perf_counter() - start
        available_at = len(audio) / cfg.SAMPLE_RATE
        completed_at = max(available_at, simulated_worker_available) + infer_seconds
        simulated_worker_available = completed_at
        emitted = []
        word_segments = [seg for seg in segments if getattr(seg, "is_word", False)]
        speech_start_ts = stream_origin_ts + speech.stream_start
        speech_end_ts = stream_origin_ts + speech.stream_end
        if word_segments and len(word_segments) == len(segments):
            accepted = timed_stabilizer.accept(
                "bench",
                word_segments,
                window_start_ts=speech_start_ts,
                stable_until_ts=speech_end_ts,
                is_final=speech.is_final,
            )
            if accepted is not None and accepted.text:
                emitted.append((accepted, accepted.text))
        else:
            for seg in segments:
                text = accepted_segment_text(stabilizer, "bench", seg)
                if text:
                    emitted.append((seg, text))
        jobs.append({
            "speech_id": speech.speech_id,
            "audio_seconds": speech.duration,
            "infer_seconds": infer_seconds,
            "language": engine.last_language,
            "speaker": speaker.speaker_name,
            "texts": [text for _seg, text in emitted],
        })
        if emitted and first_emit_at is None:
            first_emit_at = speech_end_ts + infer_seconds
            first_emit_simulated = completed_at
        if emitted:
            segments_with_text += 1
        else:
            empty_segments += 1
        for seg, text in emitted:
            store.add_segment(
                channel_id="bench",
                text=text,
                timestamp=seg.start if isinstance(seg, TimedText) else speech_start_ts + seg.start,
                confidence=seg.confidence,
                requires_confirmation=getattr(seg, "requires_confirmation", False),
                raw_text=getattr(seg, "raw_text", None),
                safety_confirmation_raw_text=getattr(seg, "safety_confirmation_raw_text", None),
                safety_confirmation_model=getattr(seg, "safety_confirmation_model", None),
                safety_confirmation_used=getattr(seg, "safety_confirmation_used", False),
                safety_command_id=getattr(seg, "safety_command_id", None),
                safety_match_score=getattr(seg, "safety_match_score", None),
                safety_match_margin=getattr(seg, "safety_match_margin", None),
                safety_rejection_reason=getattr(seg, "safety_rejection_reason", None),
                safety_catalog_id=getattr(seg, "safety_catalog_id", None),
                safety_catalog_sha256=getattr(seg, "safety_catalog_sha256", None),
                speaker_id=speaker.speaker_id,
                speaker_name=speaker.speaker_name,
                speaker_color=speaker.speaker_color,
                speaker_confidence=speaker.confidence,
            )

    infer = [job["infer_seconds"] for job in jobs]
    stored = store.get_all()
    transcript_text = " ".join(seg["text"] for seg in stored)
    raw_transcript_text = " ".join(seg.get("raw_text") or seg["text"] for seg in stored)
    word_counts = word_errors(reference_text, transcript_text)
    char_counts = character_errors(reference_text, transcript_text)
    semantic_counts = semantic_word_errors(reference_text, transcript_text)
    raw_word_counts = word_errors(reference_text, raw_transcript_text)
    raw_char_counts = character_errors(reference_text, raw_transcript_text)
    recognized_text_count = sum(len(job["texts"]) for job in jobs)
    duplicate_replacements = recognized_text_count - len(stored)
    speaker_counts = {}
    for job in jobs:
        speaker_counts[job["speaker"]] = speaker_counts.get(job["speaker"], 0) + 1
    result = {
        "audio": str(audio_path),
        "audio_sha256": audio_sha256,
        "reference_source": reference_source,
        "reference_binding_verified": reference_binding_verified,
        "reference_word_count": len(normalize_text(reference_text).split()),
        "duration_seconds": source_duration_seconds,
        "chunk_seconds": cfg.CHUNK_SECONDS,
        "configured_legacy_overlap_seconds": cfg.OVERLAP_SECONDS,
        "capture_overlap_seconds": capture_overlap_size / cfg.SAMPLE_RATE,
        "language": cfg.WHISPER_LANGUAGE,
        "languages_used": sorted({job["language"] for job in jobs}),
        "model": engine.status(),
        "recognition_config": {
            "initial_prompt": cfg.WHISPER_INITIAL_PROMPT,
            "hotwords": cfg.WHISPER_HOTWORDS,
            "german_spoken_number_normalization": cfg.GERMAN_SPOKEN_NUMBER_NORMALIZATION,
            "confirm_short_seconds": cfg.ASR_CONFIRM_SHORT_SECONDS,
            "beam_size": cfg.WHISPER_BEAM_SIZE,
            "no_speech_threshold": cfg.WHISPER_NO_SPEECH_THRESHOLD,
            "language_switch_min_probability": cfg.WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY,
            "language_stickiness_ratio": cfg.WHISPER_LANGUAGE_STICKINESS_RATIO,
            "language_switch_margin": cfg.WHISPER_LANGUAGE_SWITCH_MARGIN,
        },
        "segmentation_config": {
            "vad_min_speech_seconds": cfg.VAD_MIN_SPEECH_SECONDS,
            "vad_min_silence_seconds": cfg.VAD_MIN_SILENCE_SECONDS,
            "vad_max_segment_seconds": cfg.VAD_MAX_SEGMENT_SECONDS,
            "vad_threshold": cfg.VAD_THRESHOLD,
            "vad_energy_threshold": cfg.VAD_ENERGY_THRESHOLD,
            "vad_pre_roll_seconds": cfg.VAD_CONTEXT_PRE_ROLL_SECONDS,
            "vad_post_roll_seconds": cfg.VAD_CONTEXT_POST_ROLL_SECONDS,
            "asr_min_rms": cfg.ASR_MIN_RMS,
        },
        "jobs": len(jobs),
        "stored_segments": len(stored),
        "segments_with_text": segments_with_text,
        "empty_segments": empty_segments,
        "duplicate_replacements": duplicate_replacements,
        "word_error_rate": word_counts.rate,
        "character_error_rate": char_counts.rate,
        "semantic_word_error_rate": semantic_counts.rate,
        "raw_model_word_error_rate": raw_word_counts.rate,
        "raw_model_character_error_rate": raw_char_counts.rate,
        "char_similarity": 1.0 - char_counts.rate,
        "word_errors": {
            "substitutions": word_counts.substitutions,
            "deletions": word_counts.deletions,
            "insertions": word_counts.insertions,
        },
        "character_errors": {
            "substitutions": char_counts.substitutions,
            "deletions": char_counts.deletions,
            "insertions": char_counts.insertions,
        },
        "semantic_word_errors": {
            "substitutions": semantic_counts.substitutions,
            "deletions": semantic_counts.deletions,
            "insertions": semantic_counts.insertions,
        },
        "speaker_counts": speaker_counts,
        "speaker_status": speaker_service.status(),
        "first_emit_seconds": first_emit_at,
        "first_emit_simulated_seconds": first_emit_simulated,
        "avg_infer_seconds": statistics.mean(infer) if infer else 0,
        "p50_infer_seconds": statistics.median(infer) if infer else 0,
        "p95_infer_seconds": percentile(infer, 0.95),
        "max_infer_seconds": max(infer) if infer else 0,
        "total_infer_seconds": sum(infer),
        "inference_real_time_factor": sum(infer) / source_duration_seconds if source_duration_seconds else 0,
        "simulated_pipeline_complete_seconds": simulated_worker_available,
        "transcript": transcript_text,
        "raw_model_transcript": raw_transcript_text,
        "texts": [seg["text"] for seg in stored],
        "safety_events": [
            {
                "text": seg["text"],
                "raw_text": seg.get("raw_text"),
                "safety_confirmation_raw_text": seg.get("safety_confirmation_raw_text"),
                "safety_confirmation_model": seg.get("safety_confirmation_model"),
                "safety_confirmation_used": bool(seg.get("safety_confirmation_used")),
                "safety_command_id": seg.get("safety_command_id"),
                "safety_match_score": seg.get("safety_match_score"),
                "safety_match_margin": seg.get("safety_match_margin"),
                "safety_rejection_reason": seg.get("safety_rejection_reason"),
            }
            for seg in stored
            if seg.get("safety_match_score") is not None
        ],
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    store.close()


if __name__ == "__main__":
    main()
