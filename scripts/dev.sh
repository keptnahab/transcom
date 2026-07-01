#!/usr/bin/env bash
# Dev launcher for TransCom — starts Vite renderer then Electron.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/backend/.venv"
PORT=5747

if [ ! -d "$VENV" ]; then
  echo "ERROR: venv not found. Run ./scripts/setup.sh first."
  exit 1
fi

echo "==> Cleaning up old processes on port $PORT..."
lsof -ti "tcp:$PORT" 2>/dev/null | xargs kill -9 2>/dev/null
sleep 0.3

cleanup() {
  echo ""
  echo "==> Shutting down..."
  kill "$VITE_PID" "$ELECTRON_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

cd "$ROOT"

echo "==> Starting Vite on port $PORT..."
npm run dev:renderer > /tmp/transcom-vite.log 2>&1 &
VITE_PID=$!

echo "    Waiting for Vite (logs: /tmp/transcom-vite.log)..."
for i in $(seq 1 40); do
  sleep 0.5
  if curl -sf "http://localhost:$PORT" > /dev/null 2>&1; then
    echo "    Vite ready."
    break
  fi
  if ! kill -0 "$VITE_PID" 2>/dev/null; then
    echo "ERROR: Vite exited. Check /tmp/transcom-vite.log:"
    cat /tmp/transcom-vite.log
    exit 1
  fi
done

echo "==> Starting Electron..."
NODE_ENV=development TRANSCOM_RENDERER_PORT=$PORT \
  node_modules/.bin/electron . > /tmp/transcom-electron.log 2>&1 &
ELECTRON_PID=$!

echo "    TransCom running. Logs: /tmp/transcom-vite.log  /tmp/transcom-electron.log"
echo "    Press Ctrl-C to stop."

wait "$ELECTRON_PID"
