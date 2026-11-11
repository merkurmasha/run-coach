"""Checks that every number Claude wrote actually appears in the stats JSON
it was given. A sentence with a number that doesn't check out is dropped;
if nothing is left of a recommendation, the whole recommendation is dropped.

This is deliberately literal rather than semantic: it flattens the stats
JSON to text and extracts every numeric token from it (including the
pieces of pre-formatted strings like "5:27/km" or "20.1%"), then requires
every numeric token in each sentence to appear in that same set. It won't
catch a number that's technically present but used to mean something else
-- it only guards against Claude inventing or miscalculating a number.

The plain-voice rewrite (see claude_client.SYSTEM_PROMPT) asks Claude to
convert raw stats into everyday phrasing -- "6:30/km" instead of "390",
"about three quarters" instead of "74.6%", "last week" instead of a
"2026-W42" key. A literal digit-for-digit check would reject every one of
those conversions, so this module resolves them back to the number they
represent before checking: a min:sec pace becomes its total seconds, a
"3 in 4" or "3 out of 4" becomes the percentage it stands for, and a
rounded number is allowed to round to a nearby stat rather than match it
exactly. Word fractions ("about half", "roughly a third") aren't literal
numbers at all, so they're checked with a wider tolerance against any
percentage-shaped stat, rather than against the exact `allowed` set.
"""

from __future__ import annotations

import json
import math
import re

NUMBER_RE = re.compile(r"-?\d+\.?\d*")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
FRACTION_OF_RE = re.compile(r"\b(\d+)\s+(?:in|out of|of every)\s+(\d+)\b", re.IGNORECASE)

# Deliberately approximate phrasings -- checked against any percentage-shaped
# stat within FRACTION_TOLERANCE points, not against an exact number.
WORD_FRACTION_PERCENTAGES = {
    re.compile(r"\bhalf\b", re.IGNORECASE): 50.0,
    re.compile(r"\b(?:a|one)\s+third\b", re.IGNORECASE): 100.0 / 3,
    re.compile(r"\btwo\s+thirds\b", re.IGNORECASE): 200.0 / 3,
    re.compile(r"\b(?:a|one)\s+quarter\b", re.IGNORECASE): 25.0,
    re.compile(r"\bthree\s+quarters\b", re.IGNORECASE): 75.0,
}
FRACTION_TOLERANCE = 12.0  # percentage points

# What the plain-voice rewrite must never leak into user-facing text: a
# snake_case internal field/variable name, a dotted attribute path, an ISO
# week code, or a raw "s/km" unit.
FIELD_NAME_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
DOTTED_PATH_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\b")
WEEK_CODE_RE = re.compile(r"\bW\d{1,2}\b")
S_PER_KM_RE = re.compile(r"\bs/km\b", re.IGNORECASE)
JARGON_PATTERNS = (FIELD_NAME_RE, DOTTED_PATH_RE, WEEK_CODE_RE, S_PER_KM_RE)


def _normalize(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _extract_plain_numbers(text: str) -> set[str]:
    numbers = set()
    for match in NUMBER_RE.findall(text):
        normalized = match.rstrip(".")
        if normalized in ("", "-"):
            continue
        try:
            value = float(normalized)
        except ValueError:
            continue
        numbers.add(_normalize(value))
    return numbers


def _strip_times(text: str) -> tuple[str, set[str]]:
    """Replaces every "M:SS" / "H:MM:SS" span with a blank (so its digits
    aren't independently checked as plain numbers) and returns the total
    seconds each one represents.
    """
    derived: set[str] = set()

    def repl(match: re.Match) -> str:
        parts = [int(g) for g in match.groups() if g is not None]
        total = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
        derived.add(_normalize(float(total)))
        return " "

    return TIME_RE.sub(repl, text), derived


def _strip_fraction_of(text: str) -> tuple[str, set[str]]:
    """Replaces "3 in 4" / "3 out of 4" with a blank and returns the
    percentage it represents.
    """
    derived: set[str] = set()

    def repl(match: re.Match) -> str:
        num, denom = int(match.group(1)), int(match.group(2))
        if denom:
            derived.add(_normalize(100.0 * num / denom))
        return " "

    return FRACTION_OF_RE.sub(repl, text), derived


def _word_fraction_percentages(text: str) -> list[float]:
    return [pct for pattern, pct in WORD_FRACTION_PERCENTAGES.items() if pattern.search(text)]


def _percentages_in(allowed: set[str]) -> list[float]:
    out = []
    for token in allowed:
        try:
            value = float(token)
        except ValueError:
            continue
        if 0.0 <= value <= 100.0:
            out.append(value)
    return out


def _extract_numbers(text: str) -> set[str]:
    stripped, time_numbers = _strip_times(text)
    stripped, fraction_numbers = _strip_fraction_of(stripped)
    return _extract_plain_numbers(stripped) | time_numbers | fraction_numbers


def _expand_with_rounded(numbers: set[str]) -> set[str]:
    """A plain-voice rewrite rounds for readability ("21 km" for 21.0975,
    "about 5:10/km" for 309.6s) -- so a number in the text only has to
    round to a stat, not match its exact decimal.
    """
    expanded = set(numbers)
    for token in numbers:
        try:
            value = float(token)
        except ValueError:
            continue
        for candidate in (round(value), math.floor(value), math.ceil(value), round(value, 1)):
            expanded.add(_normalize(float(candidate)))
    return expanded


def allowed_numbers_from_stats(stats: dict) -> set[str]:
    serialized = json.dumps(stats, default=str)
    return _expand_with_rounded(_extract_plain_numbers(serialized))


def contains_jargon(text: str) -> bool:
    """True if `text` leaks an internal field/variable name, an ISO week
    code ("W42"), or a raw "s/km" unit -- the kind of thing the plain-voice
    rewrite should have converted into words a non-technical runner reads.
    Not applied to "rationale", which is deliberately technical.
    """
    return any(pattern.search(text) for pattern in JARGON_PATTERNS)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def filter_text_against_numbers(text: str, allowed: set[str], *, check_jargon: bool = False) -> str | None:
    """Drop any sentence in `text` whose numbers -- after resolving
    converted forms like min:sec paces and "3 in 4" back to the value they
    stand for -- aren't all in `allowed`, or (when check_jargon is set, for
    the plain user-facing fields) that leaks jargon. Returns None if
    nothing survives.
    """
    kept = []
    for sentence in _split_sentences(text):
        if check_jargon and contains_jargon(sentence):
            continue
        if not _extract_numbers(sentence).issubset(allowed):
            continue
        word_fractions = _word_fraction_percentages(sentence)
        if word_fractions:
            stat_percentages = _percentages_in(allowed)
            if not any(abs(wp - sp) <= FRACTION_TOLERANCE for wp in word_fractions for sp in stat_percentages):
                continue
        kept.append(sentence)
    return " ".join(kept) if kept else None


def validate_recommendations(recommendations: list[dict], stats: dict) -> list[dict]:
    allowed = allowed_numbers_from_stats(stats)
    cleaned: list[dict] = []

    for rec in recommendations:
        text = filter_text_against_numbers(rec.get("text", ""), allowed, check_jargon=True)
        if text is None:
            continue
        why_it_matters = filter_text_against_numbers(rec.get("why_it_matters", ""), allowed, check_jargon=True) or ""
        rationale = filter_text_against_numbers(rec.get("rationale", ""), allowed, check_jargon=False) or ""
        cleaned.append({**rec, "text": text, "why_it_matters": why_it_matters, "rationale": rationale})

    return cleaned
