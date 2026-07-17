from __future__ import annotations

from dataclasses import dataclass
import re


_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def _german_cardinals() -> dict[str, str]:
    numbers = {
        0: "null", 1: "eins", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf",
        6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn",
        11: "elf", 12: "zwölf", 13: "dreizehn", 14: "vierzehn",
        15: "fünfzehn", 16: "sechzehn", 17: "siebzehn", 18: "achtzehn",
        19: "neunzehn", 20: "zwanzig", 30: "dreißig", 40: "vierzig",
        50: "fünfzig", 60: "sechzig", 70: "siebzig", 80: "achtzig",
        90: "neunzig",
    }
    unit_stems = {
        1: "ein", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf",
        6: "sechs", 7: "sieben", 8: "acht", 9: "neun",
    }
    for tens in range(20, 100, 10):
        for unit in range(1, 10):
            numbers[tens + unit] = f"{unit_stems[unit]}und{numbers[tens]}"
    return {word: str(value) for value, word in numbers.items()}


_GERMAN_CARDINALS = _german_cardinals()


def normalize_text(text: str) -> str:
    return " ".join(match.group(0).casefold() for match in _WORD_RE.finditer(text or ""))


def normalize_characters(text: str) -> str:
    return "".join(normalize_text(text).split())


def normalize_semantic_text(text: str) -> str:
    """Conservative scoring normalization for common German ASR renderings.

    Raw WER/CER remain the release metrics. This secondary view only collapses
    clearly equivalent number, percent, unit, and compact technical spellings;
    it deliberately does not correct names or domain words.
    """
    prepared = (text or "").replace("%", " prozent ")
    tokens = normalize_text(prepared).split()
    normalized: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        mapped = _GERMAN_CARDINALS.get(token, token)
        if token == "minus" and index + 1 < len(tokens):
            next_value = _GERMAN_CARDINALS.get(tokens[index + 1], tokens[index + 1])
            if next_value.isdigit():
                normalized.append(f"minus{next_value}")
                index += 2
                continue
        if token in {"aes", "m"} and index + 1 < len(tokens) and tokens[index + 1].isdigit():
            normalized.append(f"{token}{tokens[index + 1]}")
            index += 2
            continue
        normalized.append({"cm": "zentimeter"}.get(mapped, mapped))
        index += 1
    return " ".join(normalized)


@dataclass(frozen=True)
class EditCounts:
    substitutions: int
    deletions: int
    insertions: int
    reference_length: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float:
        if self.reference_length == 0:
            return 0.0 if self.errors == 0 else 1.0
        return self.errors / self.reference_length


def edit_counts(reference: list[str], hypothesis: list[str]) -> EditCounts:
    # Each cell stores (cost, substitutions, deletions, insertions). The stable
    # tie-break order makes reports reproducible when multiple alignments exist.
    previous = [(index, 0, 0, index) for index in range(len(hypothesis) + 1)]
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [(ref_index, 0, ref_index, 0)]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            if ref_item == hyp_item:
                diagonal = previous[hyp_index - 1]
            else:
                cost, substitutions, deletions, insertions = previous[hyp_index - 1]
                diagonal = (cost + 1, substitutions + 1, deletions, insertions)
            cost, substitutions, deletions, insertions = previous[hyp_index]
            deletion = (cost + 1, substitutions, deletions + 1, insertions)
            cost, substitutions, deletions, insertions = current[hyp_index - 1]
            insertion = (cost + 1, substitutions, deletions, insertions + 1)
            current.append(min((diagonal, deletion, insertion), key=lambda item: item))
        previous = current
    _, substitutions, deletions, insertions = previous[-1]
    return EditCounts(substitutions, deletions, insertions, len(reference))


def word_errors(reference: str, hypothesis: str) -> EditCounts:
    return edit_counts(normalize_text(reference).split(), normalize_text(hypothesis).split())


def character_errors(reference: str, hypothesis: str) -> EditCounts:
    return edit_counts(list(normalize_characters(reference)), list(normalize_characters(hypothesis)))


def semantic_word_errors(reference: str, hypothesis: str) -> EditCounts:
    return edit_counts(normalize_semantic_text(reference).split(), normalize_semantic_text(hypothesis).split())
