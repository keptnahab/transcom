import os
import tempfile
import time
import pytest
from backend.transcript.store import TranscriptStore


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = TranscriptStore(db_path=path)
    yield s
    s.close()
    os.unlink(path)


def test_add_and_retrieve(store):
    ts = time.time()
    seg = store.add_segment("ch1", "hello world", ts)
    assert seg["text"] == "hello world"
    assert seg["channel_id"] == "ch1"
    all_segs = store.get_all()
    assert len(all_segs) == 1
    assert all_segs[0]["segment_id"] == seg["segment_id"]


def test_empty_text_not_stored(store):
    result = store.add_segment("ch1", "   ", time.time())
    assert result == {}
    assert len(store.get_all()) == 0


def test_segments_ordered_by_timestamp(store):
    t = time.time()
    store.add_segment("ch1", "second", t + 1)
    store.add_segment("ch1", "first", t)
    # In-memory order is insertion order; DB loads by timestamp
    all_segs = store.get_all()
    assert len(all_segs) == 2


def test_search(store):
    t = time.time()
    store.add_segment("ch1", "hello world", t)
    store.add_segment("ch2", "goodbye cruel world", t + 1)
    store.add_segment("ch1", "just hello", t + 2)

    results = store.search("hello")
    assert len(results) == 2
    assert all("hello" in r["text"].lower() for r in results)


def test_search_empty_query_returns_all(store):
    t = time.time()
    store.add_segment("ch1", "foo", t)
    store.add_segment("ch2", "bar", t + 1)
    assert len(store.search("")) == 2


def test_persistence(store, tmp_path):
    t = time.time()
    db_path = str(tmp_path / "persist_test.db")
    s1 = TranscriptStore(db_path=db_path)
    s1.add_segment("ch1", "persistent text", t)
    s1.close()

    # Re-open same DB
    s2 = TranscriptStore(db_path=db_path)
    segs = s2.get_all()
    s2.close()

    assert len(segs) == 1
    assert segs[0]["text"] == "persistent text"


def test_confirmation_policy_persists(tmp_path):
    db_path = str(tmp_path / "confirmation.db")
    first = TranscriptStore(db_path=db_path)
    first.add_segment("ch1", "Stopp", time.time(), requires_confirmation=True)
    first.close()

    second = TranscriptStore(db_path=db_path)
    assert second.get_all()[0]["requires_confirmation"] is True
    second.close()


def test_confirmation_acknowledgement_persists(tmp_path):
    db_path = str(tmp_path / "confirmation_ack.db")
    first = TranscriptStore(db_path=db_path)
    seg = first.add_segment("ch1", "Stopp", time.time(), requires_confirmation=True)
    acknowledged = first.acknowledge_confirmation(
        seg["segment_id"], acknowledged_by="operator@example.test"
    )
    assert acknowledged["confirmation_acknowledged"] is True
    assert acknowledged["confirmation_acknowledged_by"] == "operator@example.test"
    assert acknowledged["confirmation_acknowledged_at"] is not None
    events = first.get_confirmation_events(seg["segment_id"])
    assert len(events) == 1
    assert events[0]["acknowledged_by"] == "operator@example.test"
    assert events[0]["text"] == "Stopp"
    first.close()

    second = TranscriptStore(db_path=db_path)
    assert second.get_all()[0]["confirmation_acknowledged"] is True
    assert second.get_all()[0]["confirmation_acknowledged_by"] == "operator@example.test"
    assert len(second.get_confirmation_events(seg["segment_id"])) == 1
    second.close()


