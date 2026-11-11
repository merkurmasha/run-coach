"""Orchestrates one recommendations run: aggregate stats -> ask Claude ->
validate numbers -> cache. Called on demand (button click), never on a
schedule, per the project's "cache and regenerate on click" design.

If Claude is unavailable (no key, or the API call fails) this falls back
to rule_based.py's code-computed recommendations instead of leaving the
section empty -- see rule_based.py's module docstring.
"""

from __future__ import annotations

import sqlite3

from run_coach.config import Secrets
from run_coach.metrics.aggregate import build_stats
from run_coach.recommendations.claude_client import generate_recommendations
from run_coach.recommendations.rule_based import generate_rule_based_recommendations
from run_coach.recommendations.validator import validate_recommendations
from run_coach.storage.db import get_cached_recommendations, set_cached_recommendations


def generate_and_cache(conn: sqlite3.Connection, secrets: Secrets) -> dict:
    stats = build_stats(conn)

    recs: list[dict] = []
    if secrets.has_claude():
        try:
            raw = generate_recommendations(stats, secrets.anthropic_api_key, secrets.claude_model)
            recs = validate_recommendations(raw, stats)
        except Exception:  # defensive: any Claude failure falls back to rule-based, never raises here
            recs = []

    if not recs:
        recs = generate_rule_based_recommendations(stats)

    set_cached_recommendations(conn, stats, recs)
    return get_cached_recommendations(conn)
