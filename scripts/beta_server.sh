#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x backend/.venv/bin/python ]; then
  echo "ERROR: backend/.venv missing. Run ./scripts/setup.sh first."
  exit 1
fi

npm run build:renderer

export PYTHONUNBUFFERED=1
export PYTHONPATH="$ROOT"
export TRANSCOM_WEB_HOST="${TRANSCOM_WEB_HOST:-0.0.0.0}"
export TRANSCOM_WS_HOST="${TRANSCOM_WS_HOST:-0.0.0.0}"
export TRANSCOM_CHUNK_SECONDS="${TRANSCOM_CHUNK_SECONDS:-1.5}"
export TRANSCOM_LANG="${TRANSCOM_LANG:-de}"

backend/.venv/bin/python backend/main.py
