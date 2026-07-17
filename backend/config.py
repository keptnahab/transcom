import os
import platform
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("TRANSCOM_RESOURCE_ROOT", str(Path(__file__).resolve().parents[1]))
).expanduser().resolve()


def _default_user_data_root() -> Path:
    """Return a writable, persistent per-user location outside the app bundle."""
    override = os.environ.get("TRANSCOM_USER_DATA_ROOT")
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "TransCom"
    return Path.home() / ".local" / "share" / "TransCom"


USER_DATA_ROOT = _default_user_data_root()

_DEFAULT_ASR_BACKEND = (
    "mlx" if platform.system() == "Darwin" and platform.machine() == "arm64" else "faster-whisper"
)
WHISPER_BACKEND = os.environ.get("TRANSCOM_ASR_BACKEND", _DEFAULT_ASR_BACKEND).lower()

WS_HOST = os.environ.get("TRANSCOM_WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("TRANSCOM_WS_PORT", "8765"))
SHARE_HOST = "0.0.0.0"
SHARE_PORT = int(os.environ.get("TRANSCOM_SHARE_PORT", "8787"))
WEB_HOST = os.environ.get("TRANSCOM_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("TRANSCOM_WEB_PORT", "8080"))


def normalize_edition(value) -> str:
    """Return a safe product edition; unknown/missing values never unlock Full."""
    return "full" if str(value or "").strip().lower() == "full" else "starter"


# Product access is enforced by the backend.  The Starter limit is deliberately
# not environment-configurable so a packaged client cannot silently extend it.
EDITION = normalize_edition(os.environ.get("TRANSCOM_EDITION"))
STARTER_SESSION_LIMIT_SECONDS = 60

# Audio capture
SAMPLE_RATE = 16000        # Hz — Whisper expects 16 kHz
CHANNELS = 2               # Accept mono/stereo input; mix to mono internally
DTYPE = "float32"
_DEFAULT_CHUNK_SECONDS = "0.15" if WHISPER_BACKEND == "mlx" else "1.5"
_DEFAULT_OVERLAP_SECONDS = "3.75" if WHISPER_BACKEND == "mlx" else "0.75"
CHUNK_SECONDS = float(os.environ.get("TRANSCOM_CHUNK_SECONDS", _DEFAULT_CHUNK_SECONDS))
OVERLAP_SECONDS = float(os.environ.get("TRANSCOM_OVERLAP_SECONDS", _DEFAULT_OVERLAP_SECONDS))
CAPTURE_BLOCK_SIZE = 1024  # Frames per sounddevice callback
MAX_INPUT_CHANNELS = 2

# Live segmentation / speaker identification
VAD_MIN_SPEECH_SECONDS = float(os.environ.get("TRANSCOM_VAD_MIN_SPEECH", "0.5"))
VAD_MIN_SILENCE_SECONDS = float(os.environ.get("TRANSCOM_VAD_MIN_SILENCE", "0.35"))
VAD_MAX_SEGMENT_SECONDS = float(os.environ.get("TRANSCOM_VAD_MAX_SEGMENT", "5.0"))
VAD_THRESHOLD = float(os.environ.get("TRANSCOM_VAD_THRESHOLD", "0.25"))
VAD_WINDOW_SIZE = int(os.environ.get("TRANSCOM_VAD_WINDOW_SIZE", "512"))
VAD_ENERGY_THRESHOLD = float(os.environ.get("TRANSCOM_VAD_ENERGY", "0.012"))
VAD_CONTEXT_PRE_ROLL_SECONDS = float(os.environ.get("TRANSCOM_VAD_PRE_ROLL", "0.65"))
VAD_CONTEXT_POST_ROLL_SECONDS = float(os.environ.get("TRANSCOM_VAD_POST_ROLL", "0.0"))
VAD_AUDIO_HISTORY_SECONDS = float(os.environ.get("TRANSCOM_VAD_AUDIO_HISTORY", "12.0"))
ASR_MIN_RMS = float(os.environ.get("TRANSCOM_ASR_MIN_RMS", str(VAD_ENERGY_THRESHOLD)))
ASR_CONFIRM_SHORT_SECONDS = float(os.environ.get("TRANSCOM_CONFIRM_SHORT_SECONDS", "3.0"))
ASR_EDGE_PADDING_SECONDS = float(os.environ.get("TRANSCOM_ASR_EDGE_PADDING", "0.35"))
ASR_EDGE_PADDING_MAX_SECONDS = float(os.environ.get("TRANSCOM_ASR_EDGE_PADDING_MAX", "3.0"))
SAFETY_COMMAND_MODE = os.environ.get("TRANSCOM_SAFETY_COMMAND_MODE", "0") not in {"0", "false", "False"}
SAFETY_COMMAND_CATALOG = os.environ.get(
    "TRANSCOM_SAFETY_COMMAND_CATALOG",
    str(PROJECT_ROOT / "backend/transcription/catalogs/safety_commands_closed_v1.json"),
)
SAFETY_COMMAND_MIN_SCORE = float(os.environ.get("TRANSCOM_SAFETY_COMMAND_MIN_SCORE", "0.82"))
SAFETY_COMMAND_MIN_MARGIN = float(os.environ.get("TRANSCOM_SAFETY_COMMAND_MIN_MARGIN", "0.04"))
SPEAKER_THRESHOLD = float(os.environ.get("TRANSCOM_SPEAKER_THRESHOLD", "0.45"))
SPEAKER_AUTO_CLUSTER = os.environ.get("TRANSCOM_SPEAKER_AUTO_CLUSTER", "1") not in {"0", "false", "False"}
SPEAKER_AUTO_THRESHOLD = float(os.environ.get("TRANSCOM_SPEAKER_AUTO_THRESHOLD", "0.35"))
SPEAKER_MAX_V1 = 8

# Whisper. Default model revisions are immutable and resolved from the local HF
# cache at runtime; scripts/setup.sh is the only networked download step.
WHISPER_MODEL_REPOSITORY = "Systran/faster-whisper-small"
WHISPER_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MLX_MODEL_REPOSITORY = "mlx-community/whisper-large-v3-mlx-4bit"
MLX_MODEL_REVISION = "d12b5d0043a6fe0c59af321617fba041d4e8e0c8"
MLX_SHORT_MODEL_REPOSITORY = "mlx-community/whisper-large-v3-turbo-q4"
MLX_SHORT_MODEL_REVISION = "660c343bbf4e52ac257f0b7d952e5388e6f93bef"
MLX_SHORT_MAX_SECONDS = 3.0
WHISPER_MODEL = os.environ.get("TRANSCOM_MODEL", WHISPER_MODEL_REPOSITORY)
MLX_WHISPER_MODEL = os.environ.get("TRANSCOM_MLX_MODEL", MLX_MODEL_REPOSITORY)
MLX_SHORT_WHISPER_MODEL = os.environ.get(
    "TRANSCOM_MLX_SHORT_MODEL", MLX_SHORT_MODEL_REPOSITORY
)
SAFETY_CONFIRMATION_MODEL_REPOSITORY = WHISPER_MODEL_REPOSITORY
SAFETY_CONFIRMATION_MODEL_REVISION = WHISPER_MODEL_REVISION
SAFETY_CONFIRMATION_BEAM_SIZE = 3
WHISPER_DEVICE = os.environ.get("TRANSCOM_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("TRANSCOM_COMPUTE", "int8")
WHISPER_CPU_THREADS = int(os.environ.get("TRANSCOM_CPU_THREADS", "12"))
WHISPER_LANGUAGE = os.environ.get("TRANSCOM_LANG", "de").lower()
WHISPER_ALLOWED_LANGUAGES = {
    lang.strip().lower()
    for lang in os.environ.get("TRANSCOM_ALLOWED_LANGS", "de,en").split(",")
    if lang.strip()
}
WHISPER_DEFAULT_LANGUAGE = os.environ.get("TRANSCOM_DEFAULT_LANG", "de").lower()
WHISPER_BEAM_SIZE = int(os.environ.get("TRANSCOM_BEAM_SIZE", "1"))
_DEFAULT_INITIAL_PROMPT = (
    "Deutschsprachige Theaterprobe mit kurzen Sicherheitskommandos und technischen Cues. "
    "Es geht um Motor, Bremse, Kreis, Kanal, Einheit, Buchstaben und Zahlen sowie um "
    "Inspizienz, Hubpodium, Not-Aus, AES67 und Dante."
)
WHISPER_INITIAL_PROMPT = os.environ.get("TRANSCOM_INITIAL_PROMPT", _DEFAULT_INITIAL_PROMPT)
WHISPER_HOTWORDS = os.environ.get("TRANSCOM_HOTWORDS", "")
GERMAN_SPOKEN_NUMBER_NORMALIZATION = os.environ.get(
    "TRANSCOM_GERMAN_SPOKEN_NUMBERS", "1"
) not in {"0", "false", "False"}
DOMAIN_GLOSSARY_TERMS = tuple(
    term.strip()
    for term in os.environ.get("TRANSCOM_DOMAIN_GLOSSARY", "Lastaufnahme,unterbrechen").split(",")
    if term.strip()
)
WHISPER_NO_SPEECH_THRESHOLD = float(os.environ.get("TRANSCOM_NO_SPEECH_THRESHOLD", "0.6"))
WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY = float(
    os.environ.get("TRANSCOM_LANGUAGE_SWITCH_MIN_PROBABILITY", "0.55")
)
WHISPER_LANGUAGE_STICKINESS_RATIO = float(
    os.environ.get("TRANSCOM_LANGUAGE_STICKINESS_RATIO", "0.75")
)
WHISPER_LANGUAGE_SWITCH_MARGIN = float(
    os.environ.get("TRANSCOM_LANGUAGE_SWITCH_MARGIN", "0.0")
)
TRANSCRIPT_STABLE_TAIL_SECONDS = float(os.environ.get("TRANSCOM_STABLE_TAIL", "0.25"))

# Transcription pool
TRANSCRIPTION_WORKERS = 1  # Serialize Whisper inference for MVP (Strategy A)

# Persistence
DEFAULT_SESSION_ROOT = os.environ.get(
    "TRANSCOM_SESSION_ROOT", str(USER_DATA_ROOT / "data" / "sessions")
)
DB_PATH = os.environ.get("TRANSCOM_DB", str(USER_DATA_ROOT / "data" / "transcom_session.db"))
AUTH_DB_PATH = os.environ.get(
    "TRANSCOM_AUTH_DB", str(USER_DATA_ROOT / "data" / "transcom_auth.db")
)
AUTH_BOOTSTRAP_EMAIL = os.environ.get("TRANSCOM_ADMIN_EMAIL", "admin@transcom.local")
AUTH_SESSION_SECONDS = int(os.environ.get("TRANSCOM_AUTH_SESSION_SECONDS", str(60 * 60 * 12)))
AUTH_DISABLED = os.environ.get("TRANSCOM_AUTH_DISABLED", "0") not in {"0", "false", "False"}
AUTH_DISABLED_EMAIL = os.environ.get("TRANSCOM_AUTH_DISABLED_EMAIL", "test@transcom.local")

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
_IMPROVED_DEMO_AUDIO = (
    PROJECT_ROOT
    / "evaluation"
    / "generated"
    / "synthetic_v2"
    / "dev"
    / "synthetic_de_v3-dev-001"
    / "audio"
    / "intercom.wav"
)
DEMO_AUDIO_PATH = Path(os.environ.get("TRANSCOM_DEMO_AUDIO", str(_IMPROVED_DEMO_AUDIO)))
