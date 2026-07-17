from __future__ import annotations

import re


_SMALL = {
    0: "null",
    1: "eins",
    2: "zwei",
    3: "drei",
    4: "vier",
    5: "fünf",
    6: "sechs",
    7: "sieben",
    8: "acht",
    9: "neun",
    10: "zehn",
    11: "elf",
    12: "zwölf",
    13: "dreizehn",
    14: "vierzehn",
    15: "fünfzehn",
    16: "sechzehn",
    17: "siebzehn",
    18: "achtzehn",
    19: "neunzehn",
}
_TENS = {
    20: "zwanzig",
    30: "dreißig",
    40: "vierzig",
    50: "fünfzig",
    60: "sechzig",
    70: "siebzig",
    80: "achtzig",
    90: "neunzig",
}
_UNIT_STEMS = {
    1: "ein",
    2: "zwei",
    3: "drei",
    4: "vier",
    5: "fünf",
    6: "sechs",
    7: "sieben",
    8: "acht",
    9: "neun",
}


def german_integer_word(value: int) -> str | None:
    """Return the conventional single-word German cardinal for 0..999."""
    if not 0 <= value <= 999:
        return None
    if value < 20:
        return _SMALL[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        if unit == 0:
            return _TENS[tens * 10]
        return f"{_UNIT_STEMS[unit]}und{_TENS[tens * 10]}"
    hundreds, remainder = divmod(value, 100)
    prefix = "einhundert" if hundreds == 1 else f"{_SMALL[hundreds]}hundert"
    if remainder == 0:
        return prefix
    return f"{prefix}{german_integer_word(remainder)}"


def _word(match: re.Match[str]) -> str:
    value = german_integer_word(int(match.group("number")))
    return value if value is not None else match.group(0)


def _code(match: re.Match[str]) -> str:
    value = german_integer_word(int(match.group("number")))
    if value is None:
        return match.group(0)
    return f"{match.group('letter')} {value}"


def _percent(match: re.Match[str]) -> str:
    value = german_integer_word(int(match.group("number")))
    if value is None:
        return match.group(0)
    return f"{value} Prozent"


def normalize_german_spoken_numbers(text: str) -> str:
    """Render unambiguous integer tokens in the spoken form used by transcripts.

    Decimal values and multi-letter technical identifiers (AES67, SDI2), as
    well as digit-leading identifiers such as 4K, deliberately remain intact.
    """
    normalized = re.sub(
        r"(?<![\w.,])(?P<number>\d{1,3})\s*%",
        _percent,
        text,
    )
    normalized = re.sub(
        r"(?<![\w])(?P<letter>[A-ZÄÖÜ])(?P<number>\d{1,3})(?![\w])",
        _code,
        normalized,
    )
    return re.sub(
        r"(?<![\w.,:])(?P<number>\d{1,3})(?![\w])(?![.,:]\d)(?!\.)",
        _word,
        normalized,
    )


def normalize_german_spoken_number_segments(texts: list[str]) -> list[str]:
    """Normalize word-timestamp segments without corrupting split decimals/times."""
    result = list(texts)
    protected: set[int] = set()

    # Whisper may emit punctuation as its own word-timestamp segment. Protect
    # every numeric component of split decimals, times and ordinal dates.
    for index, text in enumerate(texts):
        stripped = text.strip()
        if stripped in {".", ",", ":"}:
            previous = texts[index - 1].strip() if index else ""
            following = texts[index + 1].strip() if index + 1 < len(texts) else ""
            if previous.isdigit() and (following.isdigit() or (stripped == "." and following)):
                protected.add(index - 1)
                if following.isdigit():
                    protected.add(index + 1)

    # Preserve split multi-letter identifiers such as [" AES", "67"], but
    # still normalize single-letter codes such as [" G", "5"].
    for index in range(1, len(texts)):
        if texts[index].strip().isdigit() and re.fullmatch(r"[A-ZÄÖÜ]{2,}", texts[index - 1].strip()):
            protected.add(index)

    for index, text in enumerate(texts):
        stripped = text.strip()
        if index in protected:
            continue
        if re.fullmatch(r"\d{1,3}", stripped):
            next_text = texts[index + 1].strip() if index + 1 < len(texts) else ""
            previous_text = texts[index - 1].strip() if index else ""
            if re.match(r"^[.,:]\d", next_text) or re.search(r"\d[.,:]$", previous_text):
                continue
            if next_text == "%":
                result[index] = normalize_german_spoken_numbers(text)
                leading = texts[index + 1][: len(texts[index + 1]) - len(texts[index + 1].lstrip())]
                result[index + 1] = f"{leading or ' '}Prozent"
                continue
        if stripped == "%" and index and texts[index - 1].strip().isdigit():
            continue
        result[index] = normalize_german_spoken_numbers(text)
    return result


def normalize_split_domain_terms(texts: list[str], glossary: tuple[str, ...]) -> list[str]:
    """Join a near-identical split compound only when it is in the glossary.

    This deliberately does not perform general spell correction. It addresses
    decoder/TTS boundaries such as ``Lass Aufnahme`` -> ``Lastaufnahme`` while
    requiring a long canonical term and an edit distance of at most one.
    """
    result = list(texts)
    canonical = {
        re.sub(r"[^\w]+", "", term, flags=re.UNICODE).casefold(): term
        for term in glossary
        if len(re.sub(r"[^\w]+", "", term, flags=re.UNICODE)) >= 8
    }
    if not canonical:
        return result

    for index in range(len(texts) - 1):
        left = re.sub(r"[^\w]+", "", texts[index], flags=re.UNICODE)
        right = re.sub(r"[^\w]+", "", texts[index + 1], flags=re.UNICODE)
        if not left or not right:
            continue
        joined = f"{left}{right}".casefold()
        match = next(
            (
                term
                for key, term in canonical.items()
                if _edit_distance_within(joined, key, 2 if len(key) >= 10 else 1)
            ),
            None,
        )
        if match is None:
            continue
        leading = texts[index][: len(texts[index]) - len(texts[index].lstrip())]
        trailing_match = re.search(r"[^\w\s]+\s*$", texts[index + 1], flags=re.UNICODE)
        trailing = trailing_match.group(0) if trailing_match else ""
        result[index] = f"{leading}{match}{trailing}"
        result[index + 1] = ""
    return result


def _edit_distance_within(left: str, right: str, limit: int) -> bool:
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_character != right_character),
                )
            )
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit
