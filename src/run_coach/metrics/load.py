"""Load and distribution: weekly running volume, and time-in-zone share
where Garmin provided per-activity heart-rate zone minutes.
"""

from __future__ import annotations

import sqlite3

from run_coach.metrics.common import is_running, iso_week_key, local_date_of
from run_coach.storage.db import activity_hr_zones


def weekly_volume(activities: list) -> list[dict]:
    runs = [a for a in activities if is_running(a["activity_type"])]
    weeks: dict[str, dict] = {}
    for row in runs:
        key = iso_week_key(local_date_of(row))
        bucket = weeks.setdefault(key, {"distance_m": 0.0, "runs": 0})
        bucket["distance_m"] += row["distance_m"] or 0.0
        bucket["runs"] += 1
    return [
        {"week": key, "distance_km": round(weeks[key]["distance_m"] / 1000.0, 1), "runs": weeks[key]["runs"]}
        for key in sorted(weeks)
    ]


def hr_zone_distribution(conn: sqlite3.Connection, activities: list) -> dict:
    runs = [a for a in activities if is_running(a["activity_type"])]
    totals: dict[int, float] = {}
    activities_with_zones = 0
    for row in runs:
        zones = activity_hr_zones(conn, row["id"])
        if not zones:
            continue
        activities_with_zones += 1
        for zone, minutes in zones.items():
            totals[zone] = totals.get(zone, 0.0) + minutes

    if activities_with_zones == 0:
        return {"available": False, "n_activities": 0, "zones": {}}

    total_minutes = sum(totals.values())
    shares = {
        str(zone): round(minutes / total_minutes * 100, 1) if total_minutes else 0.0
        for zone, minutes in sorted(totals.items())
    }
    return {"available": True, "n_activities": activities_with_zones, "zones": shares}
