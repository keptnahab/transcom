import numpy as np
import pytest

from backend.speaker.service import SpeakerService


def test_stats_enrollment_is_not_used_as_voice_profile():
    service = SpeakerService()
    speaker = service.create_speaker("Director")
    result = service.enroll_from_stats(speaker["id"], duration_seconds=10, level=0.05)
    assert result["usable"] is False
    assert result["quality"] >= 0.55
    match = service.match_audio(np.ones(1600, dtype=np.float32) * 0.05)
    assert match.speaker_id != speaker["id"]


def test_speaker_limit_is_enforced():
    service = SpeakerService(max_speakers=1)
    service.create_speaker("A")
    with pytest.raises(ValueError):
      service.create_speaker("B")


def test_unknown_match_without_profiles():
    service = SpeakerService()
    match = service.match_audio(np.zeros(1600, dtype=np.float32))
    assert match.is_unknown is True
    assert match.speaker_id is None
