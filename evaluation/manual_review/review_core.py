from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = "transcom-manual-reference-review-v1"
REVIEWED_REFERENCE_STATUS = "manually_audio_reviewed"
INHERITED_REFERENCE_STATUS = "manually_audio_reviewed_parent_inherited"
REVIEWER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReviewError(ValueError):
    """Raised when review evidence is incomplete, stale, or malformed."""


@dataclass(frozen=True)
class ReviewProfile:
    profile_id: str
    label: str
    group: str
    split: str
    manifest_path: Path
    review_log_path: Path
    mode: str = "manual"
    parent_profile_id: str | None = None
    transformation_manifest_path: Path | None = None
    seal_path: Path | None = None
    reviewed_output_path: Path | None = None


@dataclass(frozen=True)
class LoadedManifest:
    profile: ReviewProfile
    data: dict[str, Any]
    source_sha256: str

    @property
    def clips(self) -> list[dict[str, Any]]:
        return self.data["clips"]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_under(root: Path, path: Path, *, description: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ReviewError(f"{description} escapes project root: {path}")
    return resolved


def load_profiles(config_path: Path, project_root: Path) -> dict[str, ReviewProfile]:
    config_path = config_path.resolve()
    project_root = project_root.resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Cannot read profile configuration: {exc}") from exc
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError("Unsupported review profile schema")
    rows = raw.get("profiles")
    if not isinstance(rows, list) or not rows:
        raise ReviewError("Profile configuration must contain a non-empty profiles list")

    profiles: dict[str, ReviewProfile] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReviewError("Every review profile must be an object")
        profile_id = row.get("id")
        if not isinstance(profile_id, str) or not REVIEWER_ID_RE.fullmatch(profile_id):
            raise ReviewError(f"Invalid profile id: {profile_id!r}")
        if profile_id in profiles:
            raise ReviewError(f"Duplicate profile id: {profile_id}")
        manifest_value = row.get("manifest")
        log_value = row.get("review_log")
        if not isinstance(manifest_value, str) or not isinstance(log_value, str):
            raise ReviewError(f"Profile {profile_id} needs manifest and review_log paths")
        manifest_path = _resolve_under(
            project_root,
            project_root / manifest_value,
            description="Manifest path",
        )
        review_log_path = _resolve_under(
            project_root,
            project_root / log_value,
            description="Review log path",
        )
        mode = row.get("mode", "manual")
        if mode not in {"manual", "inherited"}:
            raise ReviewError(f"Profile {profile_id} has invalid mode {mode!r}")
        parent_profile_id = row.get("parent_profile")
        transform_value = row.get("transformation_manifest")
        seal_value = row.get("seal")
        reviewed_output_value = row.get("reviewed_output")
        if not isinstance(reviewed_output_value, str):
            raise ReviewError(f"Profile {profile_id} needs a reviewed_output path")
        if mode == "manual" and any(value is not None for value in (parent_profile_id, transform_value, seal_value)):
            raise ReviewError(f"Manual profile {profile_id} must not define inheritance inputs")
        if mode == "inherited":
            if not isinstance(parent_profile_id, str) or not isinstance(transform_value, str):
                raise ReviewError(
                    f"Inherited profile {profile_id} needs parent_profile and transformation_manifest"
                )
        transformation_manifest_path = None
        if isinstance(transform_value, str):
            transformation_manifest_path = _resolve_under(
                project_root,
                project_root / transform_value,
                description="Transformation manifest path",
            )
        seal_path = None
        if isinstance(seal_value, str):
            seal_path = _resolve_under(project_root, project_root / seal_value, description="Seal path")
        reviewed_output_path = None
        if reviewed_output_value is not None:
            reviewed_output_path = _resolve_under(
                project_root,
                project_root / reviewed_output_value,
                description="Reviewed output path",
            )
            if not reviewed_output_path.name.endswith("_reviewed_v1.json"):
                raise ReviewError(f"Profile {profile_id} reviewed_output must end in _reviewed_v1.json")
        profiles[profile_id] = ReviewProfile(
            profile_id=profile_id,
            label=str(row.get("label", profile_id)),
            group=str(row.get("group", "")),
            split=str(row.get("split", "")),
            manifest_path=manifest_path,
            review_log_path=review_log_path,
            mode=mode,
            parent_profile_id=parent_profile_id,
            transformation_manifest_path=transformation_manifest_path,
            seal_path=seal_path,
            reviewed_output_path=reviewed_output_path,
        )
    for profile in profiles.values():
        if profile.mode == "inherited":
            parent = profiles.get(profile.parent_profile_id or "")
            if parent is None:
                raise ReviewError(f"Profile {profile.profile_id} references an unknown parent profile")
            if parent.mode != "manual":
                raise ReviewError(f"Profile {profile.profile_id} parent must be a manual profile")
            if parent.split != profile.split:
                raise ReviewError(f"Profile {profile.profile_id} and its parent must use the same split")
    return profiles


def load_manifest(profile: ReviewProfile) -> LoadedManifest:
    try:
        raw = profile.manifest_path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Cannot read source manifest for {profile.profile_id}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list) or not data["clips"]:
        raise ReviewError("Source manifest must contain a non-empty clips list")
    if not all(isinstance(clip, dict) for clip in data["clips"]):
        raise ReviewError("Every manifest clip must be an object")
    return LoadedManifest(profile=profile, data=data, source_sha256=sha256_bytes(raw))


