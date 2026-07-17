from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.check_acceptance import (
    CandidateBindingError,
    assess,
    verify_candidate_binding,
)


def _clip_report(wer=0.10, cer=0.05, safety_wer=0.0):
    return {
        "micro": {"word_error_rate": wer, "character_error_rate": cer},
        "real_time_factor": 0.1,
        "groups": {"length_bucket": {"short": {"micro": {"word_error_rate": wer}}}},
        "clip_results": [
            {
                "audio_id": "safety-1",
                "length_bucket": "short",
                "categories": ["safety"],
                "requires_confirmation": True,
                "word_error_rate": safety_wer,
                "reference": "Stopp",
                "reference_status": "manually_reviewed_against_audio",
                "hypothesis": "Stopp" if safety_wer == 0 else "Start",
            }
        ],
    }


def _latency_report():
    return {
        "real_time_factor": 0.2,
        "clip_results": [
            {
                "audio_id": "latency-1",
                "reference": "Stopp",
                "reference_status": "manually_reviewed_against_audio",
                "word_error_rate": 0.0,
                "character_error_rate": 0.0,
                "first_usable_emit_seconds": 2.9,
            }
        ],
    }


def _warm_latency_report(end_to_emit=1.0, first_usable=2.9, rtf=0.2, wer=0.1):
    return {
        "benchmark": "simulated-realtime-short-utterance-latency",
        "all_hashes_verified": True,
        "split": "dev",
        "word_error_rate": wer,
        "character_error_rate": 0.05,
        "canonical_word_error_rate": wer,
        "canonical_character_error_rate": 0.05,
        "clips": 2,
        "jobs": 2,
        "successful_first_emits": 2,
        "real_time_factor": rtf,
        "clip_results": [
            {
                "clip_id": "short-1",
                "word_error_rate": wer,
                "character_error_rate": 0.05,
                "canonical_word_error_rate": wer,
                "canonical_character_error_rate": 0.05,
                "expected_command_id": "safety-stop",
                "detected_command_id": "safety-stop",
                "detected_command_ids": ["safety-stop"],
                "reference": "Stopp",
                "reference_status": "manually_reviewed_against_audio",
                "end_to_emit_seconds": end_to_emit,
                "first_usable_emit_seconds": first_usable,
            },
            {
                "clip_id": "short-2",
                "word_error_rate": 0.0,
                "character_error_rate": 0.0,
                "canonical_word_error_rate": 0.0,
                "canonical_character_error_rate": 0.0,
                "expected_command_id": None,
                "detected_command_id": None,
                "detected_command_ids": [],
                "reference": "Weiter",
                "reference_status": "manually_reviewed_against_audio",
                "end_to_emit_seconds": end_to_emit,
                "first_usable_emit_seconds": first_usable,
            },
        ],
    }


def _assess_with_warm(runs):
    return assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=_clip_report(),
        candidate_intercom=_clip_report(),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
        warm_short_latency_runs=runs,
    )


def test_acceptance_passes_all_frozen_gates():
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=_clip_report(),
        candidate_intercom=_clip_report(),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )
    assert report["passed"] is True
    assert all(gate["passed"] for gate in report["gates"])


def test_acceptance_rejects_nonexact_safety_and_absolute_wer():
    candidate = _clip_report(0.21, 0.05, safety_wer=0.5)
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=deepcopy(candidate),
        candidate_intercom=deepcopy(candidate),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )
    failed = {gate["name"] for gate in report["gates"] if not gate["passed"]}
    assert report["passed"] is False
    assert "synthetic_clean_absolute" in failed
    assert "short_safety_command_exact" in failed


def test_acceptance_uses_frozen_command_id_for_closed_safety_mode():
    candidate = _clip_report(0.10, 0.05, safety_wer=0.5)
    clip = candidate["clip_results"][0]
    clip["expected_command_id"] = "safety_stop"
    clip["detected_command_id"] = "safety_stop"
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=deepcopy(candidate),
        candidate_intercom=deepcopy(candidate),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )

    safety_gate = next(
        gate for gate in report["gates"] if gate["name"] == "short_safety_command_exact"
    )
    assert safety_gate["passed"] is True


def test_acceptance_rejects_fully_wrong_raw_text_despite_matching_command_id():
    candidate = _clip_report(0.10, 0.05, safety_wer=1.0)
    clip = candidate["clip_results"][0]
    clip["expected_command_id"] = "safety_stop"
    clip["detected_command_id"] = "safety_stop"
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=deepcopy(candidate),
        candidate_intercom=deepcopy(candidate),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )

    safety_gate = next(
        gate for gate in report["gates"] if gate["name"] == "short_safety_command_exact"
    )
    assert safety_gate["passed"] is False


