#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/fixtures/audio/intercom_test_feed.wav"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say -v Anna -o "$TMP/01.aiff" "Hallo Regie, dies ist Anna auf Kanal eins. Wir testen jetzt die lokale Transkription mit einem gemischten Intercom Signal."
say -v Daniel -o "$TMP/02.aiff" "Copy that. This is Daniel from stage management. The next cue is in ten seconds, please stand by."
say -v Anna -o "$TMP/03.aiff" "Danke. Bitte pruefen, ob der Sprecherwechsel im Transkript sichtbar bleibt."
say -v Daniel -o "$TMP/04.aiff" "Confirmed. The offline viewer should show timestamps, speaker names, and the current text."

for n in 01 02 03 04; do
  afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/$n.aiff" "$TMP/$n.wav"
done

"$ROOT/backend/.venv/bin/python" - "$OUT" "$TMP/01.wav" "$TMP/02.wav" "$TMP/03.wav" "$TMP/04.wav" <<'PY'
import sys
import wave

out_path = sys.argv[1]
in_paths = sys.argv[2:]
target_rate = 16000
silence_seconds = 0.8

frames = bytearray()

for idx, path in enumerate(in_paths):
    with wave.open(path, "rb") as src:
        channels = src.getnchannels()
        width = src.getsampwidth()
        rate = src.getframerate()
        raw = src.readframes(src.getnframes())

    if channels != 1 or width != 2 or rate != target_rate:
        raise SystemExit(f"Unexpected format for {path}: {channels}ch {width * 8}bit {rate}Hz")

    frames.extend(raw)
    if idx != len(in_paths) - 1:
        frames.extend(b"\x00\x00" * int(target_rate * silence_seconds))

with wave.open(out_path, "wb") as dst:
    dst.setnchannels(1)
    dst.setsampwidth(2)
    dst.setframerate(target_rate)
    dst.writeframes(bytes(frames))

duration = len(frames) / 2 / target_rate
print(f"Wrote {out_path}")
print(f"Duration: {duration:.1f}s, mono, 16 kHz")
PY
