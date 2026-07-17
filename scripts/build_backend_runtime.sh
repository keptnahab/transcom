#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"
OUT="$ROOT/release/runtime"
export PYINSTALLER_CONFIG_DIR="$ROOT/build/pyinstaller-config"
SITE_PACKAGES="$("$PYTHON" -c 'import site; print(site.getsitepackages()[0])')"

if ! "$PYTHON" -c 'import PyInstaller' 2>/dev/null; then
  echo "ERROR: PyInstaller fehlt. Installiere es in backend/.venv (Version 6.15.0)." >&2
  exit 1
fi

rm -rf "$ROOT/build/transcom-backend" "$OUT/backend-runtime"
mkdir -p "$OUT"

cd "$ROOT"
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name transcom-backend \
  --paths "$ROOT" \
  --distpath "$OUT" \
  --workpath "$ROOT/build/transcom-backend" \
  --specpath "$ROOT/build" \
  --add-data "$ROOT/backend/transcription/catalogs:backend/transcription/catalogs" \
  --add-data "$SITE_PACKAGES/mlx:mlx" \
  --collect-data mlx_whisper \
  --hidden-import mlx_whisper \
  --hidden-import mlx_whisper.transcribe \
  --collect-all sherpa_onnx \
  --collect-all ctranslate2 \
  --collect-all faster_whisper \
  --collect-all sounddevice \
  --collect-all soundfile \
  --hidden-import websockets.legacy \
  backend/main.py

mv "$OUT/transcom-backend" "$OUT/backend-runtime"
test -x "$OUT/backend-runtime/transcom-backend"
echo "Backend runtime: $OUT/backend-runtime"
