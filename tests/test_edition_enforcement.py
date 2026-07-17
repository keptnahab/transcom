import asyncio
import json
from unittest.mock import patch

from backend.channels.channel import Channel
from backend.server.ws_server import WSServer
from backend.session.manager import SessionManager
import backend.config as cfg


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send(self, raw):
        self.messages.append(json.loads(raw))


class FakeChannelManager:
    def __init__(self):
        self.channel = Channel(name="Test", device_index=0)
        self.stop_all_calls = 0

    def list_channels(self):
        return [self.channel]

    def start_channel(self, channel_id):
        assert channel_id == self.channel.id
        self.channel.is_active = True
        return self.channel

    def stop_channel(self, channel_id):
        assert channel_id == self.channel.id
        self.channel.is_active = False
        return self.channel

    def stop_all(self):
        self.stop_all_calls += 1
        self.channel.is_active = False


class FakeStore:
    def __init__(self):
        self.reopened = None

    def get_all(self):
        return []

    def reopen(self, path):
        self.reopened = path


class FakeSpeakerService:
    def list_speakers(self):
        return []

    def status(self):
        return {}


class FakeShareServer:
    def state(self):
        return {"enabled": False}


def make_server(tmp_path, *, edition="starter", limit=60):
    channels = FakeChannelManager()
    sessions = SessionManager(default_root=str(tmp_path / "sessions"))
    store = FakeStore()
    server = WSServer(
        channel_manager=channels,
        transcript_store=store,
        device_scanner_fn=lambda: [],
        session_manager=sessions,
        speaker_service=FakeSpeakerService(),
        share_server=FakeShareServer(),
        edition=edition,
        session_limit_seconds=limit,
    )
    return server, channels, sessions, store


def test_unknown_and_missing_editions_fail_closed_to_starter():
    assert cfg.normalize_edition(None) == "starter"
    assert cfg.normalize_edition("") == "starter"
    assert cfg.normalize_edition("enterprise") == "starter"
    assert cfg.normalize_edition(" FULL ") == "full"


def test_starter_export_is_denied_without_writing(tmp_path):
    async def scenario():
        server, _channels, _sessions, _store = make_server(tmp_path, edition="starter")
        ws = FakeWebSocket()
        export_path = tmp_path / "locked.txt"

        await server._handle_export(ws, {"format": "txt", "path": str(export_path)}, "export-1")

        assert not export_path.exists()
        assert ws.messages == [{
            "type": "error",
            "id": "export-1",
            "payload": {
                "message": "Export ist in der Starter-Edition nicht verfügbar.",
                "code": "EDITION_EXPORT_LOCKED",
                "edition": "starter",
                "export_allowed": False,
                "session_limit_seconds": 60,
            },
        }]

    asyncio.run(scenario())


def test_status_exposes_edition_capabilities(tmp_path):
    server, _channels, _sessions, _store = make_server(tmp_path, edition="starter")
    engine_status = {
        "asr_backend": "test",
        "model": "test-model",
        "device": "cpu",
        "compute_type": "test",
        "language_mode": "auto",
        "last_language": None,
        "fallback_reason": None,
    }
    with patch("backend.server.ws_server.WhisperEngine.get") as get_engine:
        get_engine.return_value.status.return_value = engine_status
        status = server.status_payload()

    assert status["edition"] == "starter"
    assert status["export_allowed"] is False
    assert status["session_limit_seconds"] == 60


def test_full_has_no_limit_and_allows_export(tmp_path):
    async def scenario():
        server, channels, sessions, _store = make_server(tmp_path, edition="full", limit=0.01)
        ws = FakeWebSocket()
        sessions.create()
        server._clients.add(ws)

        await server._handle_session_start(ws, {}, "start-1")
        await server._handle_start_capture(ws, {"id": channels.channel.id}, "capture-1")
        await asyncio.sleep(0.03)

        assert channels.channel.is_active is True
        assert sessions.current.status == "live"
        assert server._edition_timer_task is None
        export_path = tmp_path / "full.txt"
        await server._handle_export(ws, {"format": "txt", "path": str(export_path)}, "export-2")
        assert export_path.exists()
        assert any(message["type"] == "export_done" for message in ws.messages)

    asyncio.run(scenario())


def test_starter_limit_stops_capture_and_session_and_broadcasts_reason(tmp_path):
    async def scenario():
        server, channels, sessions, _store = make_server(tmp_path, edition="starter", limit=0.02)
        ws = FakeWebSocket()
        sessions.create()
        server._clients.add(ws)

        await server._handle_session_start(ws, {}, "start-1")
        await server._handle_start_capture(ws, {"id": channels.channel.id}, "capture-1")
        assert channels.channel.is_active is True
        await asyncio.sleep(0.05)

        assert channels.channel.is_active is False
        assert sessions.current.status == "stopped"
        limit_message = next(message for message in ws.messages if message["type"] == "edition_limit_reached")
        assert limit_message["payload"] == {
            "edition": "starter",
            "reason": "starter_time_limit",
            "limit_seconds": 0.02,
            "message": "Starter-Limit erreicht: Die Transkription wurde nach 0.02 Sekunden gestoppt.",
        }
        assert any(message["type"] == "channels_updated" for message in ws.messages)
        assert any(
            message["type"] == "session_state"
            and message["payload"].get("reason") == "starter_time_limit"
            for message in ws.messages
        )

        await server._handle_start_capture(ws, {"id": channels.channel.id}, "capture-2")
        assert channels.channel.is_active is False
        assert ws.messages[-1]["payload"]["code"] == "EDITION_SESSION_LIMIT_REACHED"

    asyncio.run(scenario())


def test_new_session_resets_starter_budget(tmp_path):
    async def scenario():
        server, channels, sessions, _store = make_server(tmp_path, edition="starter", limit=0.01)
        ws = FakeWebSocket()
        sessions.create()
        server._clients.add(ws)
        await server._handle_session_start(ws, {}, "start-1")
        await asyncio.sleep(0.03)
        assert sessions.current.status == "stopped"

        await server._handle_session_create(ws, {"name": "Neu"}, "create-2")
        await server._handle_start_capture(ws, {"id": channels.channel.id}, "capture-2")
        assert channels.channel.is_active is True
        server._reset_edition_budget()

    asyncio.run(scenario())
