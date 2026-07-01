#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/backend/.venv"

echo "==> TransCom setup"

# Check Python 3.11+
PYTHON=$(command -v python3.11 || command -v python3 || echo "")
if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3.11+ not found. Install with: brew install python@3.11"
  exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "    Python: $PY_VERSION at $PYTHON"

# Check portaudio (required by sounddevice)
if ! brew list portaudio &>/dev/null; then
  echo "==> Installing portaudio via Homebrew..."
  brew install portaudio
fi

# Create venv
if [ ! -d "$VENV" ]; then
  echo "==> Creating virtual environment..."
  "$PYTHON" -m venv "$VENV"
fi

echo "==> Installing Python dependencies..."
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$ROOT/backend/requirements.txt"

# Pre-download Whisper model (base by default)
MODEL="${TRANSCOM_MODEL:-base}"
echo "==> Pre-downloading Whisper model: $MODEL"
"$VENV/bin/python" -c "
from faster_whisper import WhisperModel
print(f'  Downloading {\"$MODEL\"} model (one-time)...')
WhisperModel('$MODEL', device='cpu', compute_type='int8')
print('  Done.')
"

# Install Node deps
echo "==> Installing Node dependencies..."
cd "$ROOT" && npm install

echo ""
echo "Setup complete. Run: ./scripts/dev.sh"
