"""Builds the single aggregated stats dict shared by the dashboard API and
the recommendations prompt. Claude only ever sees this dict, never raw
activity rows -- see recommendations/claude_client.py.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from run_coach.metrics.efficiency import DEFAULT_REFERENCE_HR, hr_coverage, monthly_pace_at_hr
from run_coach.metrics.load import hr_zone_distribution, weekly_volume
from run_coach.metrics.patterns import cycle_phase_patterns
from run_coach.metrics.progress import (
    monthly_progress,
    personal_bests,
    race_time_predictions,
)
from run_coach.metrics.recovery import recovery_summary
from run_coach.metrics.standing import training_standing
from run_coach.storage.db import (
    all_activities,
    all_cycle_entries,
    all_daily_metrics,
    all_settings,
    latest_data_gaps,
)

RECOVERY_METRIC_LABELS = {
    "hrv_ms": "HRV",
    "resting_hr": "resting heart rate",
    "sleep_duration_s": "sleep duration",
    "sleep_score": "sleep score",
}


def _garmin_history_note(activities: list) -> str:
    """Always states the covered span (or its absence) rather than only
    flagging it when "too short" -- a short history is itself useful to
    know, not just a threshold to cross."""
    garmin_dates = sorted(a["local_date"] for a in activities if a["source"] == "garmin")
    if not garmin_dates:
        return "no Garmin activities synced yet"
    start, end = garmin_dates[0], garmin_dates[-1]
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return f"Garmin activity history covers {start} to {end} ({days} day{'s' if days != 1 else ''})"


def _hr_coverage_note(coverage: dict) -> str | None:
    if coverage["total_runs"] == 0:
        return None
    strava_part = (
        f" ({coverage['strava_with_hr']} of {coverage['strava_total']} from Strava)"
        if coverage["strava_total"]
        else ""
    )
    return (
        f"{coverage['runs_with_hr']} of {coverage['total_runs']} runs have heart-rate data{strava_part} "
        "-- aerobic efficiency and HR-zone charts need more runs with it"
    )


def _recovery_gap_notes(recovery: dict) -> list[str]:
    return [
        f"no {RECOVERY_METRIC_LABELS[metric]} readings from Garmin in the last 7 days"
        for metric, info in recovery.items()
        if info.get("n_recent", 0) == 0 and metric in RECOVERY_METRIC_LABELS
    ]


def compute_data_gaps(
    conn: sqlite3.Connection, activities: list, recovery: dict, coverage: dict, hr_zone_dist: dict
) -> list[str]:
    """Every sync-time gap already logged, plus gaps that are true right
    now regardless of whether a sync ever reported them -- so this section
    never has to fall back to "none recorded" when there is, in fact,
    something worth flagging."""
    gaps = list(latest_data_gaps(conn))
    gaps.append(_garmin_history_note(activities))
    hr_note = _hr_coverage_note(coverage)
    if hr_note:
        gaps.append(hr_note)
    if not hr_zone_dist["available"]:
        gaps.append("no per-zone heart-rate minutes from Garmin for any running activity yet")
    gaps.extend(_recovery_gap_notes(recovery))
    return gaps


def build_stats(conn: sqlite3.Connection) -> dict:
    activities = all_activities(conn)
    daily_metrics = all_daily_metrics(conn)
    cycle_entries = all_cycle_entries(conn)
    settings = all_settings(conn)

    recovery = recovery_summary(daily_metrics)
    coverage = hr_coverage(activities)
    hr_zone_dist = hr_zone_distribution(conn, activities)

    pbs = personal_bests(activities)
    pbs_json = {
        label: (
            {
                "moving_time_s": pb.moving_time_s,
                "distance_m": pb.distance_m,
                "pace_s_per_km": pb.pace_s_per_km,
                "date": pb.date,
            }
            if pb
            else None
        )
        for label, pb in pbs.items()
    }
    predictions = race_time_predictions(pbs)

    return {
        "n_activities_total": len(activities),
        "n_running_activities": sum(1 for a in activities if "run" in (a["activity_type"] or "").lower()),
        "progress": {
            "monthly": monthly_progress(activities),
            "personal_bests": pbs_json,
            "race_predictions": predictions,
        },
        "aerobic_efficiency": {
            "monthly_pace_at_reference_hr": monthly_pace_at_hr(
                activities, settings.get("reference_hr", DEFAULT_REFERENCE_HR)
            ),
        },
        "load": {
            "weekly_volume": weekly_volume(activities),
            "hr_zone_distribution": hr_zone_dist,
        },
        "recovery": recovery,
        "patterns": {
            "cycle_phase": cycle_phase_patterns(activities, cycle_entries),
            "special_conditions": settings.get("special_conditions_text"),
        },
        "standing": training_standing(activities, daily_metrics, settings),
        "goals": {
            "target_pace_s_per_km": settings.get("target_pace_s_per_km"),
            "race_distance_m": settings.get("race_distance_m"),
            "race_date": settings.get("race_date"),
            "runs_per_week": settings.get("runs_per_week"),
            "follows_watch_plan": settings.get("follows_watch_plan", False),
        },
        "hr_coverage": coverage,
        "data_gaps": compute_data_gaps(conn, activities, recovery, coverage, hr_zone_dist),
    }
