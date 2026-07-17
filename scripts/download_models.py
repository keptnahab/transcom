#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import NamedTuple, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from huggingface_hub import snapshot_download

import backend.config as cfg


class ModelSnapshot(NamedTuple):
    role: str
    repository: str
    revision: str


def required_model_snapshots() -> tuple[ModelSnapshot, ...]:
    return (
        ModelSnapshot(
            "mlx-full-over-3s",
            cfg.MLX_MODEL_REPOSITORY,
            cfg.MLX_MODEL_REVISION,
        ),
        ModelSnapshot(
            "mlx-turbo-up-to-3s",
            cfg.MLX_SHORT_MODEL_REPOSITORY,
            cfg.MLX_SHORT_MODEL_REVISION,
        ),
        ModelSnapshot(
            "faster-whisper-small-confirmation-fallback",
            cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY,
            cfg.SAFETY_CONFIRMATION_MODEL_REVISION,
        ),
    )


def _validate_pin(snapshot: ModelSnapshot) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", snapshot.revision):
        raise RuntimeError(
            f"Model {snapshot.repository!r} is not pinned to a full commit SHA: "
            f"{snapshot.revision!r}"
        )


def _validate_local_snapshot(path: str, snapshot: ModelSnapshot) -> str:
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise RuntimeError(
            f"Pinned snapshot is not a directory for {snapshot.role}: {resolved}"
        )
    if resolved.name != snapshot.revision:
        raise RuntimeError(
            f"Resolved revision mismatch for {snapshot.role}: "
            f"expected {snapshot.revision}, got {resolved.name}"
        )
    if not any(candidate.is_file() for candidate in resolved.rglob("*")):
        raise RuntimeError(f"Pinned snapshot is empty for {snapshot.role}: {resolved}")
    return str(resolved)


def _resolve(snapshot: ModelSnapshot, *, local_files_only: bool) -> str:
    _validate_pin(snapshot)
    mode = "verify offline" if local_files_only else "download pinned"
    print(f"  [{mode}] {snapshot.role}: {snapshot.repository}@{snapshot.revision}")
    path = snapshot_download(
        repo_id=snapshot.repository,
        revision=snapshot.revision,
        local_files_only=local_files_only,
    )
    return _validate_local_snapshot(path, snapshot)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download or offline-verify every pinned TransCom ASR snapshot."
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Use the local Hugging Face cache only; never access the network.",
    )
    args = parser.parse_args(argv)
    try:
        for snapshot in required_model_snapshots():
            _resolve(snapshot, local_files_only=args.verify_only)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.verify_only:
        print("  All three pinned ASR snapshots verified from the local cache.")
    else:
        print("  All three pinned ASR snapshots downloaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
