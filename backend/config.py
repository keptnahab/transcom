import os
import platform
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_ASR_BACKEND = "mlx" if platform.system() == "Darwin" and platform.machine() == "arm64" else "faster-whisper"
WHISPER_BACKEND = os.environ.get("TRANSCOM_ASR_BACKEND", _DEFAULT_ASR_BACKEND).lower()

WS_HOST = os.environ.get("TRANSCOM_WS_HOST", "0.0.0.0")
WS_PORT = 8765
SHARE_HOST = "0.0.0.0"
SHARE_PORT = int(os.environ.get("TRANSCOM_SHARE_PORT", "8787"))
WEB_HOST = os.environ.get("TRANSCOM_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("TRANSCOM_WEB_PORT", "8080"))

# Audio capture
SAMPLE_RATE = 16000        # Hz — Whisper expects 16 kHz
CHANNELS = 2               # Accept mono/stereo input; mix to mono internally
DTYPE = "float32"
_DEFAULT_CHUNK_SECONDS = "1.25" if WHISPER_BACKEND == "mlx" else "1.5"
_DEFAULT_OVERLAP_SECONDS = "3.75" if WHISPER_BACKEND == "mlx" else "0.75"
CHUNK_SECONDS = float(os.environ.get("TRANSCOM_CHUNK_SECONDS", _DEFAULT_CHUNK_SECONDS))
OVERLAP_SECONDS = float(os.environ.get("TRANSCOM_OVERLAP_SECONDS", _DEFAULT_OVERLAP_SECONDS))
CAPTURE_BLOCK_SIZE = 1024  # Frames per sounddevice callback
MAX_INPUT_CHANNELS = 2

# Live segmentation / speaker identification
VAD_MIN_SPEECH_SECONDS = float(os.environ.get("TRANSCOM_VAD_MIN_SPEECH", "0.5"))
VAD_MIN_SILENCE_SECONDS = float(os.environ.get("TRANSCOM_VAD_MIN_SILENCE", "0.35"))
VAD_MAX_SEGMENT_SECONDS = float(os.environ.get("TRANSCOM_VAD_MAX_SEGMENT", "8.0"))
VAD_ENERGY_THRESHOLD = float(os.environ.get("TRANSCOM_VAD_ENERGY", "0.012"))
ASR_MIN_RMS = float(os.environ.get("TRANSCOM_ASR_MIN_RMS", str(VAD_ENERGY_THRESHOLD)))
SPEAKER_THRESHOLD = float(os.environ.get("TRANSCOM_SPEAKER_THRESHOLD", "0.45"))
SPEAKER_AUTO_CLUSTER = os.environ.get("TRANSCOM_SPEAKER_AUTO_CLUSTER", "1") not in {"0", "false", "False"}
SPEAKER_AUTO_THRESHOLD = float(os.environ.get("TRANSCOM_SPEAKER_AUTO_THRESHOLD", "0.35"))
SPEAKER_MAX_V1 = 8

# Whisper
WHISPER_MODEL = os.environ.get("TRANSCOM_MODEL", "base")
MLX_WHISPER_MODEL = os.environ.get("TRANSCOM_MLX_MODEL", "mlx-community/whisper-large-v3-turbo-q4")
WHISPER_DEVICE = os.environ.get("TRANSCOM_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("TRANSCOM_COMPUTE", "int8")
WHISPER_LANGUAGE = os.environ.get("TRANSCOM_LANG", "auto").lower()
WHISPER_ALLOWED_LANGUAGES = {
    lang.strip().lower()
    for lang in os.environ.get("TRANSCOM_ALLOWED_LANGS", "de,en").split(",")
    if lang.strip()
}
WHISPER_DEFAULT_LANGUAGE = os.environ.get("TRANSCOM_DEFAULT_LANG", "de").lower()
WHISPER_BEAM_SIZE = int(os.environ.get("TRANSCOM_BEAM_SIZE", "1"))
WHISPER_INITIAL_PROMPT = os.environ.get("TRANSCOM_INITIAL_PROMPT", "")
TRANSCRIPT_STABLE_TAIL_SECONDS = float(os.environ.get("TRANSCOM_STABLE_TAIL", "0.25"))

# Transcription pool
TRANSCRIPTION_WORKERS = 1  # Serialize Whisper inference for MVP (Strategy A)

# Persistence
DEFAULT_SESSION_ROOT = os.environ.get("TRANSCOM_SESSION_ROOT", str(PROJECT_ROOT / "sessions"))
DB_PATH = os.environ.get("TRANSCOM_DB", "transcom_session.db")
AUTH_DB_PATH = os.environ.get("TRANSCOM_AUTH_DB", str(PROJECT_ROOT / "transcom_auth.db"))
AUTH_BOOTSTRAP_EMAIL = os.environ.get("TRANSCOM_ADMIN_EMAIL", "admin@transcom.local")
AUTH_SESSION_SECONDS = int(os.environ.get("TRANSCOM_AUTH_SESSION_SECONDS", str(60 * 60 * 12)))

# Local model cache. Setup downloads models once; runtime does not need network.
MODEL_DIR = Path(os.environ.get("TRANSCOM_MODEL_DIR", str(PROJECT_ROOT / "models")))
SILERO_VAD_MODEL = Path(os.environ.get("TRANSCOM_SILERO_VAD_MODEL", str(MODEL_DIR / "silero_vad.onnx")))
SPEAKER_EMBEDDING_MODEL = Path(
    os.environ.get(
        "TRANSCOM_SPEAKER_MODEL",
        str(MODEL_DIR / "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"),
    )
)
SHERPA_PROVIDER = os.environ.get("TRANSCOM_SHERPA_PROVIDER", "cpu")

# Test mode: set TRANSCOM_AUDIO_SOURCE=file:///path/to/audio.wav to read from file
AUDIO_SOURCE = os.environ.get("TRANSCOM_AUDIO_SOURCE", None)