def test_acceptance_rejects_false_command_activation():
    candidate = _clip_report()
    candidate["clip_results"].append({
        "audio_id": "ordinary-1",
        "expected_command_id": None,
        "detected_command_id": "safety_stop",
        "hypothesis": "Alle Bewegungen stoppen!",
        "raw_hypothesis": "Alle bewegen",
    })
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=deepcopy(candidate),
        candidate_intercom=deepcopy(candidate),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )

    gate = next(gate for gate in report["gates"] if gate["name"] == "no_false_command_activation")
    assert gate["passed"] is False
    assert gate["evidence"]["unique_clips"] == 3
    assert gate["evidence"]["occurrences"] == 5
    error = gate["evidence"]["errors"][0]
    assert error["occurrence_count"] == 2
    assert {item["role"] for item in error["activated_occurrences"]} == {
        "candidate_clean",
        "candidate_intercom",
    }


def test_safety_evidence_deduplicates_by_audio_id_without_hiding_one_bad_occurrence():
    clean = _clip_report()
    intercom = _clip_report(safety_wer=1.0)
    clean["clip_results"][0].update(
        {"expected_command_id": "safety_stop", "detected_command_id": "safety_stop"}
    )
    intercom["clip_results"][0].update(
        {"expected_command_id": "safety_stop", "detected_command_id": None}
    )
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=clean,
        candidate_intercom=intercom,
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )

    gate = next(
        gate for gate in report["gates"] if gate["name"] == "short_safety_command_exact"
    )
    assert gate["passed"] is False
    assert gate["evidence"]["unique_clips"] == 1
    assert gate["evidence"]["occurrences"] == 2
    assert gate["evidence"]["duplicate_occurrences"] == 1
    error = gate["evidence"]["errors"][0]
    assert error["occurrence_count"] == 2
    assert [item["role"] for item in error["failed_occurrences"]] == [
        "candidate_intercom"
    ]


def test_safety_evidence_uses_audio_hash_to_distinguish_same_audio_id():
    clean = _clip_report()
    intercom = _clip_report()
    clean["clip_results"][0].update(
        {
            "audio_sha256": "a" * 64,
            "expected_command_id": "safety_stop",
            "detected_command_id": "safety_stop",
        }
    )
    intercom["clip_results"][0].update(
        {
            "audio_sha256": "b" * 64,
            "expected_command_id": "safety_stop",
            "detected_command_id": "safety_stop",
        }
    )
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=clean,
        candidate_intercom=intercom,
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )

    gate = next(
        gate for gate in report["gates"] if gate["name"] == "short_safety_command_exact"
    )
    assert gate["passed"] is True
    assert gate["evidence"]["unique_clips"] == 2
    assert gate["evidence"]["occurrences"] == 2


def test_acceptance_rejects_subgroup_regression_and_latency():
    baseline = _clip_report(0.50, 0.25)
    candidate = _clip_report(0.10, 0.05)
    candidate["groups"]["length_bucket"]["short"]["micro"]["word_error_rate"] = 0.60
    latency = _latency_report()
    latency["clip_results"][0]["first_usable_emit_seconds"] = 3.6
    report = assess(
        baseline_clean=baseline,
        baseline_intercom=baseline,
        candidate_clean=candidate,
        candidate_intercom=candidate,
        short_latency=latency,
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )
    failed = {gate["name"] for gate in report["gates"] if not gate["passed"]}
    assert "no_subgroup_wer_regression_over_0_05" in failed
    assert "short_first_usable_at_most_3_5_seconds" in failed


@pytest.mark.parametrize(
    "status",
    [None, "unreviewed", "notreviewed", "synthetic_v2_spec_not_manually_reviewed"],
)
def test_acceptance_rejects_missing_or_unreviewed_scored_reference_status(status):
    candidate = _clip_report()
    candidate["clip_results"][0]["reference_status"] = status
    report = assess(
        baseline_clean=_clip_report(0.50, 0.25),
        baseline_intercom=_clip_report(0.60, 0.30),
        candidate_clean=candidate,
        candidate_intercom=_clip_report(),
        short_latency=_latency_report(),
        human=_clip_report(0.08, 0.03),
        degraded=_clip_report(0.20, 0.10),
    )
    gate = next(
        gate for gate in report["gates"] if gate["name"] == "all_scored_references_reviewed"
    )
    assert gate["passed"] is False
    assert gate["evidence"]["errors"][0]["reference_status"] == status


def test_acceptance_allows_explicit_reviewed_reference_status():
    report = _assess_with_warm(
        [_warm_latency_report(1.0), _warm_latency_report(1.05), _warm_latency_report(1.1)]
    )
    gate = next(
        gate for gate in report["gates"] if gate["name"] == "all_scored_references_reviewed"
    )
    assert gate["passed"] is True


