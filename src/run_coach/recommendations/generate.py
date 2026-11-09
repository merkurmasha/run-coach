"""Orchestrates one recommendations run: aggregate stats -> ask Claude ->
validate numbers -> cache. Called on demand (button click), never on a
schedule, per the project's "cache and regenerate on click" design.
"""

from __future__ import annotations

import sqlite3

from run_coach.config import Secrets
from run_coach.metrics.aggregate import build_stats
from run_coach.recommendations.claude_client import generate_recommendations
from run_coach.recommendations.validator import validate_recommendations
from run_coach.storage.db import get_cached_recommendations, set_cached_recommendations


def generate_and_cache(conn: sqlite3.Connection, secrets: Secrets) -> dict:
    stats = build_stats(conn)
    raw = generate_recommendations(stats, secrets.anthropic_api_key, secrets.claude_model)
    validated = validate_recommendations(raw, stats)
    set_cached_recommendations(conn, stats, validated)
    return get_cached_recommendations(conn)