def clip_id(clip: Mapping[str, Any], index: int) -> str:
    for key in ("id", "audio_id", "derived_clip_id"):
        value = clip.get(key)
        if value is not None and str(value).strip():
            return str(value)
    raise ReviewError(f"Clip at index {index} has no stable id")


def reference_payload(clip: Mapping[str, Any]) -> dict[str, Any]:
    nested = clip.get("reference")
    if isinstance(nested, dict):
        return deepcopy(nested)
    payload = {
        key: deepcopy(value)
        for key, value in clip.items()
        if "reference" in key.lower() and key != "review_log_hash"
    }
    if not payload:
        raise ReviewError("Clip has no reference fields")
    return payload


def display_reference(clip: Mapping[str, Any]) -> str:
    nested = clip.get("reference")
    if isinstance(nested, dict) and isinstance(nested.get("reference_text"), str):
        return nested["reference_text"]
    value = clip.get("reference_text")
    if not isinstance(value, str) or not value.strip():
        raise ReviewError("Clip has no displayable reference_text")
    return value


def declared_audio_sha256(clip: Mapping[str, Any]) -> str:
    value = clip.get("sha256")
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReviewError("Clip has no valid lowercase SHA-256 audio hash")
    return value


def resolve_audio_path(loaded: LoadedManifest, project_root: Path, index: int) -> Path:
    try:
        clip = loaded.clips[index]
    except IndexError as exc:
        raise ReviewError(f"Clip index out of range: {index}") from exc
    data_path = clip.get("data_path")
    relative_path = clip.get("path")
    if isinstance(data_path, str) and data_path:
        candidate = project_root / data_path
    elif isinstance(relative_path, str) and relative_path:
        candidate = loaded.profile.manifest_path.parent / relative_path
    else:
        raise ReviewError(f"Clip {clip_id(clip, index)} has no audio path")
    resolved = _resolve_under(project_root, candidate, description="Audio path")
    if not resolved.is_file():
        raise ReviewError(f"Audio file is missing: {resolved}")
    return resolved


def clip_binding(clip: Mapping[str, Any], index: int) -> dict[str, str]:
    return {
        "clip_id": clip_id(clip, index),
        "clip_sha256": sha256_bytes(canonical_json_bytes(clip)),
        "declared_audio_sha256": declared_audio_sha256(clip),
        "reference_sha256": sha256_bytes(canonical_json_bytes(reference_payload(clip))),
    }


