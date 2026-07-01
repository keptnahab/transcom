from __future__ import annotations
import asyncio
import json
import logging
from typing import TYPE_CHECKING, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.server import WebSocketServerProtocol

from backend.server.message_schema import make
import backend.config as cfg

if TYPE_CHECKING:
    from backend.channels.channel_manager import ChannelManager
    from backend.transcript.store import TranscriptStore
    from backend.session import SessionManager
    from backend.share import ShareServer
    from backend.speaker import SpeakerService
    from backend.auth import AuthService

logger = logging.getLogger(__name__)


class WSServer:
    """
    Manages all WebSocket connections and routes inbound messages to handlers.

    The server is a thin dispatcher — all business logic lives in
    ChannelManager and TranscriptStore which are injected at construction time.
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        transcript_store: TranscriptStore,
        device_scanner_fn,
        session_manager: SessionManager,
        speaker_service: SpeakerService,
        share_server: ShareServer,
        vad_status_fn: Callable[[], dict] | None = None,
        enrollment_fn: Callable[[str, float], Awaitable[dict]] | None = None,
        auth_service: AuthService | None = None,
        transcript_reset_fn: Callable[[], None] | None = None,
    ) -> None:
        self._channel_manager = channel_manager
        self._store = transcript_store
        self._scan_devices = device_scanner_fn
        self._session_manager = session_manager
        self._speaker_service = speaker_service
        self._share_server = share_server
        self._vad_status_fn = vad_status_fn
        self._enrollment_fn = enrollment_fn
        self._auth_service = auth_service
        self._transcript_reset_fn = transcript_reset_fn
        self._clients: set[WebSocketServerProtocol] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def serve(self) -> None:
        async with websockets.serve(
            self._handler,
            cfg.WS_HOST,
            cfg.WS_PORT,
            ping_interval=20,
            ping_timeout=10,
        ):
            logger.info("WebSocket server listening on ws://%s:%d", cfg.WS_HOST, cfg.WS_PORT)
            print("READY", flush=True)   # Electron main.js watches for this
            await asyncio.Future()       # run forever

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handler(self, ws: WebSocketServerProtocol) -> None:
        if self._auth_service is not None:
            token = self._token_from_ws(ws)
            if self._auth_service.user_for_token(token) is None:
                await self._handle_unauthorized_socket(ws)
                return
        self._clients.add(ws)
        logger.info("Client connected (%d total)", len(self._clients))
        try:
            async for raw in ws:
                await self._dispatch(ws, raw)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosedError as exc:
            logger.warning("Client connection error: %s", exc)
        finally:
            self._clients.discard(ws)
            logger.info("Client disconnected (%d remaining)", len(self._clients))

    async def _handle_unauthorized_socket(self, ws: WebSocketServerProtocol) -> None:
        logger.info("Unauthorized WebSocket client connected")
        await self._send(ws, make("auth_required", {"message": "Unauthorized", "code": "UNAUTHORIZED"}))
        try:
            async for _raw in ws:
                await self._send(ws, make("error", {"message": "Unauthorized", "code": "UNAUTHORIZED"}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            logger.info("Unauthorized WebSocket client disconnected")

    def _token_from_ws(self, ws: WebSocketServerProtocol) -> str | None:
        path = getattr(ws, "path", None)
        request = getattr(ws, "request", None)
        if path is None and request is not None:
            path = getattr(request, "path", None)
        query = parse_qs(urlparse(path or "").query)
        token = query.get("token", [None])[0]
        return token

    async def _dispatch(self, ws: WebSocketServerProtocol, raw: str) -> None:
        try:
            msg = json.loads(raw)
            type_ = msg.get("type", "")
            payload = msg.get("payload", {})
            req_id = msg.get("id")
        except (json.JSONDecodeError, AttributeError):
            await self._send(ws, make("error", {"message": "Invalid JSON", "code": "PARSE_ERROR"}))
            return

        handlers = {
            "init": self._handle_init,
            "list_devices": self._handle_list_devices,
            "add_channel": self._handle_add_channel,
            "set_audio_source": self._handle_set_audio_source,
            "set_language": self._handle_set_language,
            "update_channel": self._handle_update_channel,
            "remove_channel": self._handle_remove_channel,
            "start_capture": self._handle_start_capture,
            "stop_capture": self._handle_stop_capture,
            "stop_all": self._handle_stop_all,
            "search_transcript": self._handle_search,
            "export_transcript": self._handle_export,
            "clear_transcript": self._handle_clear,
            "get_status": self._handle_get_status,
            "session_create": self._handle_session_create,
            "session_start": self._handle_session_start,
            "session_stop": self._handle_session_stop,
            "speaker_create": self._handle_speaker_create,
            "speaker_update": self._handle_speaker_update,
            "speaker_delete": self._handle_speaker_delete,
            "enrollment_start": self._handle_enrollment_start,
            "segment_correct_speaker": self._handle_segment_correct_speaker,
            "share_start": self._handle_share_start,
            "share_stop": self._handle_share_stop,
        }

        handler = handlers.get(type_)
        if handler is None:
            await self._send(ws, make("error", {"message": f"Unknown type: {type_}", "code": "UNKNOWN_TYPE"}, req_id))
            return

        try:
            await handler(ws, payload, req_id)
        except Exception as exc:
            logger.exception("Handler error for type=%s", type_)
            await self._send(ws, make("error", {"message": str(exc), "code": "HANDLER_ERROR"}, req_id))

    # ------------------------------------------------------------------
    # Inbound handlers
    # ------------------------------------------------------------------

    async def _handle_init(self, ws, payload, req_id):
        devices = self._scan_devices()
        channels = [ch.to_dict() for ch in self._channel_manager.list_channels()]
        segments = self._store.get_all()
        await self._send(ws, make("init_state", {
            "devices": devices,
            "channels": channels,
            "segments": segments,
            "session": self._session_manager.to_dict(),
            "speakers": self._speaker_service.list_speakers(),
            "share": self._share_server.state(),
            "audio_source": self.audio_source_payload(),
            "status": self.status_payload(),
        }, req_id))

    async def _handle_list_devices(self, ws, payload, req_id):
        devices = self._scan_devices()
        await self._send(ws, make("device_list", {"devices": devices}, req_id))

    async def _handle_set_audio_source(self, ws, payload, req_id):
        mode = payload.get("mode", "live")
        if mode == "file":
            path = str(payload.get("path") or "").strip()
            if not path:
                raise ValueError("Audio file path required")
            cfg.AUDIO_SOURCE = f"file://{path}"
        elif mode == "live":
            cfg.AUDIO_SOURCE = None
        else:
            raise ValueError(f"Unknown audio source mode: {mode}")

        self._channel_manager.stop_all()
        await self.broadcast(make("audio_source_state", self.audio_source_payload(), req_id))
        await self.broadcast(make("channels_updated", {"channels": [ch.to_dict() for ch in self._channel_manager.list_channels()]}))

    async def _handle_set_language(self, ws, payload, req_id):
        language = str(payload.get("language", "")).strip().lower()
        if language != "auto" and language not in cfg.WHISPER_ALLOWED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}. Supported: auto, de, en")
        cfg.WHISPER_LANGUAGE = language
        await self.broadcast(make("backend_status", self.status_payload(), req_id))

    async def _handle_add_channel(self, ws, payload, req_id):
        ch = self._channel_manager.create_channel(
            name=payload["name"],
            device_index=int(payload["device_index"]),
            color=payload.get("color", "#3498db"),
            label=payload.get("label"),
        )
        if payload.get("start"):
            ch = self._channel_manager.start_channel(ch.id)
        await self.broadcast(make("channel_added", {"channel": ch.to_dict()}))

    async def _handle_update_channel(self, ws, payload, req_id):
        ch = self._channel_manager.update_channel(
            id_=payload["id"],
            name=payload.get("name"),
            device_index=int(payload["device_index"]) if "device_index" in payload else None,
            color=payload.get("color"),
            label=payload.get("label"),
        )
        await self.broadcast(make("channel_updated", {"channel": ch.to_dict()}))

    async def _handle_remove_channel(self, ws, payload, req_id):
        self._channel_manager.delete_channel(payload["id"])
        await self.broadcast(make("channel_removed", {"id": payload["id"]}))

    async def _handle_start_capture(self, ws, payload, req_id):
        ch = self._channel_manager.start_channel(payload["id"])
        await self.broadcast(make("channel_updated", {"channel": ch.to_dict()}))

    async def _handle_stop_capture(self, ws, payload, req_id):
        ch = self._channel_manager.stop_channel(payload["id"])
        await self.broadcast(make("channel_updated", {"channel": ch.to_dict()}))

    async def _handle_stop_all(self, ws, payload, req_id):
        self._channel_manager.stop_all()
        channels = [ch.to_dict() for ch in self._channel_manager.list_channels()]
        await self.broadcast(make("channels_updated", {"channels": channels}))

    async def _handle_search(self, ws, payload, req_id):
        results = self._store.search(payload.get("query", ""))
        await self._send(ws, make("search_results", {"segments": results, "query": payload.get("query", "")}, req_id))

    async def _handle_export(self, ws, payload, req_id):
        fmt = payload.get("format", "txt")
        path = payload.get("path", f"transcom_export.{fmt}")
        from backend.transcript.exporter import export
        export(self._store, fmt, path)
        await self._send(ws, make("export_done", {"path": path, "format": fmt}, req_id))

    async def _handle_clear(self, ws, payload, req_id):
        self._store.clear()
        self._reset_transcript_state()
        await self.broadcast(make("transcript_cleared", {}))

    async def _handle_get_status(self, ws, payload, req_id):
        await self._send(ws, make("backend_status", self.status_payload(), req_id))

    async def _handle_session_create(self, ws, payload, req_id):
        info = self._session_manager.create(
            root_dir=payload.get("root_dir"),
            name=payload.get("name"),
        )
        self._store.reopen(info.db_path)
        self._reset_transcript_state()
        await self.broadcast(make("session_state", {"session": self._session_manager.to_dict()}))
        await self.broadcast(make("transcript_cleared", {}))

    def _reset_transcript_state(self) -> None:
        if self._transcript_reset_fn is not None:
            self._transcript_reset_fn()

    async def _handle_session_start(self, ws, payload, req_id):
        info = self._session_manager.start()
        await self.broadcast(make("session_state", {"session": self._session_manager.to_dict()}))
        await self._send(ws, make("session_started", {"session": info.__dict__}, req_id))

    async def _handle_session_stop(self, ws, payload, req_id):
        self._channel_manager.stop_all()
        info = self._session_manager.stop()
        await self.broadcast(make("channels_updated", {"channels": [ch.to_dict() for ch in self._channel_manager.list_channels()]}))
        await self.broadcast(make("session_state", {"session": self._session_manager.to_dict()}))
        await self._send(ws, make("session_stopped", {"session": info.__dict__}, req_id))

    async def _handle_speaker_create(self, ws, payload, req_id):
        speaker = self._speaker_service.create_speaker(
            name=payload.get("name", ""),
            color=payload.get("color"),
        )
        await self.broadcast(make("speaker_update", {"speaker": speaker, "speakers": self._speaker_service.list_speakers()}))

    async def _handle_speaker_update(self, ws, payload, req_id):
        speaker = self._speaker_service.update_speaker(
            speaker_id=payload["id"],
            name=payload.get("name"),
            color=payload.get("color"),
        )
        await self.broadcast(make("speaker_update", {"speaker": speaker, "speakers": self._speaker_service.list_speakers()}))

    async def _handle_speaker_delete(self, ws, payload, req_id):
        self._speaker_service.delete_speaker(payload["id"])
        await self.broadcast(make("speaker_update", {"speaker": None, "speakers": self._speaker_service.list_speakers()}))

    async def _handle_enrollment_start(self, ws, payload, req_id):
        duration = float(payload.get("duration_seconds", 10))
        if self._enrollment_fn is not None:
            await self.broadcast(make("engine_status", {
                "state": "enrollment",
                "message": "Recording speaker check-in",
            }, req_id))
            result = await self._enrollment_fn(payload["speaker_id"], duration)
        else:
            result = self._speaker_service.enroll_from_stats(
                speaker_id=payload["speaker_id"],
                duration_seconds=duration,
                level=float(payload.get("level", 0)),
            )
        await self.broadcast(make("enrollment_result", result, req_id))
        await self.broadcast(make("speaker_update", {"speaker": result["speaker"], "speakers": self._speaker_service.list_speakers()}))

    async def _handle_segment_correct_speaker(self, ws, payload, req_id):
        speaker_id = payload.get("speaker_id")
        speaker_name = payload.get("speaker_name")
        segment = self._store.correct_speaker(payload["segment_id"], speaker_id, speaker_name)
        await self.broadcast(make("segment_updated", {"segment": segment}, req_id))

    async def _handle_share_start(self, ws, payload, req_id):
        state = self._share_server.start()
        await self.broadcast(make("share_state", state, req_id))

    async def _handle_share_stop(self, ws, payload, req_id):
        state = self._share_server.stop()
        await self.broadcast(make("share_state", state, req_id))

    def status_payload(self) -> dict:
        active = [ch.to_dict() for ch in self._channel_manager.list_channels() if ch.is_active]
        vad_status = self._vad_status_fn() if self._vad_status_fn else {
            "engine": "unknown",
            "ready": False,
            "error": None,
        }
        speaker_status = self._speaker_service.status()
        mlx_backend = cfg.WHISPER_BACKEND == "mlx"
        return {
            "active_channels": len(active),
            "segments": len(self._store.get_all()),
            "active_channel_ids": [ch["id"] for ch in active],
            "audio_source": self.audio_source_payload(),
            "backend": cfg.WHISPER_BACKEND,
            "model": cfg.MLX_WHISPER_MODEL if mlx_backend else cfg.WHISPER_MODEL,
            "device": "apple-silicon" if mlx_backend else cfg.WHISPER_DEVICE,
            "compute_type": "mlx-q4" if mlx_backend else cfg.WHISPER_COMPUTE_TYPE,
            "language": cfg.WHISPER_LANGUAGE,
            "allowed_languages": sorted(cfg.WHISPER_ALLOWED_LANGUAGES),
            "chunk_seconds": cfg.CHUNK_SECONDS,
            "overlap_seconds": cfg.OVERLAP_SECONDS,
            "stable_tail_seconds": cfg.TRANSCRIPT_STABLE_TAIL_SECONDS,
            "vad": vad_status,
            "speaker_model": speaker_status,
        }

    def audio_source_payload(self) -> dict:
        demo_path = cfg.PROJECT_ROOT / "fixtures" / "audio" / "intercom_test_feed.wav"
        if cfg.AUDIO_SOURCE and cfg.AUDIO_SOURCE.startswith("file://"):
            return {
                "mode": "file",
                "path": cfg.AUDIO_SOURCE[7:],
                "demo_path": str(demo_path),
            }
        return {
            "mode": "live",
            "path": None,
            "demo_path": str(demo_path),
        }

    # ------------------------------------------------------------------
    # Outbound helpers
    # ------------------------------------------------------------------

    async def broadcast(self, message: dict) -> None:
        """Send a message to all connected clients."""
        if not self._clients:
            return
        raw = json.dumps(message)
        # Fire-and-forget to all; don't let one slow client block others
        await asyncio.gather(
            *[ws.send(raw) for ws in list(self._clients)],
            return_exceptions=True,
        )

    async def _send(self, ws: WebSocketServerProtocol, message: dict) -> None:
        try:
            await ws.send(json.dumps(message))
        except websockets.exceptions.ConnectionClosed:
            self._clients.discard(ws)
