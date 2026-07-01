#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=5747
WS_PORT=8765
FEED="${1:-$ROOT/fixtures/audio/intercom_test_feed.wav}"

if [ ! -f "$FEED" ]; then
  echo "ERROR: audio feed not found: $FEED"
  echo "Run scripts/generate_test_audio_feed.sh first."
  exit 1
fi

cleanup() {
  echo ""
  echo "==> Shutting down test feed..."
  kill "$VITE_PID" "$BACKEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT"

echo "==> Cleaning old local dev processes..."
lsof -ti "tcp:$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti "tcp:$WS_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true

echo "==> Starting Vite renderer on http://localhost:$PORT"
npm run dev:renderer > /tmp/transcom-vite.log 2>&1 &
VITE_PID=$!

echo "==> Starting Python backend with test audio feed:"
echo "    $FEED"
TRANSCOM_AUDIO_SOURCE="file://$FEED" \
  "$ROOT/backend/.venv/bin/python" "$ROOT/backend/main.py" > /tmp/transcom-backend.log 2>&1 &
BACKEND_PID=$!

echo "==> Logs:"
echo "    /tmp/transcom-vite.log"
echo "    /tmp/transcom-backend.log"
echo "==> Open http://localhost:$PORT and click Start Feed."

wait "$BACKEND_PID"
