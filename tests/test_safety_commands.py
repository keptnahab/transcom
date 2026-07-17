from __future__ import annotations

import json

import backend.config as cfg
from backend.transcription.engine import Segment, WhisperEngine
from backend.transcription.safety_commands import SafetyCommandCatalog
from backend.main import _accepted_segment_text
from backend.transcript.stabilizer import TranscriptStabilizer


def _catalog(tmp_path):
    path = tmp_path / "commands.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog_id": "test-v1",
                "language": "de-DE",
                "commands": [
                    {
                        "command_id": "stop",
                        "allowed_phrases": ["Alle Bewegungen stoppen!"],
                    },
                    {
                        "command_id": "brake",
                        "allowed_phrases": ["Haltebremse verriegeln!"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return SafetyCommandCatalog.load(path)


def test_catalog_loads_closed_command_schema_and_builds_prompt(tmp_path):
    catalog = _catalog(tmp_path)

    assert [command.command_id for command in catalog.commands] == ["stop", "brake"]
    prompt = catalog.prompt("Deutsch.")
    assert "Alle Bewegungen stoppen." in prompt
    assert "Haltebremse verriegeln." in prompt


def test_catalog_match_requires_exact_allowlisted_tokens(tmp_path):
    catalog = _catalog(tmp_path)

    accepted = catalog.match(
        "Haltebremse verrigeln", min_score=0.75, min_margin=0.04
    )
    rejected = catalog.match(
        "Bitte das Licht einschalten", min_score=0.82, min_margin=0.04
    )

    assert accepted.command is None
    assert accepted.best_candidate.command_id == "brake"
    assert accepted.best_candidate.text == "Haltebremse verriegeln!"
    assert accepted.rejection_reason == "not-allowlisted-exact"
    assert rejected.command is None
    assert rejected.best_candidate is not None


def test_engine_emits_canonical_command_with_raw_audit_text(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_SCORE", 0.75)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_MARGIN", 0.04)
    engine = WhisperEngine()
    engine._safety_catalog = _catalog(tmp_path)

    output = engine._apply_safety_catalog(
        [Segment("Haltebremse verriegeln", 0.1, 1.2, 0.8, is_word=True)]
    )

    assert len(output) == 1
    assert output[0].text == "Haltebremse verriegeln!"
    assert output[0].raw_text == "Haltebremse verriegeln"
    assert output[0].safety_command_id == "brake"
    assert output[0].requires_confirmation is True
    assert output[0].is_word is False


def test_engine_keeps_unresolved_transcript_without_command_id(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_SCORE", 0.82)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_MARGIN", 0.04)
    engine = WhisperEngine()
    engine._safety_catalog = _catalog(tmp_path)

    output = engine._apply_safety_catalog(
        [Segment("Bitte das Licht einschalten", 0.0, 1.0, 0.7)]
    )

    assert output[0].text == "Bitte das Licht einschalten"
    assert output[0].raw_text == output[0].text
    assert output[0].safety_command_id is None
    assert output[0].safety_match_score is not None
    assert output[0].requires_confirmation is True


def test_catalog_rejects_negations_and_opposite_actions(tmp_path):
    catalog = _catalog(tmp_path)
    negated = catalog.match(
        "Alle Bewegungen nicht stoppen", min_score=0.75, min_margin=0.04
    )
    # Use the frozen production catalog for its stage-lock command.
    production = SafetyCommandCatalog.load(
        cfg.PROJECT_ROOT / "evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json"
    )
    opposite = production.match(
        "Bühne sofort entsperren", min_score=0.82, min_margin=0.04
    )

    assert negated.command is None
    assert negated.rejection_reason == "negation:nicht"
    assert opposite.command is None
    assert opposite.rejection_reason == "opposite-action:entsperr"


def test_catalog_rejects_extra_negation_and_prohibition_language():
    production = SafetyCommandCatalog.load(
        cfg.PROJECT_ROOT / "evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json"
    )
    attempts = (
        "Alle Bewegungen keineswegs stoppen",
        "Alle Bewegungen nich stoppen",
        "Schutztor nisch schließen",
        "Schutztor nischt schließen",
        "Schutztor sicher schließen verhindern",
        "Schutztor sicher schließen unterlassen",
    )

    for text in attempts:
        match = production.match(text, min_score=0.82, min_margin=0.04)
        assert match.command is None
        assert match.best_candidate is not None
        assert match.rejection_reason is not None


def test_catalog_rejects_semantically_wrong_fuzzy_matches():
    production = SafetyCommandCatalog.load(
        cfg.PROJECT_ROOT / "evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json"
    )
    attempts = (
        "Last sicher fallen",
        "Not-Aus sofort auslassen",
        "Not-Aus sofort ausbleiben",
        "Energiezufuhr brennen",
    )

    for text in attempts:
        match = production.match(text, min_score=0.82, min_margin=0.04)
        assert match.command is None
        assert match.rejection_reason is not None


def test_raw_model_text_is_captured_before_normalization():
    segments = [Segment(" 67", 0.0, 0.5, 0.9, is_word=True)]
    WhisperEngine._capture_raw_segment_text(segments)
    segments[0].text = " siebenundsechzig"

    assert segments[0].raw_text == " 67"


def test_production_catalog_never_rejects_its_own_canonical_phrases():
    production = SafetyCommandCatalog.load(
        cfg.PROJECT_ROOT / "evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json"
    )

    for command in production.commands:
        match = production.match(command.text, min_score=0.82, min_margin=0.04)
        assert match.command == command
        assert match.rejection_reason is None


def test_bundled_product_catalog_matches_frozen_evaluation_catalog():
    bundled = SafetyCommandCatalog.load(cfg.SAFETY_COMMAND_CATALOG)
    frozen = SafetyCommandCatalog.load(
        cfg.PROJECT_ROOT / "evaluation/synthesis_v2/catalogs/safety_commands_closed_v1.json"
    )

    assert bundled.catalog_id == frozen.catalog_id
    assert bundled.language == frozen.language
    assert [(item.command_id, item.text) for item in bundled.commands] == [
        (item.command_id, item.text) for item in frozen.commands
    ]


def test_repeated_safety_events_bypass_generic_text_stabilizer():
    stabilizer = TranscriptStabilizer()
    segment = Segment(
        "Alle Bewegungen stoppen!",
        0.0,
        1.0,
        0.9,
        safety_match_score=1.0,
    )

    assert _accepted_segment_text(stabilizer, "ch1", segment) == segment.text
    assert _accepted_segment_text(stabilizer, "ch1", segment) == segment.text
