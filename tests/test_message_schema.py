import json
from backend.server.message_schema import make


def test_make_round_trips():
    msg = make("add_channel", {"name": "Mic 1", "device_index": 0, "color": "#3498db"}, id_="req-1")
    raw = json.dumps(msg)
    parsed = json.loads(raw)
    assert parsed["type"] == "add_channel"
    assert parsed["id"] == "req-1"
    assert parsed["payload"]["name"] == "Mic 1"


def test_make_no_id():
    msg = make("init_state", {"devices": [], "channels": [], "segments": []})
    assert msg["id"] is None
    raw = json.dumps(msg)
    parsed = json.loads(raw)
    assert parsed["type"] == "init_state"


def test_all_message_types_are_json_serializable():
    types_and_payloads = [
        ("init", {}),
        ("list_devices", {}),
        ("set_audio_source", {"mode": "file", "path": "/tmp/intercom.wav"}),
        ("set_language", {"language": "de"}),
        ("audio_source_state", {"mode": "live", "path": None}),
        ("add_channel", {"name": "x", "device_index": 0, "color": "#fff"}),
        ("update_channel", {"id": "abc", "name": "y"}),
        ("remove_channel", {"id": "abc"}),
        ("start_capture", {"id": "abc"}),
        ("stop_capture", {"id": "abc"}),
        ("stop_all", {}),
        ("search_transcript", {"query": "hello"}),
        ("export_transcript", {"format": "csv", "path": "/tmp/out.csv"}),
        ("clear_transcript", {}),
        ("transcript_cleared", {}),
        ("session_create", {"name": "show", "root_dir": "/tmp/transcom"}),
        ("session_start", {}),
        ("session_stop", {}),
        ("speaker_create", {"name": "Director"}),
        ("speaker_update", {"speaker": {"id": "sp1"}, "speakers": []}),
        ("enrollment_start", {"speaker_id": "sp1", "duration_seconds": 10, "level": 0.04}),
        ("enrollment_result", {"quality": 0.9, "usable": True}),
        ("speaker_match", {"speaker_id": "sp1", "confidence": 0.8}),
        ("segment_correct_speaker", {"segment_id": "seg1", "speaker_id": "sp1"}),
        ("segment_acknowledge_confirmation", {"segment_id": "seg1"}),
        ("share_start", {}),
        ("share_stop", {}),
        ("share_state", {"enabled": True, "url": "http://127.0.0.1:8787/?token=x"}),
        ("backend_status", {"active_channels": 0}),
        ("engine_status", {"state": "ready", "message": "Model ready"}),
        ("edition_limit_reached", {"edition": "starter", "reason": "starter_time_limit", "limit_seconds": 60}),
        ("transcript_segment", {"segment_id": "x", "channel_id": "y", "text": "hi", "timestamp": 1.0, "confidence": 0.9}),
        ("error", {"message": "oops", "code": "E001"}),
    ]
    for type_, payload in types_and_payloads:
        msg = make(type_, payload)
        serialized = json.dumps(msg)
        parsed = json.loads(serialized)
        assert parsed["type"] == type_
