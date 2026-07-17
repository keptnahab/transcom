#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("edition", choices=("starter", "full"))
    args = parser.parse_args()
    payload = {
        "schema": 1,
        "edition": args.edition,
        "export_allowed": args.edition == "full",
        "session_limit_seconds": None if args.edition == "full" else 60,
    }
    destination = ROOT / "release" / "runtime" / "edition.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Edition manifest: {args.edition} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