def verify_audio_binding(loaded: LoadedManifest, project_root: Path, index: int) -> tuple[Path, str]:
    clip = loaded.clips[index]
    audio_path = resolve_audio_path(loaded, project_root, index)
    actual_sha256 = sha256_file(audio_path)
    declared_sha256 = declared_audio_sha256(clip)
    if actual_sha256 != declared_sha256:
        raise ReviewError(
            f"Audio hash mismatch for {clip_id(clip, index)}: "
            f"manifest={declared_sha256}, file={actual_sha256}"
        )
    return audio_path, actual_sha256


def _read_log_bytes(handle: Any) -> bytes:
    handle.seek(0)
    return handle.read()


def parse_review_log(payload: bytes) -> list[dict[str, Any]]:
    if not payload:
        return []
    if not payload.endswith(b"\n"):
        raise ReviewError("Review log is truncated: final newline is missing")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise ReviewError(f"Blank line in review log at line {line_number}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"Invalid JSON in review log line {line_number}") from exc
        if not isinstance(event, dict):
            raise ReviewError(f"Review log line {line_number} is not an object")
        events.append(event)
    return events


def validate_review_events(
    events: Iterable[dict[str, Any]],
    loaded: LoadedManifest,
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for event_number, event in enumerate(events, start=1):
        event_hash = event.get("event_sha256")
        body = {key: value for key, value in event.items() if key != "event_sha256"}
        expected_hash = sha256_bytes(canonical_json_bytes(body))
        if event_hash != expected_hash:
            raise ReviewError(f"Review log event {event_number} hash is invalid")
        if event.get("previous_event_sha256") != previous_hash:
            raise ReviewError(f"Review log chain is broken at event {event_number}")
        if event.get("schema_version") != SCHEMA_VERSION or event.get("event_type") != "decision":
            raise ReviewError(f"Unsupported review event at line {event_number}")
        if event.get("profile_id") != loaded.profile.profile_id:
            raise ReviewError(f"Review event {event_number} belongs to another profile")
        if event.get("source_manifest_sha256") != loaded.source_sha256:
            raise ReviewError(f"Review event {event_number} is bound to a different manifest")
        index = event.get("clip_index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(loaded.clips):
            raise ReviewError(f"Invalid clip index in review event {event_number}")
        binding = clip_binding(loaded.clips[index], index)
        for field, expected in binding.items():
            if event.get(field) != expected:
                raise ReviewError(f"Review event {event_number} has stale {field}")
        decision = event.get("decision")
        if decision not in {"PASS", "FAIL"}:
            raise ReviewError(f"Invalid decision in review event {event_number}")
        reviewer_id = event.get("reviewer_id")
        if not isinstance(reviewer_id, str) or not REVIEWER_ID_RE.fullmatch(reviewer_id):
            raise ReviewError(f"Invalid reviewer id in review event {event_number}")
        reviewed_at = event.get("reviewed_at_utc")
        if not isinstance(reviewed_at, str) or not reviewed_at.endswith("Z"):
            raise ReviewError(f"Invalid UTC timestamp in review event {event_number}")
        note = event.get("note")
        if not isinstance(note, str) or len(note) > 4000:
            raise ReviewError(f"Invalid note in review event {event_number}")
        if decision == "FAIL" and not note.strip():
            raise ReviewError(f"FAIL event {event_number} must contain a note")
        previous_hash = event_hash
        validated.append(event)
    return validated


def read_and_validate_log(loaded: LoadedManifest) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        payload = loaded.profile.review_log_path.read_bytes()
    except FileNotFoundError:
        return b"", []
    except OSError as exc:
        raise ReviewError(f"Cannot read review log: {exc}") from exc
    events = parse_review_log(payload)
    return payload, validate_review_events(events, loaded)


def latest_decisions(events: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    for event in events:
        latest[event["clip_index"]] = event
    return latest


def append_decision(
    loaded: LoadedManifest,
    project_root: Path,
    *,
    index: int,
    decision: str,
    note: str,
    reviewer_id: str,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if loaded.profile.mode != "manual":
        raise ReviewError("Derived profiles cannot receive manual decisions; use parent inheritance")
    decision = decision.upper()
    note = note.strip()
    reviewer_id = reviewer_id.strip()
    if decision not in {"PASS", "FAIL"}:
        raise ReviewError("Decision must be PASS or FAIL")
    if not REVIEWER_ID_RE.fullmatch(reviewer_id):
        raise ReviewError("Reviewer id must be 1-64 safe identifier characters")
    if len(note) > 4000:
        raise ReviewError("Note is longer than 4000 characters")
    if decision == "FAIL" and not note:
        raise ReviewError("A FAIL decision requires a note")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(loaded.clips):
        raise ReviewError("Clip index is out of range")
    if "manual_audio_review" in loaded.data:
        raise ReviewError("Reviewed manifests cannot be used as manual review sources")

    # Refuse to bind a human decision to stale manifest or audio bytes.
    current = load_manifest(loaded.profile)
    if current.source_sha256 != loaded.source_sha256:
        raise ReviewError("Source manifest changed during review; restart with a new log")
    _, actual_audio_sha256 = verify_audio_binding(current, project_root, index)

    log_path = loaded.profile.review_log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        payload = _read_log_bytes(handle)
        events = validate_review_events(parse_review_log(payload), current)
        previous_hash = events[-1]["event_sha256"] if events else None
        timestamp = (now or (lambda: datetime.now(timezone.utc)))()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ReviewError("Review timestamp must be timezone-aware")
        reviewed_at = timestamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        binding = clip_binding(current.clips[index], index)
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "decision",
            "profile_id": current.profile.profile_id,
            "source_manifest_sha256": current.source_sha256,
            "clip_index": index,
            **binding,
            "verified_audio_sha256": actual_audio_sha256,
            "decision": decision,
            "note": note,
            "reviewer_id": reviewer_id,
            "reviewed_at_utc": reviewed_at,
            "previous_event_sha256": previous_hash,
        }
        event["event_sha256"] = sha256_bytes(canonical_json_bytes(event))
        handle.seek(0, os.SEEK_END)
        handle.write(canonical_json_bytes(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event


def completion_summary(loaded: LoadedManifest, events: Iterable[dict[str, Any]]) -> dict[str, int]:
    latest = latest_decisions(events)
    counts = {"total": len(loaded.clips), "pass": 0, "fail": 0, "pending": 0}
    for index in range(len(loaded.clips)):
        event = latest.get(index)
        if event is None:
            counts["pending"] += 1
        elif event["decision"] == "PASS":
            counts["pass"] += 1
        else:
            counts["fail"] += 1
    return counts


def _set_reviewed_fields(clip: dict[str, Any], review_log_sha256: str) -> None:
    nested = clip.get("reference")
    if isinstance(nested, dict) and "reference_status" in nested:
        nested["reference_status"] = REVIEWED_REFERENCE_STATUS
    else:
        clip["reference_status"] = REVIEWED_REFERENCE_STATUS
    clip["review_log_hash"] = review_log_sha256


def _allowed_review_projection(clip: Mapping[str, Any]) -> dict[str, Any]:
    projection = deepcopy(dict(clip))
    projection.pop("review_log_hash", None)
    projection.pop("manual_review_inheritance", None)
    nested = projection.get("reference")
    if isinstance(nested, dict) and "reference_status" in nested:
        nested.pop("reference_status")
    else:
        projection.pop("reference_status", None)
    return projection


def build_reviewed_manifest(
    loaded: LoadedManifest,
    project_root: Path,
) -> tuple[dict[str, Any], str]:
    if loaded.profile.mode != "manual":
        raise ReviewError("This profile requires parent inheritance, not direct manual review")
    if "manual_audio_review" in loaded.data:
        raise ReviewError("Source manifest already contains manual review provenance")
    if any("review_log_hash" in clip or "manual_review_inheritance" in clip for clip in loaded.clips):
        raise ReviewError("Source clips already contain review output fields")
    log_payload, events = read_and_validate_log(loaded)
    latest = latest_decisions(events)
    summary = completion_summary(loaded, events)
    if summary["pending"] or summary["fail"]:
        raise ReviewError(
            "Review is not fully passed: "
            f"pass={summary['pass']}, fail={summary['fail']}, pending={summary['pending']}"
        )
    if len(latest) != len(loaded.clips):
        raise ReviewError("Review does not contain exactly one current decision per clip")

    for index, event in latest.items():
        _, actual_sha256 = verify_audio_binding(loaded, project_root, index)
        if event.get("verified_audio_sha256") != actual_sha256:
            raise ReviewError(f"Reviewed audio changed for clip {index}")

    review_log_sha256 = sha256_bytes(log_payload)
    output = deepcopy(loaded.data)
    if len(output["clips"]) != len(loaded.clips):
        raise ReviewError("Reviewed manifest clip count changed unexpectedly")
    for original, reviewed in zip(loaded.clips, output["clips"]):
        _set_reviewed_fields(reviewed, review_log_sha256)
        if _allowed_review_projection(reviewed) != _allowed_review_projection(original):
            raise ReviewError("Reviewed manifest modified immutable clip data")

    last_reviewed_at = max(event["reviewed_at_utc"] for event in latest.values())
    output["manual_audio_review"] = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": loaded.profile.profile_id,
        "source_manifest": str(loaded.profile.manifest_path.relative_to(project_root.resolve())),
        "source_manifest_sha256": loaded.source_sha256,
        "review_log": str(loaded.profile.review_log_path.relative_to(project_root.resolve())),
        "review_log_sha256": review_log_sha256,
        "reviewed_clip_count": len(loaded.clips),
        "reviewer_ids": sorted({event["reviewer_id"] for event in latest.values()}),
        "completed_at_utc": last_reviewed_at,
    }
    if output.get("scoring_authorized") is False:
        output["scoring_authorized"] = True
        output["scoring_authorization"] = {
            "basis": REVIEWED_REFERENCE_STATUS,
            "review_log_sha256": review_log_sha256,
            "authorized_clip_count": len(loaded.clips),
        }
    return output, review_log_sha256


def _reference_content_payload(clip: Mapping[str, Any]) -> dict[str, Any]:
    payload = reference_payload(clip)
    payload.pop("reference_status", None)
    return payload


def _recursive_contains(value: Any, needle: str) -> bool:
    if value == needle:
        return True
    if isinstance(value, dict):
        return any(_recursive_contains(child, needle) for child in value.values())
    if isinstance(value, list):
        return any(_recursive_contains(child, needle) for child in value)
    return False


def _verify_tree_seal(seal_path: Path, seal_data: Mapping[str, Any]) -> None:
    if seal_data.get("sealed") is not True:
        raise ReviewError("Transformation seal is not marked sealed")
    records = seal_data.get("files")
    if not isinstance(records, list) or not records:
        raise ReviewError("Transformation seal has no file inventory")
    root = seal_path.parent.resolve()
    expected_paths: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ReviewError(f"Invalid transformation seal record {index}")
        relative = record.get("path")
        expected_hash = record.get("sha256")
        expected_size = record.get("bytes")
        if not isinstance(relative, str) or not relative or relative in expected_paths:
            raise ReviewError(f"Invalid or duplicate sealed path at record {index}")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            raise ReviewError(f"Invalid sealed SHA-256 at record {index}")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
            raise ReviewError(f"Invalid sealed byte size at record {index}")
        path = _resolve_under(root, root / relative, description="Sealed file path")
        if not path.is_file():
            raise ReviewError(f"Sealed transformation file is missing: {relative}")
        if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
            raise ReviewError(f"Sealed transformation file changed: {relative}")
        expected_paths.add(Path(relative).as_posix())
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != seal_path.resolve()
    }
    if actual_paths != expected_paths:
        added = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        raise ReviewError(f"Transformation seal inventory mismatch: added={added}, missing={missing}")


def _parent_clip_id(clip: Mapping[str, Any], index: int) -> str:
    parent = clip.get("parent_clip")
    if isinstance(parent, dict) and parent.get("id") is not None:
        return str(parent["id"])
    return clip_id(clip, index)


def _verify_transformation_binding(
    loaded: LoadedManifest,
    project_root: Path,
) -> tuple[str, str | None]:
    transform_path = loaded.profile.transformation_manifest_path
    if transform_path is None or not transform_path.is_file():
        raise ReviewError("Transformation manifest is missing")
    transformation_sha256 = sha256_file(transform_path)
    source_manifest = loaded.data.get("source_manifest")
    source_sha256 = loaded.data.get("source_manifest_sha256")
    if source_manifest is not None:
        expected_path = (project_root.resolve() / source_manifest).resolve()
        if expected_path != transform_path.resolve():
            raise ReviewError("Derived manifest points to a different transformation manifest")
    if source_sha256 is not None and source_sha256 != transformation_sha256:
        raise ReviewError("Derived manifest transformation hash is stale")

    seal_sha256 = None
    if loaded.profile.seal_path is not None:
        seal_path = loaded.profile.seal_path
        if not seal_path.is_file():
            raise ReviewError("Required holdout seal is missing")
        try:
            seal_data = json.loads(seal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewError(f"Cannot validate transformation seal: {exc}") from exc
        if not isinstance(seal_data, dict):
            raise ReviewError("Transformation seal root must be an object")
        _verify_tree_seal(seal_path, seal_data)
        if not _recursive_contains(seal_data, transformation_sha256):
            raise ReviewError("Holdout seal does not bind the transformation manifest hash")
        seal_sha256 = sha256_file(seal_path)
    return transformation_sha256, seal_sha256


def build_inherited_reviewed_manifest(
    loaded: LoadedManifest,
    parent_loaded: LoadedManifest,
    parent_reviewed: Mapping[str, Any],
    project_root: Path,
) -> tuple[dict[str, Any], str]:
    if loaded.profile.mode != "inherited":
        raise ReviewError("Only an inherited profile can use parent review evidence")
    if loaded.profile.parent_profile_id != parent_loaded.profile.profile_id:
        raise ReviewError("Wrong parent review profile")
    if "manual_audio_review" in loaded.data:
        raise ReviewError("Source manifest already contains manual review provenance")
    if any("review_log_hash" in clip or "manual_review_inheritance" in clip for clip in loaded.clips):
        raise ReviewError("Source clips already contain review output fields")
    expected_parent, parent_log_sha256 = build_reviewed_manifest(parent_loaded, project_root)
    if dict(parent_reviewed) != expected_parent:
        raise ReviewError("Parent reviewed manifest is missing, stale, or not reproducible")

    transformation_sha256, seal_sha256 = _verify_transformation_binding(loaded, project_root)
    parent_manifest_sha256 = parent_loaded.source_sha256
    parent_metadata = loaded.data.get("parent")
    if isinstance(parent_metadata, dict):
        recorded_parent_manifest_sha256 = parent_metadata.get("manifest_sha256")
        if (
            recorded_parent_manifest_sha256 is not None
            and recorded_parent_manifest_sha256 != parent_manifest_sha256
        ):
            raise ReviewError("Derived manifest has a stale parent manifest hash")
    parent_by_id = {
        clip_id(clip, index): (index, clip)
        for index, clip in enumerate(parent_loaded.clips)
    }
    reviewed_parent_by_id = {
        clip_id(clip, index): clip
        for index, clip in enumerate(expected_parent["clips"])
    }
    output = deepcopy(loaded.data)
    for index, (original, reviewed) in enumerate(zip(loaded.clips, output["clips"])):
        parent_id = _parent_clip_id(original, index)
        if parent_id not in parent_by_id:
            raise ReviewError(f"Derived clip {clip_id(original, index)} has no reviewed parent {parent_id}")
        _, parent_clip = parent_by_id[parent_id]
        reviewed_parent_clip = reviewed_parent_by_id[parent_id]
        parent_audio_sha256 = declared_audio_sha256(parent_clip)
        nested_parent = original.get("parent_clip")
        if isinstance(nested_parent, dict) and nested_parent.get("sha256") != parent_audio_sha256:
            raise ReviewError(f"Derived clip {clip_id(original, index)} has a stale parent audio hash")
        if _reference_content_payload(original) != _reference_content_payload(parent_clip):
            raise ReviewError(f"Derived clip {clip_id(original, index)} changed the parent reference")
        if reviewed_parent_clip.get("review_log_hash") != parent_log_sha256:
            raise ReviewError(f"Parent clip {parent_id} lacks the expected review-log binding")
        verify_audio_binding(loaded, project_root, index)

        nested_reference = reviewed.get("reference")
        if isinstance(nested_reference, dict) and "reference_status" in nested_reference:
            nested_reference["reference_status"] = INHERITED_REFERENCE_STATUS
        else:
            reviewed["reference_status"] = INHERITED_REFERENCE_STATUS
        reviewed["review_log_hash"] = parent_log_sha256
        reviewed["manual_review_inheritance"] = {
            "schema_version": SCHEMA_VERSION,
            "parent_profile_id": parent_loaded.profile.profile_id,
            "parent_clip_id": parent_id,
            "parent_audio_sha256": parent_audio_sha256,
            "parent_manifest_sha256": parent_manifest_sha256,
            "parent_review_log_sha256": parent_log_sha256,
            "transformation_manifest": str(
                loaded.profile.transformation_manifest_path.relative_to(project_root.resolve())
            ),
            "transformation_manifest_sha256": transformation_sha256,
            "seal": (
                str(loaded.profile.seal_path.relative_to(project_root.resolve()))
                if loaded.profile.seal_path is not None
                else None
            ),
            "seal_sha256": seal_sha256,
        }
        if _allowed_review_projection(reviewed) != _allowed_review_projection(original):
            raise ReviewError("Inherited reviewed manifest modified immutable clip data")

    output["manual_audio_review"] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "parent_inherited",
        "profile_id": loaded.profile.profile_id,
        "source_manifest": str(loaded.profile.manifest_path.relative_to(project_root.resolve())),
        "source_manifest_sha256": loaded.source_sha256,
        "parent_profile_id": parent_loaded.profile.profile_id,
        "parent_manifest_sha256": parent_manifest_sha256,
        "parent_review_log_sha256": parent_log_sha256,
        "transformation_manifest_sha256": transformation_sha256,
        "seal_sha256": seal_sha256,
        "reviewed_clip_count": len(loaded.clips),
    }
    if output.get("scoring_authorized") is False:
        output["scoring_authorized"] = True
        output["scoring_authorization"] = {
            "basis": INHERITED_REFERENCE_STATUS,
            "parent_review_log_sha256": parent_log_sha256,
            "transformation_manifest_sha256": transformation_sha256,
            "authorized_clip_count": len(loaded.clips),
        }
    return output, parent_log_sha256


def default_output_path(source_manifest: Path) -> Path:
    return source_manifest.with_name(f"{source_manifest.stem}_reviewed_v1.json")


def profile_output_path(profile: ReviewProfile) -> Path:
    return profile.reviewed_output_path or default_output_path(profile.manifest_path)


def write_reviewed_manifest(output_path: Path, data: Mapping[str, Any], source_path: Path) -> str:
    output_path = output_path.resolve()
    source_path = source_path.resolve()
    if output_path == source_path:
        raise ReviewError("Reviewed manifest must not overwrite the source manifest")
    if not output_path.name.endswith("_reviewed_v1.json"):
        raise ReviewError("Reviewed manifest filename must end with _reviewed_v1.json")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if output_path.exists():
        if output_path.read_bytes() == payload:
            return sha256_bytes(payload)
        raise ReviewError(f"Refusing to overwrite different existing output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output_path.parent, prefix=f".{output_path.name}.", delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        temporary_path = Path(tmp.name)
    try:
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != payload:
                raise ReviewError(f"Refusing to overwrite different existing output: {output_path}")
    finally:
        temporary_path.unlink(missing_ok=True)
    return sha256_bytes(payload)
