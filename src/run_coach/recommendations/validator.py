"""Checks that every number Claude wrote actually appears in the stats JSON
it was given. A sentence with a number that doesn't check out is dropped;
if nothing is left of a recommendation, the whole recommendation is dropped.

This is deliberately literal rather than semantic: it flattens the stats
JSON to text and extracts every numeric token from it (including the
pieces of pre-formatted strings like "5:27/km" or "20.1%"), then requires
every numeric token in each sentence to appear in that same set. It won't
catch a number that's technically present but used to mean something else
-- it only guards against Claude inventing or miscalculating a number.
"""

from __future__ import annotations

import json
import re

NUMBER_RE = re.compile(r"-?\d+\.?\d*")


def _extract_numbers(text: str) -> set[str]:
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


def _normalize(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def allowed_numbers_from_stats(stats: dict) -> set[str]:
    serialized = json.dumps(stats, default=str)
    return _extract_numbers(serialized)


def filter_text_against_numbers(text: str, allowed: set[str]) -> str | None:
    """Drop any sentence in `text` whose numbers aren't all in `allowed`.
    Returns None if nothing survives.
    """
    kept = [s for s in _split_sentences(text) if _extract_numbers(s).issubset(allowed)]
    return " ".join(kept) if kept else None


def validate_recommendations(recommendations: list[dict], stats: dict) -> list[dict]:
    allowed = allowed_numbers_from_stats(stats)
    cleaned: list[dict] = []

    for rec in recommendations:
        filtered_text = filter_text_against_numbers(rec.get("text", ""), allowed)
        if filtered_text is None:
            continue
        cleaned.append({**rec, "text": filtered_text})

    return cleaned
