from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_REPORT_ROLES = (
    "baseline_clean",
    "baseline_intercom",
    "candidate_clean",
    "candidate_intercom",
    "short_latency",
    "human",
    "degraded",
)


class CandidateBindingError(ValueError):
    """Raised when a pre-freeze candidate binding is incomplete or invalid."""


def _load(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_sha256(value: object, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise CandidateBindingError(f"{label} must be a valid SHA-256")
    return digest


def _safe_bound_path(value: object, root: Path, label: str) -> Path:
    text = str(value or "").strip()
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts:
        raise CandidateBindingError(f"{label} must be a safe project-relative path")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise CandidateBindingError(f"{label} escapes project root") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise CandidateBindingError(f"{label} is not a regular file: {text}")
    return resolved


def _bound_bytes(record: object, root: Path, label: str) -> tuple[Path, bytes, str]:
    if not isinstance(record, dict):
        raise CandidateBindingError(f"{label} must be an object")
    path = _safe_bound_path(record.get("path"), root, f"{label}.path")
    expected = _valid_sha256(record.get("sha256"), f"{label}.sha256")
    data = path.read_bytes()
    actual = _sha256_bytes(data)
    if actual != expected:
        raise CandidateBindingError(
            f"{label} SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return path, data, actual


def _bound_json(record: object, root: Path, label: str) -> tuple[Path, dict[str, Any], str]:
    path, data, digest = _bound_bytes(record, root, label)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateBindingError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CandidateBindingError(f"{label} JSON root must be an object")
    return path, payload, digest


def _reviewed_reference_status(value: object) -> bool:
    status = str(value or "").strip().lower().replace("-", "_")
    if not status or "reviewed" not in status:
        return False
    tokens = set(status.split("_"))
    forbidden_tokens = {
        "not",
        "un",
        "unreviewed",
        "never",
        "pending",
        "unchecked",
        "unverified",
        "false",
    }
    forbidden_markers = ("notreviewed", "not_reviewed", "not_manually_reviewed")
    return not (tokens & forbidden_tokens) and not any(
        marker in status for marker in forbidden_markers
    )


def _scored_reference_issues(role: str, report: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    metric_keys = {
        "word_error_rate",
        "character_error_rate",
        "semantic_word_error_rate",
        "canonical_word_error_rate",
        "canonical_character_error_rate",
    }
    scored = 0
    issues: list[dict[str, Any]] = []
    for index, clip in enumerate(report.get("clip_results", [])):
        if not isinstance(clip, dict):
            issues.append({"role": role, "index": index, "reason": "clip_result_not_object"})
            continue
        is_scored = clip.get("reference") is not None or bool(metric_keys & set(clip))
        if not is_scored:
            continue
        scored += 1
        status = clip.get("reference_status")
        if not _reviewed_reference_status(status):
            issues.append(
                {
                    "role": role,
                    "index": index,
                    "audio_id": clip.get("audio_id", clip.get("clip_id")),
                    "reference_status": status,
                    "reason": "missing_or_unreviewed_reference_status",
                }
            )
    if scored == 0:
        issues.append({"role": role, "reason": "no_scored_clip_results"})
    return scored, issues


def _verify_degraded_source_references(
    report: dict[str, Any], source: dict[str, Any], label: str
) -> None:
    source_by_id: dict[str, dict[str, Any]] = {}
    for clip in source.get("clips", []):
        if not isinstance(clip, dict):
            continue
        clip_id = str(
            clip.get("derived_clip_id")
            or clip.get("audio_id")
            or clip.get("clip_id")
            or clip.get("id")
            or ""
        )
        if clip_id:
            source_by_id[clip_id] = clip
    for index, result in enumerate(report.get("clip_results", [])):
        if not isinstance(result, dict):
            continue
        result_id = str(result.get("audio_id") or result.get("clip_id") or "")
        source_clip = source_by_id.get(result_id)
        if source_clip is None:
            raise CandidateBindingError(
                f"{label} clip_result[{index}] is not bound to its degraded source clip"
            )
        source_reference = source_clip.get("reference")
        if not isinstance(source_reference, dict) or not isinstance(
            source_clip.get("parent_clip"), dict
        ):
            raise CandidateBindingError(
                f"{label} clip_result[{index}] lacks a status-bound source reference"
            )
        source_status = source_reference.get("reference_status")
        if not _reviewed_reference_status(source_status):
            raise CandidateBindingError(
                f"{label} clip_result[{index}] source reference is not reviewed: {source_status!r}"
            )
        if result.get("reference_status") != source_status:
            raise CandidateBindingError(
                f"{label} clip_result[{index}] reference status differs from its source"
            )
        if result.get("reference") != source_reference.get("reference_text"):
            raise CandidateBindingError(
                f"{label} clip_result[{index}] reference text differs from its source"
            )


def _verify_dev_source(
    record: object, root: Path, label: str
) -> tuple[Path, dict[str, Any], str]:
    path, payload, digest = _bound_json(record, root, label)
    usage = str(payload.get("usage") or payload.get("split") or "").lower()
    official_split = str(payload.get("official_split") or payload.get("split") or "").lower()
    if payload.get("is_holdout") is True or usage == "holdout" or official_split == "holdout":
        raise CandidateBindingError(f"{label} must bind development data, not holdout")
    if usage not in {"dev", "development"} and official_split not in {"dev", "development"}:
        raise CandidateBindingError(f"{label} does not declare a development split")
    return path, payload, digest


def _verify_report(
    role: str, record: object, root: Path
) -> tuple[Path, dict[str, Any], str]:
    if not isinstance(record, dict) or not isinstance(record.get("source"), dict):
        raise CandidateBindingError(f"dev_reports.{role} must bind report and source")
    path, report, digest = _bound_json(record, root, f"dev_reports.{role}")
    try:
        path.relative_to((root / "evaluation/results").resolve())
    except ValueError as exc:
        raise CandidateBindingError(f"dev_reports.{role} must be under evaluation/results") from exc
    source_path, source_manifest, source_digest = _verify_dev_source(
        record["source"], root, f"dev_reports.{role}.source"
    )
    if str(report.get("manifest_sha256") or "").lower() != source_digest:
        raise CandidateBindingError(f"dev_reports.{role} source-manifest hash mismatch")
    report_manifest = Path(str(report.get("manifest") or "")).name
    if report_manifest != source_path.name:
        raise CandidateBindingError(f"dev_reports.{role} source-manifest path mismatch")

    expected_benchmark = (
        "simulated-realtime-short-utterance-latency"
        if role == "short_latency" or role.startswith("warm_short_latency_runs[")
        else "hash-bound-clip-suite"
    )
    if report.get("benchmark") != expected_benchmark:
        raise CandidateBindingError(
            f"dev_reports.{role} has wrong benchmark type: {report.get('benchmark')!r}"
        )
    if expected_benchmark == "hash-bound-clip-suite":
        if report.get("all_clip_hashes_verified") is not True:
            raise CandidateBindingError(f"dev_reports.{role} did not verify all clip hashes")
        _rates(report)
    else:
        if report.get("all_hashes_verified") is not True or report.get("split") != "dev":
            raise CandidateBindingError(f"dev_reports.{role} is not a verified Dev latency run")
        _latency_transcript_signature(report)
        _warm_run_metrics(report)
    _scored, reference_issues = _scored_reference_issues(role, report)
    if reference_issues:
        first = reference_issues[0]
        raise CandidateBindingError(
            f"dev_reports.{role} has unreviewed scored references: {first}"
        )
    if role == "degraded":
        _verify_degraded_source_references(
            report, source_manifest, f"dev_reports.{role}"
        )
    return path, report, digest


def verify_candidate_binding(
    candidate_path: str | Path,
    *,
    expected_report_paths: dict[str, str | Path],
    expected_warm_paths: list[str | Path],
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    candidate_path = Path(candidate_path).resolve()
    try:
        candidate_path.relative_to(root)
    except ValueError as exc:
        raise CandidateBindingError("Candidate binding must be inside the project root") from exc
    data = candidate_path.read_bytes()
    candidate_digest = _sha256_bytes(data)
    try:
        candidate = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateBindingError("Candidate binding is not valid UTF-8 JSON") from exc
    if not isinstance(candidate, dict) or candidate.get("schema_version") != 2:
        raise CandidateBindingError(
            "Candidate must use schema_version=2; historical schema v1 is not pre-freeze bindable"
        )
    if candidate.get("freeze_state") != "pre_freeze":
        raise CandidateBindingError("Candidate freeze_state must be pre_freeze")
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        raise CandidateBindingError("Candidate must contain candidate_id")
    binding = candidate.get("acceptance_binding")
    if not isinstance(binding, dict) or binding.get("schema_version") != 1:
        raise CandidateBindingError("Candidate acceptance_binding schema is missing or unsupported")

    verified_static: dict[str, list[dict[str, str]]] = {}
    seen_static_paths: set[Path] = set()
    for group in ("code", "configuration", "catalogs"):
        records = binding.get(group)
        if not isinstance(records, list) or not records:
            raise CandidateBindingError(f"acceptance_binding.{group} must be non-empty")
        verified_static[group] = []
        for index, record in enumerate(records):
            path, payload, digest = _bound_bytes(
                record, root, f"acceptance_binding.{group}[{index}]"
            )
            if path in seen_static_paths:
                raise CandidateBindingError(f"Static artifact is bound more than once: {path}")
            seen_static_paths.add(path)
            if group == "catalogs":
                try:
                    catalog = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise CandidateBindingError("Bound catalog is not valid JSON") from exc
                if not isinstance(catalog, dict) or not str(catalog.get("catalog_id") or ""):
                    raise CandidateBindingError("Bound catalog has no catalog_id")
            verified_static[group].append(
                {"path": path.relative_to(root).as_posix(), "sha256": digest}
            )

    sealed = binding.get("sealed_manifests")
    if not isinstance(sealed, list) or not sealed:
        raise CandidateBindingError("acceptance_binding.sealed_manifests must be non-empty")
    verified_sealed = []
    for index, pair in enumerate(sealed):
        if not isinstance(pair, dict):
            raise CandidateBindingError(f"sealed_manifests[{index}] must be an object")
        manifest_path, _manifest_bytes, manifest_hash = _bound_bytes(
            pair.get("manifest"), root, f"sealed_manifests[{index}].manifest"
        )
        seal_path, seal_bytes, seal_hash = _bound_bytes(
            pair.get("seal"), root, f"sealed_manifests[{index}].seal"
        )
        if manifest_path == seal_path:
            raise CandidateBindingError("Sealed manifest and seal must be different files")
        try:
            seal_payload = json.loads(seal_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidateBindingError(f"sealed_manifests[{index}].seal is not JSON") from exc
        if not isinstance(seal_payload, dict):
            raise CandidateBindingError(f"sealed_manifests[{index}].seal root must be an object")
        directly_bound = seal_payload.get("manifest_sha256") == manifest_hash
        file_bound = any(
            isinstance(item, dict)
            and Path(str(item.get("path") or "")).name == manifest_path.name
            and item.get("sha256") == manifest_hash
            for item in seal_payload.get("files", [])
        )
        if not directly_bound and not file_bound:
            raise CandidateBindingError(
                f"sealed_manifests[{index}].seal does not bind the manifest hash"
            )
        verified_sealed.append(
            {
                "manifest": {
                    "path": manifest_path.relative_to(root).as_posix(),
                    "sha256": manifest_hash,
                },
                "seal": {
                    "path": seal_path.relative_to(root).as_posix(),
                    "sha256": seal_hash,
                },
            }
        )

    reports = binding.get("dev_reports")
    if not isinstance(reports, dict) or set(REQUIRED_REPORT_ROLES) - set(reports):
        missing = sorted(set(REQUIRED_REPORT_ROLES) - set(reports or {}))
        raise CandidateBindingError(f"Candidate is missing Dev report roles: {missing}")
    allowed_report_keys = set(REQUIRED_REPORT_ROLES) | {"warm_short_latency_runs"}
    unknown_report_keys = sorted(set(reports) - allowed_report_keys)
    if unknown_report_keys:
        raise CandidateBindingError(
            f"Candidate contains unsupported Dev report roles: {unknown_report_keys}"
        )
    verified_reports: dict[str, dict[str, Any]] = {}
    loaded_reports: dict[str, dict[str, Any]] = {}
    seen_report_paths: dict[Path, str] = {}
    for role in REQUIRED_REPORT_ROLES:
        path, report, digest = _verify_report(role, reports[role], root)
        if path in seen_report_paths:
            raise CandidateBindingError(
                f"Dev report roles {seen_report_paths[path]} and {role} bind the same file"
            )
        seen_report_paths[path] = role
        expected = Path(expected_report_paths[role]).resolve()
        if path != expected:
            raise CandidateBindingError(f"CLI path for {role} does not match candidate binding")
        loaded_reports[role] = report
        verified_reports[role] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": digest,
        }

    warm_records = reports.get("warm_short_latency_runs")
    if not isinstance(warm_records, list) or len(warm_records) != 3:
        raise CandidateBindingError("Candidate must bind exactly three warm short-latency runs")
    if len(expected_warm_paths) != 3:
        raise CandidateBindingError("CLI must supply exactly three warm short-latency runs")
    warm_reports = []
    verified_warm = []
    for index, (record, expected_path) in enumerate(zip(warm_records, expected_warm_paths)):
        role = f"warm_short_latency_runs[{index}]"
        path, report, digest = _verify_report(role, record, root)
        if path != Path(expected_path).resolve():
            raise CandidateBindingError(f"CLI path for warm run {index + 1} does not match binding")
        if index > 0 and path in seen_report_paths:
            raise CandidateBindingError(
                f"Warm run {index + 1} reuses Dev report role {seen_report_paths[path]}"
            )
        seen_report_paths[path] = role
        warm_reports.append(report)
        verified_warm.append(
            {"path": path.relative_to(root).as_posix(), "sha256": digest}
        )
    if verified_warm[0] != verified_reports["short_latency"]:
        raise CandidateBindingError("short_latency must be identical to warm run 1")

    return {
        "candidate_id": candidate_id,
        "candidate_binding_path": candidate_path.relative_to(root).as_posix(),
        "candidate_binding_sha256": candidate_digest,
        "static_artifacts": verified_static,
        "sealed_manifests": verified_sealed,
        "dev_reports": verified_reports,
        "warm_short_latency_runs": verified_warm,
        "loaded_reports": loaded_reports,
        "loaded_warm_reports": warm_reports,
    }


def _rates(report: dict[str, Any]) -> tuple[float, float]:
    # Product WER/CER uses the text displayed and exported. Hash-bound reports
    # retain the pre-normalization model metrics separately under `micro`.
    metrics = report.get("canonical_micro", report.get("micro", report))
    return float(metrics["word_error_rate"]), float(metrics["character_error_rate"])


def _gate(name: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def _subgroup_regressions(
    baseline: dict[str, Any], candidate: dict[str, Any], tolerance: float = 0.05
) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    for dimension, candidate_groups in candidate.get("groups", {}).items():
        baseline_groups = baseline.get("groups", {}).get(dimension, {})
        for group, candidate_values in candidate_groups.items():
            if group not in baseline_groups:
                continue
            candidate_metrics = candidate_values.get("canonical_micro", candidate_values["micro"])
            baseline_metrics = baseline_groups[group].get(
                "canonical_micro", baseline_groups[group]["micro"]
            )
            candidate_wer = float(candidate_metrics["word_error_rate"])
            baseline_wer = float(baseline_metrics["word_error_rate"])
            delta = candidate_wer - baseline_wer
            if delta > tolerance + 1e-12:
                regressions.append(
                    {
                        "dimension": dimension,
                        "group": group,
                        "baseline_wer": baseline_wer,
                        "candidate_wer": candidate_wer,
                        "delta": delta,
                    }
                )
    return regressions


def _latency_transcript_signature(report: dict[str, Any]) -> dict[str, Any]:
    top_keys = (
        "word_error_rate",
        "character_error_rate",
        "canonical_word_error_rate",
        "canonical_character_error_rate",
        "clips",
        "jobs",
        "successful_first_emits",
    )
    clip_keys = (
        "clip_id",
        "audio_id",
        "word_error_rate",
        "character_error_rate",
        "canonical_word_error_rate",
        "canonical_character_error_rate",
        "expected_command_id",
        "detected_command_id",
        "detected_command_ids",
    )
    signature = {
        "aggregate": {key: report.get(key) for key in top_keys},
        "clips": [
            {key: clip.get(key) for key in clip_keys}
            for clip in report.get("clip_results", [])
        ],
    }
    if not signature["clips"]:
        raise CandidateBindingError("Warm latency report contains no clip_results")
    required_metrics = ("word_error_rate", "character_error_rate")
    if any(report.get(key) is None for key in required_metrics):
        raise CandidateBindingError("Warm latency report lacks transcript metrics")
    return signature


def _signature_sha256(signature: dict[str, Any]) -> str:
    rendered = json.dumps(
        signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(rendered)


def _warm_run_metrics(report: dict[str, Any]) -> dict[str, float]:
    clips = report.get("clip_results", [])
    end_to_emit = [float(clip["end_to_emit_seconds"]) for clip in clips]
    first_usable = [float(clip["first_usable_emit_seconds"]) for clip in clips]
    rtf = float(report["real_time_factor"])
    values = end_to_emit + first_usable + [rtf]
    if not end_to_emit or not first_usable or any(
        not math.isfinite(value) or value < 0 for value in values
    ):
        raise CandidateBindingError("Warm latency report contains invalid latency metrics")
    return {
        "median_end_to_emit_seconds": float(statistics.median(end_to_emit)),
        "max_first_usable_emit_seconds": max(first_usable),
        "real_time_factor": rtf,
    }


def _warm_repeatability_gates(
    reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    count_ok = len(reports) == 3
    signatures: list[str] = []
    metrics: list[dict[str, float]] = []
    try:
        for report in reports:
            signatures.append(_signature_sha256(_latency_transcript_signature(report)))
            metrics.append(_warm_run_metrics(report))
    except (CandidateBindingError, KeyError, TypeError, ValueError):
        signatures = []
        metrics = []
    transcript_ok = count_ok and len(set(signatures)) == 1
    medians = [item["median_end_to_emit_seconds"] for item in metrics]
    if count_ok and len(medians) == 3:
        center = float(statistics.median(medians))
        if center == 0:
            variation = 0.0 if max(medians) == 0 else float("inf")
        else:
            variation = (max(medians) - min(medians)) / center
    else:
        variation = float("inf")
    each_first = count_ok and len(metrics) == 3 and all(
        item["max_first_usable_emit_seconds"] <= 3.5 for item in metrics
    )
    each_rtf = count_ok and len(metrics) == 3 and all(
        item["real_time_factor"] <= 0.5 for item in metrics
    )
    return [
        _gate("warm_repeat_count_exactly_3", count_ok, count=len(reports)),
        _gate(
            "warm_transcript_metrics_identical",
            transcript_ok,
            signature_sha256=signatures,
        ),
        _gate(
            "warm_median_end_to_emit_variation_at_most_15_percent",
            variation <= 0.15 + 1e-12,
            run_median_seconds=medians,
            relative_range_over_median=variation,
        ),
        _gate(
            "warm_each_max_first_usable_at_most_3_5_seconds",
            each_first,
            run_max_seconds=[item["max_first_usable_emit_seconds"] for item in metrics],
        ),
        _gate(
            "warm_each_rtf_at_most_0_5",
            each_rtf,
            run_rtf=[item["real_time_factor"] for item in metrics],
        ),
    ]


def _audio_evidence_identity(
    clip: dict[str, Any], *, fallback: str
) -> tuple[str, str | None, str | None]:
    audio_id = str(clip.get("audio_id") or clip.get("clip_id") or "").strip() or None
    audio_hash = str(clip.get("audio_sha256") or "").strip().lower() or None
    if audio_hash:
        return f"sha256:{audio_hash}", audio_id, audio_hash
    if audio_id:
        return f"audio_id:{audio_id}", audio_id, None
    return f"occurrence:{fallback}", None, None


def _group_audio_evidence(
    occurrences: list[tuple[str, int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for role, index, clip in occurrences:
        key, audio_id, audio_hash = _audio_evidence_identity(
            clip, fallback=f"{role}:{index}"
        )
        group = groups.setdefault(
            key,
            {
                "evidence_key": key,
                "audio_id": audio_id,
                "audio_sha256": audio_hash,
                "occurrences": [],
            },
        )
        group["occurrences"].append({"role": role, "index": index, "clip": clip})
    return list(groups.values())


def _safety_occurrence_error(clip: dict[str, Any]) -> bool:
    expected = clip.get("expected_command_id")
    if expected is not None:
        return (
            clip.get("detected_command_id") != expected
            or float(
                clip.get(
                    "semantic_word_error_rate", clip.get("word_error_rate", 1.0)
                )
            )
            >= 1.0
        )
    return float(clip.get("word_error_rate", 1.0)) != 0.0


def _error_occurrence_evidence(occurrence: dict[str, Any]) -> dict[str, Any]:
    clip = occurrence["clip"]
    return {
        "role": occurrence["role"],
        "index": occurrence["index"],
        "audio_id": clip.get("audio_id", clip.get("clip_id")),
        "audio_sha256": clip.get("audio_sha256"),
        "word_error_rate": clip.get("word_error_rate"),
        "semantic_word_error_rate": clip.get("semantic_word_error_rate"),
        "reference": clip.get("reference"),
        "hypothesis": clip.get("hypothesis"),
        "raw_hypothesis": clip.get("raw_hypothesis"),
        "expected_command_id": clip.get("expected_command_id"),
        "detected_command_id": clip.get("detected_command_id"),
    }


def assess(
    *,
    baseline_clean: dict[str, Any],
    baseline_intercom: dict[str, Any],
    candidate_clean: dict[str, Any],
    candidate_intercom: dict[str, Any],
    short_latency: dict[str, Any],
    human: dict[str, Any],
    degraded: dict[str, Any],
    warm_short_latency_runs: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    bc_wer, bc_cer = _rates(baseline_clean)
    bi_wer, bi_cer = _rates(baseline_intercom)
    cc_wer, cc_cer = _rates(candidate_clean)
    ci_wer, ci_cer = _rates(candidate_intercom)
    human_wer, human_cer = _rates(human)
    degraded_wer, degraded_cer = _rates(degraded)

    relative = {
        "clean_wer": 1.0 - cc_wer / bc_wer,
        "clean_cer": 1.0 - cc_cer / bc_cer,
        "intercom_wer": 1.0 - ci_wer / bi_wer,
        "intercom_cer": 1.0 - ci_cer / bi_cer,
    }
    subgroup_regressions = _subgroup_regressions(baseline_clean, candidate_clean)
    subgroup_regressions += _subgroup_regressions(baseline_intercom, candidate_intercom)

    safety_reports = {
        "candidate_clean": candidate_clean,
        "candidate_intercom": candidate_intercom,
        "short_latency": short_latency,
    }
    safety_occurrences = [
        (role, index, clip)
        for role, safety_report in safety_reports.items()
        for index, clip in enumerate(safety_report.get("clip_results", []))
        if clip.get("expected_command_id") is not None
    ]
    if not safety_occurrences:
        safety_occurrences = [
            ("candidate_intercom", index, clip)
            for index, clip in enumerate(candidate_intercom.get("clip_results", []))
            if clip.get("length_bucket") == "short"
            and "safety" in clip.get("categories", [])
        ]
    unique_safety = _group_audio_evidence(safety_occurrences)
    safety_errors = []
    for group in unique_safety:
        failed_occurrences = [
            _error_occurrence_evidence(occurrence)
            for occurrence in group["occurrences"]
            if _safety_occurrence_error(occurrence["clip"])
        ]
        if failed_occurrences:
            safety_errors.append(
                {
                    "evidence_key": group["evidence_key"],
                    "audio_id": group["audio_id"],
                    "audio_sha256": group["audio_sha256"],
                    "occurrence_count": len(group["occurrences"]),
                    "failed_occurrences": failed_occurrences,
                }
            )

    negative_occurrences = [
        (role, index, clip)
        for role, safety_report in safety_reports.items()
        for index, clip in enumerate(safety_report.get("clip_results", []))
        if clip.get("expected_command_id") is None
    ]
    unique_negative = _group_audio_evidence(negative_occurrences)
    false_activations = []
    for group in unique_negative:
        activated = [
            _error_occurrence_evidence(occurrence)
            for occurrence in group["occurrences"]
            if occurrence["clip"].get("detected_command_id") is not None
        ]
        if activated:
            false_activations.append(
                {
                    "evidence_key": group["evidence_key"],
                    "audio_id": group["audio_id"],
                    "audio_sha256": group["audio_sha256"],
                    "occurrence_count": len(group["occurrences"]),
                    "activated_occurrences": activated,
                }
            )
    unflagged_short = [
        clip.get("audio_id")
        for clip in candidate_intercom.get("clip_results", [])
        if clip.get("length_bucket") == "short" and not clip.get("requires_confirmation")
    ]
    max_first_usable = max(
        (float(clip["first_usable_emit_seconds"]) for clip in short_latency.get("clip_results", [])),
        default=float("inf"),
    )
    latency_rtf = float(short_latency["real_time_factor"])

    reference_reports = {
        "baseline_clean": baseline_clean,
        "baseline_intercom": baseline_intercom,
        "candidate_clean": candidate_clean,
        "candidate_intercom": candidate_intercom,
        "short_latency": short_latency,
        "human": human,
        "degraded": degraded,
    }
    scored_reference_count = 0
    reference_issues: list[dict[str, Any]] = []
    for role, scored_report in reference_reports.items():
        scored, issues = _scored_reference_issues(role, scored_report)
        scored_reference_count += scored
        reference_issues.extend(issues)

    gates = [
        _gate(
            "all_scored_references_reviewed",
            scored_reference_count > 0 and not reference_issues,
            scored_clips=scored_reference_count,
            errors=reference_issues,
        ),
        _gate("relative_wer_cer_reduction_at_least_20_percent", all(v >= 0.20 for v in relative.values()), **relative),
        _gate("synthetic_clean_absolute", cc_wer <= 0.20 and cc_cer <= 0.12, wer=cc_wer, cer=cc_cer),
        _gate("synthetic_intercom_absolute", ci_wer <= 0.20 and ci_cer <= 0.12, wer=ci_wer, cer=ci_cer),
        _gate("no_subgroup_wer_regression_over_0_05", not subgroup_regressions, regressions=subgroup_regressions),
        _gate("human_absolute", human_wer <= 0.20 and human_cer <= 0.12, wer=human_wer, cer=human_cer),
        _gate("degraded_absolute", degraded_wer <= 0.40 and degraded_cer <= 0.25, wer=degraded_wer, cer=degraded_cer),
        _gate(
            "short_safety_command_exact",
            bool(unique_safety) and not safety_errors,
            clips=len(unique_safety),
            unique_clips=len(unique_safety),
            occurrences=len(safety_occurrences),
            duplicate_occurrences=len(safety_occurrences) - len(unique_safety),
            errors=safety_errors,
        ),
        _gate(
            "no_false_command_activation",
            not false_activations,
            unique_clips=len(unique_negative),
            occurrences=len(negative_occurrences),
            duplicate_occurrences=len(negative_occurrences) - len(unique_negative),
            errors=false_activations,
        ),
        _gate("all_short_outputs_require_confirmation", not unflagged_short, unflagged_audio_ids=unflagged_short),
        _gate("short_first_usable_at_most_3_5_seconds", max_first_usable <= 3.5, max_seconds=max_first_usable),
        _gate("short_rtf_at_most_0_5", latency_rtf <= 0.5, rtf=latency_rtf),
    ]
    if warm_short_latency_runs is not None:
        gates.extend(_warm_repeatability_gates(warm_short_latency_runs))
    return {
        "schema_version": 1,
        "passed": all(gate["passed"] for gate in gates),
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check frozen TransCom ASR acceptance gates.")
    for name in (
        "baseline-clean",
        "baseline-intercom",
        "candidate-clean",
        "candidate-intercom",
        "short-latency",
        "human",
        "degraded",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--warm-short-latency",
        action="append",
        default=[],
        help="One warm short-latency report; repeat exactly three times for pre-freeze verification.",
    )
    parser.add_argument(
        "--candidate-binding",
        help="Schema-v2 pre-freeze candidate whose artifact/report hashes must match this invocation.",
    )
    args = parser.parse_args()
    report_paths = {
        role: getattr(args, role)
        for role in REQUIRED_REPORT_ROLES
    }
    binding_summary: dict[str, Any]
    try:
        if args.candidate_binding:
            verified = verify_candidate_binding(
                args.candidate_binding,
                expected_report_paths=report_paths,
                expected_warm_paths=args.warm_short_latency,
            )
            loaded = verified.pop("loaded_reports")
            warm_reports = verified.pop("loaded_warm_reports")
            binding_summary = {"verified": True, **verified}
        else:
            loaded = {role: _load(path) for role, path in report_paths.items()}
            warm_reports = [_load(path) for path in args.warm_short_latency]
            binding_summary = {
                "verified": False,
                "pre_freeze_eligible": False,
                "reason": "No schema-v2 candidate binding supplied; legacy assessment only.",
            }
        report = assess(
            baseline_clean=loaded["baseline_clean"],
            baseline_intercom=loaded["baseline_intercom"],
            candidate_clean=loaded["candidate_clean"],
            candidate_intercom=loaded["candidate_intercom"],
            short_latency=loaded["short_latency"],
            human=loaded["human"],
            degraded=loaded["degraded"],
            warm_short_latency_runs=warm_reports if warm_reports else None,
        )
    except (CandidateBindingError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report["candidate_binding"] = binding_summary
    report["pre_freeze_eligible"] = bool(
        binding_summary.get("verified") and report["passed"]
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
