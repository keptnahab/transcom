import numpy as np
import pytest
from backend.audio.ring_buffer import RingBuffer


def make_buf(chunk=8, overlap=2, capacity=64):
    return RingBuffer(capacity=capacity, chunk_size=chunk, overlap_size=overlap)


def test_no_chunk_before_enough_data():
    buf = make_buf(chunk=8, overlap=2)
    buf.write(np.zeros(4, dtype=np.float32))
    assert buf.next_chunk() is None


def test_chunk_returned_after_enough_data():
    buf = make_buf(chunk=8, overlap=2)
    buf.write(np.ones(10, dtype=np.float32))
    chunk = buf.next_chunk()
    assert chunk is not None
    # First chunk: no history yet, overlap = 0 (clamped to available)
    assert len(chunk) == 8  # actual_overlap=0 on first chunk since read_pos=0


def test_overlap_on_second_chunk():
    buf = make_buf(chunk=8, overlap=2)
    data = np.arange(20, dtype=np.float32)
    buf.write(data)

    # Consume first chunk
    c1 = buf.next_chunk()
    assert c1 is not None

    # Second chunk should include 2-frame overlap from the end of c1
    c2 = buf.next_chunk()
    assert c2 is not None
    assert len(c2) == 10  # overlap(2) + chunk(8)
    # The first 2 frames of c2 should match the last 2 frames of c1
    np.testing.assert_array_equal(c2[:2], c1[-2:])


def test_read_advances_by_chunk_size():
    buf = make_buf(chunk=4, overlap=1, capacity=32)
    buf.write(np.ones(20, dtype=np.float32))
    c1 = buf.next_chunk()
    c2 = buf.next_chunk()
    c3 = buf.next_chunk()
    assert c1 is not None
    assert c2 is not None
    assert c3 is not None


def test_returns_copy_not_view():
    buf = make_buf(chunk=4, overlap=1, capacity=32)
    buf.write(np.ones(10, dtype=np.float32))
    chunk = buf.next_chunk()
    original = chunk.copy()
    chunk[:] = 999
    # Writing to the returned array must not corrupt the internal buffer
    buf.write(np.zeros(4, dtype=np.float32))
    c2 = buf.next_chunk()
    np.testing.assert_array_equal(c2[:1], original[-1:])  # overlap frame unchanged


def test_reset_clears_state():
    buf = make_buf(chunk=4, overlap=1, capacity=32)
    buf.write(np.ones(10, dtype=np.float32))
    buf.next_chunk()
    buf.reset()
    assert buf.buffered_frames == 0
    assert buf.next_chunk() is None


def test_large_overlap_builds_history_window():
    buf = make_buf(chunk=4, overlap=8, capacity=64)
    data = np.arange(20, dtype=np.float32)
    buf.write(data)

    c1 = buf.next_chunk()
    c2 = buf.next_chunk()
    c3 = buf.next_chunk()

    assert c1 is not None
    assert c2 is not None
    assert c3 is not None
    assert len(c1) == 4
    assert len(c2) == 8
    assert len(c3) == 12
    np.testing.assert_array_equal(c3, data[:12])


def test_context_window_must_fit_capacity():
    with pytest.raises(ValueError):
        RingBuffer(capacity=8, chunk_size=4, overlap_size=5)


def test_wrap_around():
    buf = RingBuffer(capacity=16, chunk_size=6, overlap_size=2)
    # Fill buffer beyond capacity to trigger wrap-around
    buf.write(np.arange(14, dtype=np.float32))
    c1 = buf.next_chunk()
    assert c1 is not None
    buf.write(np.arange(8, dtype=np.float32))
    c2 = buf.next_chunk()
    assert c2 is not None
    assert len(c2) == 8  # overlap(2) + chunk(6)