def test_warm_repeatability_accepts_three_identical_metric_runs_with_bounded_latency():
    report = _assess_with_warm(
        [
            _warm_latency_report(1.00),
            _warm_latency_report(1.05),
            _warm_latency_report(1.10),
        ]
    )
    warm = {gate["name"]: gate for gate in report["gates"] if gate["name"].startswith("warm_")}
    assert report["passed"] is True
    assert len(warm) == 5
    assert all(gate["passed"] for gate in warm.values())


def test_warm_repeatability_rejects_metric_drift_latency_variation_and_per_run_limits():
    runs = [
        _warm_latency_report(1.00),
        _warm_latency_report(1.16, first_usable=3.6),
        _warm_latency_report(1.00, rtf=0.51, wer=0.11),
    ]
    report = _assess_with_warm(runs)
    failed = {gate["name"] for gate in report["gates"] if not gate["passed"]}
    assert "warm_transcript_metrics_identical" in failed
    assert "warm_median_end_to_emit_variation_at_most_15_percent" in failed
    assert "warm_each_max_first_usable_at_most_3_5_seconds" in failed
    assert "warm_each_rtf_at_most_0_5" in failed


def _write_json(path: Path, payload: dict, root: Path = None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "path": (path.relative_to(root) if root else path).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _binding_fixture(tmp_path: Path):
    code = tmp_path / "backend/module.py"
    code.parent.mkdir(parents=True)
    code.write_text("VALUE = 1\n", encoding="utf-8")
    config = tmp_path / "config/settings.json"
    catalog = tmp_path / "evaluation/synthesis_v2/catalogs/safety.json"
    config_record = _write_json(config, {"language": "de"}, tmp_path)
    catalog_record = _write_json(catalog, {"catalog_id": "closed-v1"}, tmp_path)
    code_record = {
        "path": code.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
    }

    sealed_manifest = tmp_path / "evaluation/data/manifests/sealed.json"
    manifest_record = _write_json(sealed_manifest, {"is_holdout": True}, tmp_path)
    seal = tmp_path / "evaluation/data/manifests/sealed.seal.json"
    seal_record = _write_json(
        seal, {"manifest_sha256": manifest_record["sha256"], "sealed": True}, tmp_path
    )

    source = tmp_path / "evaluation/data/manifests/dev.json"
    source_record = _write_json(
        source,
        {
            "dataset_id": "dev-v1",
            "split": "dev",
            "is_holdout": False,
            "clips": [
                {
                    "derived_clip_id": "safety-1",
                    "parent_clip": {"id": "source-1"},
                    "reference": {
                        "reference_text": "Stopp",
                        "reference_status": "manually_reviewed_against_audio",
                    },
                }
            ],
        },
        tmp_path,
    )
    report_dir = tmp_path / "evaluation/results"
    reports = {}
    expected = {}
    for role in (
        "baseline_clean",
        "baseline_intercom",
        "candidate_clean",
        "candidate_intercom",
        "human",
        "degraded",
    ):
        payload = _clip_report()
        payload.update(
            {
                "benchmark": "hash-bound-clip-suite",
                "all_clip_hashes_verified": True,
                "manifest": str(source),
                "manifest_sha256": source_record["sha256"],
            }
        )
        record = _write_json(report_dir / f"{role}.json", payload, tmp_path)
        record["source"] = source_record
        reports[role] = record
        expected[role] = tmp_path / record["path"]

    warm_records = []
    warm_paths = []
    for index, end_to_emit in enumerate((1.0, 1.05, 1.1), start=1):
        payload = _warm_latency_report(end_to_emit)
        payload.update(
            {
                "manifest": str(source),
                "manifest_sha256": source_record["sha256"],
            }
        )
        record = _write_json(report_dir / f"warm-{index}.json", payload, tmp_path)
        record["source"] = source_record
        warm_records.append(record)
        warm_paths.append(tmp_path / record["path"])
    reports["short_latency"] = warm_records[0]
    reports["warm_short_latency_runs"] = warm_records
    expected["short_latency"] = warm_paths[0]

    candidate = {
        "schema_version": 2,
        "candidate_id": "candidate-test",
        "freeze_state": "pre_freeze",
        "acceptance_binding": {
            "schema_version": 1,
            "code": [code_record],
            "configuration": [config_record],
            "catalogs": [catalog_record],
            "sealed_manifests": [
                {"manifest": manifest_record, "seal": seal_record}
            ],
            "dev_reports": reports,
        },
    }
    candidate_path = tmp_path / "evaluation/CANDIDATE_TEST.json"
    _write_json(candidate_path, candidate)
    return candidate_path, expected, warm_paths, candidate


def test_candidate_binding_hashes_roles_sources_seals_and_warm_runs(tmp_path):
    candidate_path, expected, warm_paths, _candidate = _binding_fixture(tmp_path)
    verified = verify_candidate_binding(
        candidate_path,
        expected_report_paths=expected,
        expected_warm_paths=warm_paths,
        project_root=tmp_path,
    )
    assert verified["candidate_id"] == "candidate-test"
    assert len(verified["warm_short_latency_runs"]) == 3
    assert verified["dev_reports"]["short_latency"] == verified["warm_short_latency_runs"][0]


def test_candidate_binding_rejects_tampering_arbitrary_json_and_legacy_schema(tmp_path):
    candidate_path, expected, warm_paths, candidate = _binding_fixture(tmp_path)
    bound_report = Path(expected["candidate_clean"])
    bound_report.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CandidateBindingError, match="SHA-256 mismatch"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )

    source_record = candidate["acceptance_binding"]["dev_reports"]["candidate_clean"]["source"]
    arbitrary = _clip_report()
    arbitrary.update(
        {
            "benchmark": "arbitrary-json",
            "all_clip_hashes_verified": True,
            "manifest": str(tmp_path / source_record["path"]),
            "manifest_sha256": source_record["sha256"],
        }
    )
    replacement = _write_json(bound_report, arbitrary, tmp_path)
    replacement["source"] = source_record
    candidate["acceptance_binding"]["dev_reports"]["candidate_clean"] = replacement
    _write_json(candidate_path, candidate)
    with pytest.raises(CandidateBindingError, match="wrong benchmark type"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )

    candidate["schema_version"] = 1
    _write_json(candidate_path, candidate)
    with pytest.raises(CandidateBindingError, match="schema_version=2"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )


