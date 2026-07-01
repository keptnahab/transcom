from unittest.mock import patch
from backend.audio.device_scanner import list_input_devices


MOCK_DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 44100.0},
    {"name": "HDMI Output", "max_input_channels": 0, "default_samplerate": 44100.0},
    {"name": "Scarlett 2i2", "max_input_channels": 2, "default_samplerate": 48000.0},
]


def test_filters_output_only_devices():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.default") as mock_default:
        mock_default.device = [0, 1]
        result = list_input_devices()

    names = [d["name"] for d in result]
    assert "HDMI Output" not in names
    assert "MacBook Pro Microphone" in names
    assert "Scarlett 2i2" in names


def test_marks_default_device():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.default") as mock_default:
        mock_default.device = [0, 1]
        result = list_input_devices()

    defaults = [d for d in result if d["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "MacBook Pro Microphone"


def test_returns_correct_indices():
    with patch("sounddevice.query_devices", return_value=MOCK_DEVICES), \
         patch("sounddevice.default") as mock_default:
        mock_default.device = [0, 1]
        result = list_input_devices()

    indices = [d["index"] for d in result]
    assert 0 in indices
    assert 2 in indices
    assert 1 not in indices  # output-only device filtered out


def test_empty_device_list():
    with patch("sounddevice.query_devices", return_value=[]), \
         patch("sounddevice.default") as mock_default:
        mock_default.device = [None, None]
        result = list_input_devices()
    assert result == []