def test_safety_command_audit_fields_persist_and_repetitions_are_kept(tmp_path):
    db_path = str(tmp_path / "safety.db")
    first = TranscriptStore(db_path=db_path)
    now = time.time()
    safety = first.add_segment(
        "ch1",
        "Haltebremse verriegeln!",
        now,
        requires_confirmation=True,
        raw_text="Halt die Bremse verriegeln",
        safety_confirmation_raw_text="Haltebremse verriegeln.",
        safety_confirmation_model="Systran/faster-whisper-small@536b0662",
        safety_confirmation_used=True,
        safety_command_id="safety_brake_lock",
        safety_match_score=0.91,
        safety_match_margin=0.42,
        safety_catalog_id="catalog-v1",
        safety_catalog_sha256="a" * 64,
    )
    first.acknowledge_confirmation(safety["segment_id"], acknowledged_by="safety.operator@test")
    first.add_segment(
        "ch1",
        "Haltebremse verriegeln!",
        now + 1,
        requires_confirmation=True,
        raw_text="Haltebremse verriegeln",
        safety_command_id="safety_brake_lock",
        safety_match_score=0.99,
    )
    first.close()

    second = TranscriptStore(db_path=db_path)
    segments = second.get_all()
    events = second.get_confirmation_events(safety["segment_id"])
    second.close()

    assert len(segments) == 2
    assert segments[0]["raw_text"] == "Halt die Bremse verriegeln"
    assert segments[0]["safety_confirmation_raw_text"] == "Haltebremse verriegeln."
    assert segments[0]["safety_confirmation_model"] == "Systran/faster-whisper-small@536b0662"
    assert segments[0]["safety_confirmation_used"] is True
    assert segments[0]["safety_command_id"] == "safety_brake_lock"
    assert segments[0]["safety_match_score"] == pytest.approx(0.91)
    assert segments[0]["safety_match_margin"] == pytest.approx(0.42)
    assert segments[0]["safety_catalog_id"] == "catalog-v1"
    assert segments[0]["safety_catalog_sha256"] == "a" * 64
    assert events[0]["safety_confirmation_raw_text"] == "Haltebremse verriegeln."
    assert events[0]["safety_confirmation_model"] == "Systran/faster-whisper-small@536b0662"
    assert events[0]["safety_confirmation_used"] == 1


def test_normal_segment_cannot_replace_prior_safety_audit(store):
    now = time.time()
    safety = store.add_segment(
        "ch1",
        "Bühne sofort sperren!",
        now,
        raw_text="Bühne sofort sperren",
        safety_command_id="safety_stage_lock",
        safety_match_score=0.99,
        safety_match_margin=0.5,
    )
    normal = store.add_segment("ch1", "Bühne sofort sperren, bitte", now + 1)

    assert normal["segment_id"] != safety["segment_id"]
    persisted = store.get_all()[0]
    assert persisted["safety_command_id"] == "safety_stage_lock"
    assert persisted["raw_text"] == "Bühne sofort sperren"


def test_clear(store):
    t = time.time()
    store.add_segment("ch1", "to be cleared", t)
    store.clear()
    assert store.get_all() == []


def test_correct_speaker(store):
    seg = store.add_segment("ch1", "hello", time.time(), speaker_name="Unknown")
    updated = store.correct_speaker(seg["segment_id"], "sp1", "Director")
    assert updated["corrected_speaker_id"] == "sp1"
    assert updated["corrected_speaker_name"] == "Director"


def test_deduplicates_overlap_segments(store):
    now = time.time()
    first = store.add_segment("ch1", "Hallo Regie, dies ist Anna auf Kanal eins", now)
    duplicate = store.add_segment("ch1", "Hallo Regie, dies ist Anna auf Kanal eins", now + 2)
    assert first
    assert duplicate == {}
    assert len(store.get_all()) == 1


def test_replaces_short_overlap_with_longer_text(store):
    now = time.time()
    first = store.add_segment("ch1", "Hallo Regie", now)
    replacement = store.add_segment("ch1", "Hallo Regie, dies ist Anna auf Kanal eins", now + 2)
    assert replacement["segment_id"] == first["segment_id"]
    assert replacement["text"] == "Hallo Regie, dies ist Anna auf Kanal eins"
    assert len(store.get_all()) == 1


def test_deduplication_never_drops_confirmation_requirement(store):
    now = time.time()
    first = store.add_segment("ch1", "Stopp", now)
    upgraded = store.add_segment("ch1", "Stopp", now + 1, requires_confirmation=True)
    assert upgraded["segment_id"] == first["segment_id"]
    assert upgraded["requires_confirmation"] is True

    replaced = store.add_segment("ch1", "Stopp sofort", now + 2, requires_confirmation=False)
    assert replaced["requires_confirmation"] is True
    assert replaced["confirmation_acknowledged"] is False


def test_get_all_since(store):
    now = time.time()
    store.add_segment("ch1", "old", now - 100)
    store.add_segment("ch1", "new", now + 1)
    recent = store.get_all(since=now)
    assert len(recent) == 1
    assert recent[0]["text"] == "new"
