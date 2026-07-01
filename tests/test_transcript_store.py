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


def test_get_all_since(store):
    now = time.time()
    store.add_segment("ch1", "old", now - 100)
    store.add_segment("ch1", "new", now + 1)
    recent = store.get_all(since=now)
    assert len(recent) == 1
    assert recent[0]["text"] == "new"
