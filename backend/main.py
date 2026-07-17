"""
TransCom backend entry point.

Wires all subsystems together and starts the WebSocket server.
Writes "READY" to stdout once the server is listening so Electron
main.js knows it can open the window.
"""
from __future__ import annotations
import asyncio
import logging
import multiprocessing
import os
from pathlib import Path
import sys

# Ensure the project root is on sys.path so `import backend.*` works
# regardless of how this script is invoked (dev.sh, Electron spawn, tests).
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
import signal
import sys

import backend.config as cfg
from backend.auth import AuthService
from backend.audio.device_scanner import list_input_devices
from backend.audio.segmentation import SpeechSegmenter
from backend.channels.channel_manager import ChannelManager
from backend.server.ws_server import WSServer
from backend.session import SessionManager
from backend.share import ShareServer
from backend.speaker import SpeakerService
from backend.speaker.enrollment import AudioEnrollmentRecorder
from backend.transcript.store import TranscriptStore
from backend.transcript.stabilizer import TimedWordStabilizer, TranscriptStabilizer
from backend.transcription.engine import WhisperEngine
from backend.transcription.worker_pool import TranscriptionPool, TranscriptionResult
from backend.web import WebAppServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _accepted_segment_text(stabilizer: TranscriptStabilizer, channel_id: str, segment) -> str:
    """Safety attempts are events; never suppress a repeated occurrence."""
    if getattr(segment, "safety_match_score", None) is not None:
        return str(segment.text or "").strip()
    return stabilizer.accept(channel_id, segment.text)


def _make_result_handler(
    store: TranscriptStore,
    server: WSServer,
    speaker_service: SpeakerService,
    stabilizer: TranscriptStabilizer,
    timed_stabilizer: TimedWordStabilizer,
    loop: asyncio.AbstractEventLoop,
):
    """Returns the callback invoked (on asyncio loop) when Whisper finishes a chunk."""
    def on_result(result: TranscriptionResult) -> None:
        word_segments = [seg for seg in result.segments if getattr(seg, "is_word", False)]
        if word_segments and len(word_segments) == len(result.segments):
            accepted = timed_stabilizer.accept(
                result.channel_id,
                word_segments,
                window_start_ts=result.speech_start_ts,
                stable_until_ts=result.speech_end_ts,
                is_final=result.is_final,
            )
            if accepted is None or not accepted.text.strip():
                return
            start_idx = max(0, int((accepted.start - result.speech_start_ts) * cfg.SAMPLE_RATE))
            end_idx = min(len(result.source_audio), int((accepted.end - result.speech_start_ts) * cfg.SAMPLE_RATE))
            speaker_audio = result.source_audio[start_idx:end_idx]
            if len(speaker_audio) < int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE):
                speaker_audio = result.source_audio
            match = speaker_service.match_audio(speaker_audio, sample_rate=cfg.SAMPLE_RATE)
            stored = store.add_segment(
                channel_id=result.channel_id,
                text=accepted.text,
                timestamp=accepted.start,
                confidence=accepted.confidence,
                requires_confirmation=accepted.requires_confirmation,
                raw_text=accepted.raw_text,
                speaker_id=match.speaker_id,
                speaker_name=match.speaker_name,
                speaker_color=match.speaker_color,
                speaker_confidence=match.confidence,
            )
            if stored:
                asyncio.run_coroutine_threadsafe(
                    server.broadcast({
                        "type": "transcript_segment",
                        "id": None,
                        "payload": stored,
                    }),
                    loop,
                )
            return

        for seg in result.segments:
            text = _accepted_segment_text(stabilizer, result.channel_id, seg)
            if not text:
                continue
            abs_ts = result.speech_start_ts + seg.start
            start_idx = max(0, int(seg.start * cfg.SAMPLE_RATE))
            end_idx = min(len(result.source_audio), int(seg.end * cfg.SAMPLE_RATE))
            speaker_audio = result.source_audio[start_idx:end_idx]
            if len(speaker_audio) < int(cfg.VAD_MIN_SPEECH_SECONDS * cfg.SAMPLE_RATE):
                speaker_audio = result.source_audio
            match = speaker_service.match_audio(speaker_audio, sample_rate=cfg.SAMPLE_RATE)
            stored = store.add_segment(
                channel_id=result.channel_id,
                text=text,
                timestamp=abs_ts,
                confidence=seg.confidence,
                requires_confirmation=seg.requires_confirmation,
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
                speaker_id=match.speaker_id,
                speaker_name=match.speaker_name,
                speaker_color=match.speaker_color,
                speaker_confidence=match.confidence,
            )
            if stored:
                asyncio.run_coroutine_threadsafe(
                    server.broadcast({
                        "type": "transcript_segment",
                        "id": None,
                        "payload": stored,
                    }),
                    loop,
                )
    return on_result


