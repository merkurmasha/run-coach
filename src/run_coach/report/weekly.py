"""Weekly report: last complete week vs. the average of the previous three,
written up by Claude from a small aggregated JSON (never raw activities),
with every number it writes checked against that same JSON.
"""

from __future__ import annotations

import json
import sqlite3

import anthropic

from run_coach.config import Secrets
from run_coach.metrics.common import is_running, iso_week_key, local_date_of
from run_coach.metrics.recovery import recovery_summary
from run_coach.recommendations.validator import allowed_numbers_from_stats, filter_text_against_numbers
from run_coach.storage.db import all_activities, all_daily_metrics, all_settings

SYSTEM_PROMPT = """You write a short weekly running report for one runner, from the \
small JSON you're given. Never invent or compute a number -- every number you write \
must appear in the JSON. Never give medical advice or diagnose anything mentioned in \
special_conditions; if it sounds like pain or injury, the watch_out or a key result \
should suggest checking with a professional rather than pushing through it. If \
follows_watch_plan is true, next_week.objective and key_results must read as \
adjustments to the user's existing plan, not a replacement for it. Keep it concise: \
highlight and watch_out are one sentence each; key_results are short, each pairing a \
target with one fallback_session. Call submit_report exactly once."""

TOOL_SCHEMA = {
    "name": "submit_report",
    "description": "Submit the finished weekly report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "highlight": {"type": "string"},
            "watch_out": {"type": "string"},
            "next_week": {
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "key_results": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                    "fallback_sessions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                },
                "required": ["objective", "key_results", "fallback_sessions"],
            },
        },
        "required": ["highlight", "watch_out", "next_week"],
    },
}


def _weekly_buckets(activities: list, n_weeks: int) -> list[dict]:
    runs = [a for a in activities if is_running(a["activity_type"])]
    weeks: dict[str, dict] = {}
    for row in runs:
        key = iso_week_key(local_date_of(row))
        bucket = weeks.setdefault(key, {"distance_m": 0.0, "moving_time_s": 0.0, "runs": 0})
        bucket["distance_m"] += row["distance_m"] or 0.0
        bucket["moving_time_s"] += row["moving_time_s"] or 0.0
        bucket["runs"] += 1

    ordered = sorted(weeks)[-n_weeks:]
    out = []
    for key in ordered:
        b = weeks[key]
        avg_pace = b["moving_time_s"] / (b["distance_m"] / 1000.0) if b["distance_m"] else None
        out.append({"week": key, "distance_km": round(b["distance_m"] / 1000.0, 1), "runs": b["runs"], "avg_pace_s_per_km": avg_pace})
    return out


def build_report_context(conn: sqlite3.Connection, weeks: int = 8) -> dict:
    activities = all_activities(conn)
    settings = all_settings(conn)
    buckets = _weekly_buckets(activities, weeks)

    if len(buckets) < 2:
        last_week = buckets[-1] if buckets else None
        previous_avg = None
    else:
        last_week = buckets[-1]
        previous = buckets[max(0, len(buckets) - 4) : len(buckets) - 1]
        if previous:
            previous_avg = {
                "distance_km": round(sum(b["distance_km"] for b in previous) / len(previous), 1),
                "runs": round(sum(b["runs"] for b in previous) / len(previous), 1),
                "n_weeks": len(previous),
            }
        else:
            previous_avg = None

    recovery = recovery_summary(all_daily_metrics(conn))

    return {
        "weekly_history": buckets,
        "last_week": last_week,
        "average_of_previous_weeks": previous_avg,
        "recovery": recovery,
        "goals": {
            "runs_per_week": settings.get("runs_per_week"),
            "follows_watch_plan": settings.get("follows_watch_plan", False),
            "target_pace_s_per_km": settings.get("target_pace_s_per_km"),
            "race_distance_m": settings.get("race_distance_m"),
            "race_date": settings.get("race_date"),
        },
        "special_conditions": settings.get("special_conditions_text"),
    }


def generate_weekly_report(conn: sqlite3.Connection, secrets: Secrets, weeks: int = 8) -> dict:
    if not secrets.has_claude():
        raise RuntimeError("The weekly report needs ANTHROPIC_API_KEY configured -- it writes the prose from your stats.")

    context = build_report_context(conn, weeks=weeks)
    if context["last_week"] is None:
        raise RuntimeError("Not enough weekly running data yet to build a report.")

    client = anthropic.Anthropic(api_key=secrets.anthropic_api_key)
    response = client.messages.create(
        model=secrets.claude_model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_report"},
        messages=[{"role": "user", "content": f"Here is this week's context JSON:\n\n{json.dumps(context, default=str)}"}],
    )

    report = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_report":
            report = block.input
            break
    if report is None:
        raise RuntimeError("Claude did not return a report.")

    allowed = allowed_numbers_from_stats(context)
    report["highlight"] = filter_text_against_numbers(report.get("highlight", ""), allowed) or "(dropped: unverifiable numbers)"
    report["watch_out"] = filter_text_against_numbers(report.get("watch_out", ""), allowed) or "(dropped: unverifiable numbers)"
    next_week = report.get("next_week", {})
    next_week["objective"] = filter_text_against_numbers(next_week.get("objective", ""), allowed) or "(dropped: unverifiable numbers)"
    next_week["key_results"] = [
        filter_text_against_numbers(kr, allowed) or "(dropped: unverifiable numbers)" for kr in next_week.get("key_results", [])
    ]
    report["next_week"] = next_week
    report["context"] = context
    return report
