#!/usr/bin/env python3
"""Stage the three pinned HF snapshots and write a SHA-256 release manifest."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from huggingface_hub import snapshot_download
from scripts.download_models import required_model_snapshots


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_repo_name(repository: str) -> str:
    return "models--" + repository.replace("/", "--")


def verify_bundle(manifest_path: Path, cache_root: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or len(manifest.get("snapshots", [])) != 3:
        raise RuntimeError("Invalid model bundle manifest")
    for snapshot in manifest["snapshots"]:
        root = (
            cache_root
            / "hub"
            / cache_repo_name(snapshot["repository"])
            / "snapshots"
            / snapshot["revision"]
        )
        expected = {item["path"] for item in snapshot["files"]}
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        if actual != expected:
            raise RuntimeError(f"Model file set mismatch: {snapshot['repository']}")
        for item in snapshot["files"]:
            path = root / item["path"]
            if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
                raise RuntimeError(f"Model hash mismatch: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    runtime = ROOT / "release" / "runtime"
    manifest_path = runtime / "model-manifest.json"
    cache_root = runtime / "model-cache"
    if args.verify_only:
        verify_bundle(manifest_path, cache_root)
        print("Verified all three revisions and every staged file SHA-256.")
        return 0

    output = cache_root / "hub"
    if output.parent.exists():
        shutil.rmtree(output.parent)
    output.mkdir(parents=True)
    manifest = {"schema": 1, "snapshots": []}

    for model in required_model_snapshots():
        source = Path(snapshot_download(
            repo_id=model.repository,
            revision=model.revision,
            local_files_only=True,
        ))
        destination = output / cache_repo_name(model.repository) / "snapshots" / model.revision
        shutil.copytree(source, destination, symlinks=False)
        files = []
        for path in sorted(p for p in destination.rglob("*") if p.is_file()):
            files.append({
                "path": path.relative_to(destination).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })
        manifest["snapshots"].append({
            "role": model.role,
            "repository": model.repository,
            "revision": model.revision,
            "files": files,
        })

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {len(manifest['snapshots'])} pinned snapshots: {output}")
    print(f"SHA-256 manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