async def main() -> None:
    # Electron supplies these paths inside the per-user Application Support
    # directory. Creating them here also makes the frozen backend robust when
    # launched directly for diagnostics.
    Path(cfg.DEFAULT_SESSION_ROOT).mkdir(parents=True, exist_ok=True)
    Path(cfg.DB_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.AUTH_DB_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    store = TranscriptStore()
    stabilizer = TranscriptStabilizer()
    timed_stabilizer = TimedWordStabilizer()
    session_manager = SessionManager()
    auth_service = AuthService()
    bootstrap = auth_service.ensure_bootstrap_admin()
    if bootstrap:
        logger.warning("Initial beta admin login: %s", bootstrap)
        print(f"BETA_LOGIN {bootstrap}", flush=True)
    model_name = cfg.MLX_WHISPER_MODEL if cfg.WHISPER_BACKEND == "mlx" else cfg.WHISPER_MODEL
    logger.info("Loading %s ASR model (%s)...", cfg.WHISPER_BACKEND, model_name)
    WhisperEngine.get().load()
    logger.info("ASR model ready.")
    speaker_service = SpeakerService(
        embedding_model_path=cfg.SPEAKER_EMBEDDING_MODEL,
        provider=cfg.SHERPA_PROVIDER,
        threshold=cfg.SPEAKER_THRESHOLD,
    )
    segmenter_kwargs = {
        "model_path": cfg.SILERO_VAD_MODEL,
        "sample_rate": cfg.SAMPLE_RATE,
        "provider": cfg.SHERPA_PROVIDER,
    }
    vad_probe = SpeechSegmenter(**segmenter_kwargs)
    segmenters: dict[str, SpeechSegmenter] = {}
    stream_origin_by_channel: dict[str, float] = {}
    enrollment_recorder = AudioEnrollmentRecorder(speaker_service)
    share_server = ShareServer(lambda: store)
    web_app = WebAppServer(auth_service)
    web_state = web_app.start()
    logger.info("Beta web app: %s", web_state["url"])

    # Placeholder server ref — filled before pool starts using it
    server_ref: list[WSServer] = []

    def current_vad_status() -> dict:
        if segmenters:
            first_segmenter = next(iter(segmenters.values()))
            return first_segmenter.status()
        return vad_probe.status()

    def get_segmenter(channel_id: str) -> SpeechSegmenter:
        if channel_id not in segmenters:
            segmenters[channel_id] = SpeechSegmenter(**segmenter_kwargs)
        return segmenters[channel_id]

    def submit_segment(channel_id: str, segment) -> None:
        origin = stream_origin_by_channel.get(channel_id)
        if origin is None:
            return
        pool.submit(
            channel_id,
            segment.audio,
            speech_start_ts=origin + segment.stream_start,
            speech_end_ts=origin + segment.stream_end,
            speech_id=segment.speech_id,
            is_final=segment.is_final,
        )

    def flush_channel(channel_id: str) -> None:
        segmenter = segmenters.get(channel_id)
        if segmenter is None:
            return
        for segment in segmenter.flush():
            submit_segment(channel_id, segment)
        segmenter.reset()
        segmenters.pop(channel_id, None)
        stream_origin_by_channel.pop(channel_id, None)

    def on_result(result: TranscriptionResult) -> None:
        if server_ref:
            _make_result_handler(store, server_ref[0], speaker_service, stabilizer, timed_stabilizer, loop)(result)

    def on_status(status: dict) -> None:
        if server_ref:
            payload = {
                **status,
                "vad_engine": current_vad_status().get("engine"),
                "fallback_reason": status.get("fallback_reason") or current_vad_status().get("fallback_reason"),
            }
            asyncio.run_coroutine_threadsafe(
                server_ref[0].broadcast({"type": "engine_status", "id": None, "payload": payload}),
                loop,
            )

    pool = TranscriptionPool(loop=loop, on_result=on_result, on_status=on_status)

    def on_chunk(channel_id: str, audio, wall_clock_ts: float) -> None:
        enrollment_recorder.add_audio(audio)
        chunk_duration = len(audio) / cfg.SAMPLE_RATE
        if channel_id not in stream_origin_by_channel:
            stream_origin_by_channel[channel_id] = wall_clock_ts - chunk_duration
        segmenter = get_segmenter(channel_id)
        for segment in segmenter.segment(audio):
            submit_segment(channel_id, segment)

    channel_manager = ChannelManager(on_chunk=on_chunk, on_channel_stop=flush_channel)

    server = WSServer(
        channel_manager=channel_manager,
        transcript_store=store,
        device_scanner_fn=list_input_devices,
        session_manager=session_manager,
        speaker_service=speaker_service,
        share_server=share_server,
        vad_status_fn=current_vad_status,
        enrollment_fn=enrollment_recorder.enroll,
        auth_service=auth_service,
        transcript_reset_fn=lambda: (stabilizer.reset(), timed_stabilizer.reset()),
    )
    server_ref.append(server)

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received.")
        channel_manager.stop_all()
        for channel_id in list(segmenters):
            flush_channel(channel_id)
        pool.shutdown()
        share_server.stop()
        web_app.stop()
        store.close()
        auth_service.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await server.serve()


if __name__ == "__main__":
    # Required by PyInstaller on macOS: MLX/Hugging Face may start a resource
    # tracker or worker process. Without this dispatch hook each child would
    # execute the complete backend entry point again.
    multiprocessing.freeze_support()
    asyncio.run(main())
