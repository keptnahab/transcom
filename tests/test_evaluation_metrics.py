from evaluation.metrics import (
    character_errors,
    normalize_semantic_text,
    normalize_text,
    semantic_word_errors,
    word_errors,
)


def test_normalize_text_is_case_and_punctuation_insensitive():
    assert normalize_text("Bühne, TEST!") == "bühne test"


def test_word_errors_reports_edit_types():
    counts = word_errors("eins zwei drei", "eins vier drei extra")

    assert counts.substitutions == 1
    assert counts.deletions == 0
    assert counts.insertions == 1
    assert counts.rate == 2 / 3


def test_character_errors_ignores_spaces_and_punctuation():
    counts = character_errors("A b!", "ac")

    assert counts.reference_length == 2
    assert counts.substitutions == 1
    assert counts.rate == 0.5


def test_semantic_normalization_collapses_numbers_percent_units_and_technical_ids():
    reference = "AES67 liegt bei minus achtzehn Dezibel und 72 Prozent auf 20 Zentimeter."
    hypothesis = "AES 67 liegt bei minus 18 Dezibel und 72% auf 20 cm."

    assert semantic_word_errors(reference, hypothesis).rate == 0.0
    assert "minus18" in normalize_semantic_text(reference)


def test_semantic_normalization_does_not_turn_articles_into_numbers():
    assert normalize_semantic_text("ein Fehler") == "ein fehler"