def test_candidate_binding_rejects_duplicate_and_unknown_report_roles(tmp_path):
    candidate_path, expected, warm_paths, candidate = _binding_fixture(tmp_path)
    candidate["acceptance_binding"]["dev_reports"]["candidate_clean"] = candidate[
        "acceptance_binding"
    ]["dev_reports"]["baseline_clean"]
    expected["candidate_clean"] = expected["baseline_clean"]
    _write_json(candidate_path, candidate)
    with pytest.raises(CandidateBindingError, match="bind the same file"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )

    candidate_path, expected, warm_paths, candidate = _binding_fixture(tmp_path / "unknown")
    candidate["acceptance_binding"]["dev_reports"]["unreviewed"] = candidate[
        "acceptance_binding"
    ]["dev_reports"]["human"]
    _write_json(candidate_path, candidate)
    with pytest.raises(CandidateBindingError, match="unsupported Dev report roles"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path / "unknown",
        )


def test_candidate_binding_rejects_unreviewed_scored_report_reference(tmp_path):
    candidate_path, expected, warm_paths, candidate = _binding_fixture(tmp_path)
    record = candidate["acceptance_binding"]["dev_reports"]["candidate_clean"]
    report_path = tmp_path / record["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["clip_results"][0]["reference_status"] = "unreviewed"
    replacement = _write_json(report_path, report, tmp_path)
    replacement["source"] = record["source"]
    candidate["acceptance_binding"]["dev_reports"]["candidate_clean"] = replacement
    _write_json(candidate_path, candidate)

    with pytest.raises(CandidateBindingError, match="unreviewed scored references"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )


def test_candidate_binding_rejects_degraded_status_not_bound_to_reviewed_source(tmp_path):
    candidate_path, expected, warm_paths, candidate = _binding_fixture(tmp_path)
    reports = candidate["acceptance_binding"]["dev_reports"]
    old_record = reports["degraded"]
    source_path = tmp_path / "evaluation/data/manifests/degraded-dev.json"
    source_record = _write_json(
        source_path,
        {
            "dataset_id": "degraded-dev-v1",
            "split": "dev",
            "is_holdout": False,
            "clips": [
                {
                    "derived_clip_id": "safety-1",
                    "parent_clip": {"id": "source-1"},
                    "reference": {
                        "reference_text": "Stopp",
                        "reference_status": "source_not_manually_reviewed",
                    },
                }
            ],
        },
        tmp_path,
    )
    report_path = tmp_path / old_record["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["manifest"] = str(source_path)
    report["manifest_sha256"] = source_record["sha256"]
    replacement = _write_json(report_path, report, tmp_path)
    replacement["source"] = source_record
    reports["degraded"] = replacement
    _write_json(candidate_path, candidate)

    with pytest.raises(CandidateBindingError, match="source reference is not reviewed"):
        verify_candidate_binding(
            candidate_path,
            expected_report_paths=expected,
            expected_warm_paths=warm_paths,
            project_root=tmp_path,
        )
