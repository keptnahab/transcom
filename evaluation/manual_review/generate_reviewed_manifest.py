from __future__ import annotations

import argparse
import json
from pathlib import Path

from .review_core import (
    ReviewError,
    build_inherited_reviewed_manifest,
    build_reviewed_manifest,
    load_manifest,
    load_profiles,
    profile_output_path,
    write_reviewed_manifest,
)


MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = MODULE_DIR.parents[1]
DEFAULT_PROFILES = MODULE_DIR / "profiles_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a versioned manifest only after a complete hash-bound manual review"
    )
    parser.add_argument("--profile", required=True, help="Exact profile id from profiles_v1.json")
    parser.add_argument("--output", type=Path, help="Optional *_reviewed_v1.json output path")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    profiles = load_profiles(args.profiles, project_root)
    if args.profile not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown profile {args.profile!r}. Available: {choices}")
    loaded = load_manifest(profiles[args.profile])
    output_path = args.output or profile_output_path(loaded.profile)
    if not output_path.is_absolute():
        output_path = project_root / output_path
    try:
        if loaded.profile.mode == "manual":
            reviewed, review_log_sha256 = build_reviewed_manifest(loaded, project_root)
        else:
            parent_profile = profiles[loaded.profile.parent_profile_id]
            parent_loaded = load_manifest(parent_profile)
            parent_reviewed_path = profile_output_path(parent_profile)
            if not parent_reviewed_path.is_file():
                raise ReviewError(
                    f"Parent reviewed manifest is missing: {parent_reviewed_path}. "
                    "Complete and export the parent review first."
                )
            try:
                parent_reviewed = json.loads(parent_reviewed_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReviewError(f"Cannot read parent reviewed manifest: {exc}") from exc
            reviewed, review_log_sha256 = build_inherited_reviewed_manifest(
                loaded,
                parent_loaded,
                parent_reviewed,
                project_root,
            )
        output_sha256 = write_reviewed_manifest(output_path, reviewed, loaded.profile.manifest_path)
    except ReviewError as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    print(f"Reviewed manifest: {output_path.resolve()}")
    print(f"Review log SHA-256: {review_log_sha256}")
    print(f"Output SHA-256: {output_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
