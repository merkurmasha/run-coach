"""Builds the single aggregated stats dict shared by the dashboard API and
the recommendations prompt. Claude only ever sees this dict, never raw
activity rows -- see recommendations/claude_client.py.
"""

from __future__ import annotations

import sqlite3

from run_coach.metrics.efficiency import monthly_pace_at_hr
from run_coach.metrics.load import hr_zone_distribution, weekly_volume
from run_coach.metrics.patterns import cycle_phase_patterns
from run_coach.metrics.progress import monthly_progress, personal_bests, race_time_predictions
from run_coach.metrics.recovery import recovery_summary
from run_coach.storage.db import all_activities, all_cycle_entries, all_daily_metrics, all_settings, latest_data_gaps


def build_stats(conn: sqlite3.Connection) -> dict:
    activities = all_activities(conn)
    daily_metrics = all_daily_metrics(conn)
    cycle_entries = all_cycle_entries(conn)
    settings = all_settings(conn)

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
            "monthly_pace_at_reference_hr": monthly_pace_at_hr(activities),
        },
        "load": {
            "weekly_volume": weekly_volume(activities),
            "hr_zone_distribution": hr_zone_distribution(conn, activities),
        },
        "recovery": recovery_summary(daily_metrics),
        "patterns": {
            "cycle_phase": cycle_phase_patterns(activities, cycle_entries),
            "special_conditions": settings.get("special_conditions_text"),
        },
        "goals": {
            "target_pace_s_per_km": settings.get("target_pace_s_per_km"),
            "race_distance_m": settings.get("race_distance_m"),
            "race_date": settings.get("race_date"),
            "runs_per_week": settings.get("runs_per_week"),
            "follows_watch_plan": settings.get("follows_watch_plan", False),
        },
        "data_gaps": latest_data_gaps(conn),
    }
