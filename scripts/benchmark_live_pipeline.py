#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
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


EXPECTED_TRANSCRIPT = (
    "Hallo Regie, dies ist Anna auf Kanal eins. "
    "Wir testen jetzt die lokale Transkription mit einem gemischten Intercom Signal. "
    "Copy that. This is Daniel from stage management. "
    "The next cue is in ten seconds, please stand by. "
    "Danke. Bitte pruefen, ob der Sprecherwechsel im Transkript sichtbar bleibt. "
    "Confirmed. The offline viewer should show timestamps, speaker names, and the current text."
)


def normalize_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref_words = normalize_text(reference).split()
    hyp_words = normalize_text(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    previous = list(range(len(hyp_words) + 1))
    for i, ref_word in enumerate(ref_words, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp_words, start=1):
            substitution = previous[j - 1] + (0 if ref_word == hyp_word else 1)
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1] / len(ref_words)


def char_similarity(reference: str, hypothesis: str) -> float:
    return difflib.SequenceMatcher(
        a=normalize_text(reference),
        b=normalize_text(hypothesis),
        autojunk=False,
    ).ratio()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="?", default=str(cfg.PROJECT_ROOT / "fixtures" / "audio" / "intercom_test_feed.wav"))
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()

    audio, sr = sf.read(args.audio, dtype="float32", always_2d=False)
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
    overlap_size = int(cfg.OVERLAP_SECONDS * cfg.SAMPLE_RATE)
    ring = RingBuffer(cfg.SAMPLE_RATE * 30, chunk_size, overlap_size)
    jobs = []
    first_emit_at = None

    block_size = int(0.1 * cfg.SAMPLE_RATE)
    live_sample = 0
    for offset in range(0, len(audio), block_size):
        block = audio[offset : offset + block_size]
        ring.write(block)
        live_sample += len(block)
        while True:
            chunk = ring.next_chunk()
            if chunk is None:
                break
            live_time = live_sample / cfg.SAMPLE_RATE
            for speech in segmenter.segment(chunk):
                context_prefix_seconds = max(0.0, len(speech.audio) / cfg.SAMPLE_RATE - cfg.CHUNK_SECONDS)
                speaker_audio = speech.audio[int(context_prefix_seconds * cfg.SAMPLE_RATE) :]
                if len(speaker_audio) < int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE):
                    speaker_audio = speech.audio
                speaker = speaker_service.match_audio(speaker_audio)
                start = time.perf_counter()
                segments = engine.transcribe(speech.audio)
                infer_seconds = time.perf_counter() - start
                emitted = []
                word_segments = [seg for seg in segments if getattr(seg, "is_word", False)]
                window_start_ts = live_time - len(speech.audio) / cfg.SAMPLE_RATE
                if word_segments and len(word_segments) == len(segments):
                    accepted = timed_stabilizer.accept(
                        "bench",
                        word_segments,
                        window_start_ts=window_start_ts,
                        stable_until_ts=live_time - cfg.TRANSCRIPT_STABLE_TAIL_SECONDS,
                    )
                    if accepted is not None and accepted.text:
                        emitted.append((accepted, accepted.text))
                else:
                    for seg in segments:
                        text = stabilizer.accept("bench", seg.text)
                        if text:
                            emitted.append((seg, text))
                jobs.append({
                    "live_time": live_time,
                    "audio_seconds": len(speech.audio) / cfg.SAMPLE_RATE,
                    "context_prefix_seconds": context_prefix_seconds,
                    "infer_seconds": infer_seconds,
                    "language": engine.last_language,
                    "speaker": speaker.speaker_name,
                    "texts": [text for _seg, text in emitted],
                })
                if emitted and first_emit_at is None:
                    first_emit_at = live_time + infer_seconds
                for seg, text in emitted:
                    store.add_segment(
                        channel_id="bench",
                        text=text,
                        timestamp=seg.start if isinstance(seg, TimedText) else window_start_ts + seg.start,
                        confidence=seg.confidence,
                        speaker_id=speaker.speaker_id,
                        speaker_name=speaker.speaker_name,
                        speaker_color=speaker.speaker_color,
                        speaker_confidence=speaker.confidence,
                    )

    infer = [job["infer_seconds"] for job in jobs]
    stored = store.get_all()
    transcript_text = " ".join(seg["text"] for seg in stored)
    recognized_text_count = sum(len(job["texts"]) for job in jobs)
    duplicate_replacements = recognized_text_count - len(stored)
    speaker_counts = {}
    for job in jobs:
        speaker_counts[job["speaker"]] = speaker_counts.get(job["speaker"], 0) + 1
    result = {
        "audio": str(Path(args.audio).resolve()),
        "duration_seconds": source_duration_seconds,
        "chunk_seconds": cfg.CHUNK_SECONDS,
        "overlap_seconds": cfg.OVERLAP_SECONDS,
        "language": cfg.WHISPER_LANGUAGE,
        "languages_used": sorted({job["language"] for job in jobs}),
        "jobs": len(jobs),
        "stored_segments": len(stored),
        "duplicate_replacements": duplicate_replacements,
        "word_error_rate": word_error_rate(EXPECTED_TRANSCRIPT, transcript_text),
        "char_similarity": char_similarity(EXPECTED_TRANSCRIPT, transcript_text),
        "speaker_counts": speaker_counts,
        "speaker_status": speaker_service.status(),
        "first_emit_seconds": first_emit_at,
        "avg_infer_seconds": statistics.mean(infer) if infer else 0,
        "max_infer_seconds": max(infer) if infer else 0,
        "texts": [seg["text"] for seg in stored],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    store.close()


if __name__ == "__main__":
    main()
