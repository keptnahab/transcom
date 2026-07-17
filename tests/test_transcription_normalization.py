from backend.transcription.normalization import (
    german_integer_word,
    normalize_german_spoken_number_segments,
    normalize_german_spoken_numbers,
    normalize_split_domain_terms,
)


def test_german_integer_words_cover_common_transcript_values():
    assert german_integer_word(0) == "null"
    assert german_integer_word(16) == "sechzehn"
    assert german_integer_word(47) == "siebenundvierzig"
    assert german_integer_word(112) == "einhundertzwölf"
    assert german_integer_word(200) == "zweihundert"
    assert german_integer_word(1000) is None


def test_spoken_number_normalization_handles_codes_and_percent():
    assert normalize_german_spoken_numbers("Kanal 16 und G5 bei 0%.") == (
        "Kanal sechzehn und G fünf bei null Prozent."
    )


def test_spoken_number_normalization_preserves_technical_and_decimal_tokens():
    text = "AES67, SDI2, 4K, 23,5 und 3.14"
    assert normalize_german_spoken_numbers(text) == text


def test_spoken_number_normalization_distinguishes_comma_from_decimal_separator():
    assert normalize_german_spoken_numbers("Podest 2, danach 23,5 kg.") == (
        "Podest zwei, danach 23,5 kg."
    )


def test_spoken_number_normalization_preserves_dates_times_and_split_decimals():
    assert normalize_german_spoken_numbers("Am 14. Oktober um 19:30") == "Am 14. Oktober um 19:30"
    assert normalize_german_spoken_number_segments([" 0", ",4", " 19", ":30"]) == [
        " 0", ",4", " 19", ":30"
    ]


def test_spoken_number_normalization_joins_split_percent_rendering():
    assert normalize_german_spoken_number_segments([" 72", "%", " erreicht"]) == [
        " zweiundsiebzig", " Prozent", " erreicht"
    ]


def test_split_punctuation_and_identifiers_are_not_corrupted():
    assert normalize_german_spoken_number_segments([" 19", ":", "30"]) == [" 19", ":", "30"]
    assert normalize_german_spoken_number_segments([" 0", ",", "4"]) == [" 0", ",", "4"]
    assert normalize_german_spoken_number_segments([" AES", "67"]) == [" AES", "67"]
    assert normalize_german_spoken_number_segments([" 14", ".", " Oktober"]) == [" 14", ".", " Oktober"]


def test_glossary_repairs_only_near_identical_split_compounds():
    glossary = ("Lastaufnahme", "unterbrechen")
    assert normalize_split_domain_terms([" Lass", " Aufnahme", " unterbrechen."], glossary) == [
        " Lastaufnahme", "", " unterbrechen.",
    ]
    assert normalize_split_domain_terms([" Lasst", " Aufnahme"], glossary) == [
        " Lastaufnahme", "",
    ]
    assert normalize_split_domain_terms([" Lass", " die", " Aufnahme"], glossary) == [
        " Lass", " die", " Aufnahme",
    ]
    assert normalize_split_domain_terms([" Hoch", " Bewegung"], glossary) == [
        " Hoch", " Bewegung",
    ]
    assert normalize_split_domain_terms([" und", " verbrechen"], glossary) == [
        " unterbrechen", "",
    ]
