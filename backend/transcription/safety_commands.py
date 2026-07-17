from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re


_NON_WORD = re.compile(r"[^\w]+", flags=re.UNICODE)


@dataclass(frozen=True)
class SafetyCommand:
    command_id: str
    text: str


@dataclass(frozen=True)
class SafetyMatch:
    command: SafetyCommand | None
    best_candidate: SafetyCommand
    score: float
    margin: float
    rejection_reason: str | None = None


@dataclass(frozen=True)
class SafetyCommandCatalog:
    catalog_id: str
    language: str
    commands: tuple[SafetyCommand, ...]
    path: str
    sha256: str

    @classmethod
    def load(cls, path: str | Path) -> "SafetyCommandCatalog":
        catalog_path = Path(path).expanduser().resolve()
        raw = catalog_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("Safety command catalog schema_version must be 1")
        catalog_id = str(payload.get("catalog_id") or "").strip()
        language = str(payload.get("language") or "").strip()
        if not catalog_id or not language:
            raise ValueError("Safety command catalog requires catalog_id and language")
        commands = []
        seen_texts: set[str] = set()
        for item in payload.get("commands") or []:
            command_id = str(item.get("command_id") or item.get("id") or "").strip()
            phrases = item.get("allowed_phrases")
            if phrases is None:
                phrases = [item.get("text")]
            if not command_id or not isinstance(phrases, list) or not phrases:
                raise ValueError(
                    "Every safety command requires a non-empty command_id and allowed_phrases"
                )
            for phrase in phrases:
                text = str(phrase or "").strip()
                normalized = normalize_command(text)
                if not normalized:
                    raise ValueError("Safety command phrases must not be empty")
                if normalized in seen_texts:
                    raise ValueError("Normalized safety command phrases must be unique")
                seen_texts.add(normalized)
                commands.append(SafetyCommand(command_id=command_id, text=text))
        if not commands:
            raise ValueError("Safety command catalog must contain commands")
        return cls(
            catalog_id=catalog_id,
            language=language,
            commands=tuple(commands),
            path=str(catalog_path),
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    def prompt(self, base_prompt: str) -> str:
        phrases = " ".join(f"{command.text.rstrip('.!?')}." for command in self.commands)
        suffix = f" Zulässige kurze Sicherheitskommandos, wortgetreu: {phrases}"
        return f"{base_prompt.strip()}{suffix}".strip()

    def match(self, text: str, *, min_score: float, min_margin: float) -> SafetyMatch:
        normalized = normalize_command(text)
        scored = sorted(
            (
                (command_similarity(normalized, normalize_command(command.text)), command)
                for command in self.commands
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best_command = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score
        conflict = command_conflict_reason(
            normalized,
            best_command.command_id,
            canonical_text=normalize_command(best_command.text),
        )
        if conflict:
            return SafetyMatch(
                command=None,
                best_candidate=best_command,
                score=best_score,
                margin=margin,
                rejection_reason=conflict,
            )
        if normalized != normalize_command(best_command.text):
            return SafetyMatch(
                command=None,
                best_candidate=best_command,
                score=best_score,
                margin=margin,
                rejection_reason="not-allowlisted-exact",
            )
        if best_score < min_score:
            return SafetyMatch(
                command=None,
                best_candidate=best_command,
                score=best_score,
                margin=margin,
                rejection_reason="below-min-score",
            )
        if margin < min_margin:
            return SafetyMatch(
                command=None,
                best_candidate=best_command,
                score=best_score,
                margin=margin,
                rejection_reason="ambiguous-margin",
            )
        return SafetyMatch(
            command=best_command,
            best_candidate=best_command,
            score=best_score,
            margin=margin,
        )


def normalize_command(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.casefold()).split())


def command_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    compact_left = left.replace(" ", "")
    compact_right = right.replace(" ", "")
    character_score = SequenceMatcher(None, compact_left, compact_right).ratio()
    left_words = left.split()
    right_words = right.split()
    word_score = SequenceMatcher(None, left_words, right_words).ratio()
    # Character similarity tolerates compound splitting; word similarity
    # prevents an unrelated sentence with a shared suffix from winning.
    return 0.75 * character_score + 0.25 * word_score


_NEGATION_WORDS = {
    "nicht", "nich", "net", "ned", "kein", "keine", "keinen", "keinem", "keiner",
    "keines", "keinesfalls", "keineswegs", "nie", "niemals"
}
_GLOBAL_CONFLICT_STEMS = ("verhinder", "unterlass", "vermeid", "verbiet", "verbot", "untersag")
_CONFLICT_STEMS = {
    "safety_motion_stop": ("start", "fortsetz", "weiterfahr", "anlauf"),
    "safety_emergency_stop": ("zurücksetz", "ruecksetz", "entriegel"),
    "safety_area_evacuate": ("betret", "bleib", "zurückkehr", "rueckkehr"),
    "safety_energy_isolate": ("verbind", "einschalt", "zuschalt"),
    "safety_brake_lock": ("lös", "loes", "entriegel", "öffn", "oeffn"),
    "safety_access_secure": ("öffn", "oeffn", "entsperr", "entriegel"),
    "safety_load_hold": ("absenk", "loslass", "weiterfahr"),
    "safety_stage_lock": ("entsperr", "freigeb", "öffn", "oeffn"),
}


def command_conflict_reason(
    normalized_text: str,
    command_id: str,
    *,
    canonical_text: str = "",
) -> str | None:
    """Reject explicit negations and known opposite actions before canonicalization."""
    words = normalized_text.split()
    negation = next((word for word in words if word in _NEGATION_WORDS), None)
    if negation:
        return f"negation:{negation}"
    canonical_words = canonical_text.split()
    if canonical_words and len(words) != len(canonical_words):
        return "token-count-mismatch"
    for observed, canonical in zip(words, canonical_words):
        if SequenceMatcher(None, observed, canonical).ratio() < 0.62:
            return f"token-mismatch:{observed}"
    for stem in _GLOBAL_CONFLICT_STEMS:
        if any(word.startswith(stem) for word in words):
            return f"prohibition:{stem}"
    for stem in _CONFLICT_STEMS.get(command_id, ()):
        if any(word.startswith(stem) for word in words):
            return f"opposite-action:{stem}"
    return None
