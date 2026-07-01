from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


@dataclass
class _Token:
    value: str
    start: int
    end: int


@dataclass
class TimedText:
    text: str
    start: float
    end: float
    confidence: float


class TranscriptStabilizer:
    def __init__(self, max_words: int = 80) -> None:
        self._max_words = max_words
        self._recent_by_channel: dict[str, list[str]] = {}

    def accept(self, channel_id: str, text: str) -> str:
        tokens = self._tokens(text)
        if not tokens:
            return ""
        recent = self._recent_by_channel.get(channel_id, [])
        values = [token.value for token in tokens]

        if self._is_contained(values, recent):
            return ""

        overlap = self._prefix_overlap(values, recent)
        if overlap >= len(tokens):
            return ""

        emitted = text[tokens[overlap].start :].strip() if overlap else text.strip()
        emitted_values = values[overlap:]
        if emitted_values:
            merged = recent + emitted_values
            self._recent_by_channel[channel_id] = merged[-self._max_words :]
        return emitted

    def reset(self, channel_id: str | None = None) -> None:
        if channel_id is None:
            self._recent_by_channel.clear()
        else:
            self._recent_by_channel.pop(channel_id, None)

    def _prefix_overlap(self, values: list[str], recent: list[str]) -> int:
        limit = min(len(values), len(recent), 12)
        for size in range(limit, 0, -1):
            if recent[-size:] == values[:size]:
                return size
        return 0

    def _is_contained(self, values: list[str], recent: list[str]) -> bool:
        if not values or len(values) > len(recent):
            return False
        window = len(values)
        return any(recent[i : i + window] == values for i in range(0, len(recent) - window + 1))

    def _tokens(self, text: str) -> list[_Token]:
        return [
            _Token(match.group(0).casefold(), match.start(), match.end())
            for match in _WORD_RE.finditer(text or "")
        ]


class TimedWordStabilizer:
    def __init__(self, duplicate_horizon_seconds: float = 4.0, timestamp_epsilon: float = 0.08) -> None:
        self._duplicate_horizon_seconds = duplicate_horizon_seconds
        self._timestamp_epsilon = timestamp_epsilon
        self._last_end_by_channel: dict[str, float] = {}
        self._recent_words_by_channel: dict[str, list[tuple[str, float]]] = {}

    def accept(
        self,
        channel_id: str,
        words: Iterable,
        window_start_ts: float,
        stable_until_ts: float,
    ) -> TimedText | None:
        last_end = self._last_end_by_channel.get(channel_id, float("-inf"))
        recent = self._recent_words_by_channel.setdefault(channel_id, [])
        accepted: list[tuple[str, str, float, float, float]] = []

        for word in sorted(words, key=lambda item: float(getattr(item, "end", 0.0))):
            raw_text = str(getattr(word, "text", "") or "")
            normalized = self._normalize_word(raw_text)
            if not normalized:
                continue
            abs_start = window_start_ts + float(getattr(word, "start", 0.0))
            abs_end = window_start_ts + float(getattr(word, "end", abs_start))
            if abs_end > stable_until_ts:
                continue
            if abs_start < last_end - self._timestamp_epsilon:
                continue
            if abs_end <= last_end + self._timestamp_epsilon:
                continue
            if self._is_recent_duplicate(normalized, abs_start, recent):
                continue
            confidence = float(getattr(word, "confidence", 0.0) or 0.0)
            accepted.append((raw_text, normalized, abs_start, abs_end, confidence))
            last_end = max(last_end, abs_end)
            recent.append((normalized, abs_end))

        if not accepted:
            return None

        recent[:] = recent[-16:]
        self._last_end_by_channel[channel_id] = last_end
        text = "".join(item[0] for item in accepted).strip()
        confidence_values = [item[4] for item in accepted if item[4] > 0]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 1.0
        return TimedText(
            text=text,
            start=accepted[0][2],
            end=accepted[-1][3],
            confidence=confidence,
        )

    def reset(self, channel_id: str | None = None) -> None:
        if channel_id is None:
            self._last_end_by_channel.clear()
            self._recent_words_by_channel.clear()
            return
        self._last_end_by_channel.pop(channel_id, None)
        self._recent_words_by_channel.pop(channel_id, None)

    def _is_recent_duplicate(self, normalized: str, abs_start: float, recent: list[tuple[str, float]]) -> bool:
        for recent_word, recent_end in reversed(recent[-6:]):
            if recent_word == normalized and abs_start <= recent_end + self._duplicate_horizon_seconds:
                return True
        return False

    def _normalize_word(self, text: str) -> str:
        return " ".join(match.group(0).casefold() for match in _WORD_RE.finditer(text or ""))
