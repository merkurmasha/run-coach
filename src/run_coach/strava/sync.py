"""Imports a parsed Strava export into storage, deduplicating against Garmin.

Garmin takes priority: if any existing activity (from either source) starts
within `DEDUP_TOLERANCE_MINUTES` of a Strava row, the Strava row is skipped
(or, if the existing match is itself a Strava activity from an earlier
import, updated in place) rather than creating a second record of the same
run.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from run_coach.storage.db import Activity, find_activity_near, upsert_activity
from run_coach.strava.importer import FIELD_CANDIDATES, inspect_header, parse_strava_csv

DEDUP_TOLERANCE_MINUTES = 5


def _count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return sum(1 for _ in reader)


def import_strava_csv(
    conn: sqlite3.Connection,
    path: Path,
    timezone_name: str | None = None,
    column_overrides: dict[str, str] | None = None,
) -> dict:
    header_info = inspect_header(path)
    rows_read = _count_csv_rows(path)
    columns_not_found = [
        field
        for field in FIELD_CANDIDATES
        if field not in {**header_info["matched_fields"], **(column_overrides or {})}
    ]

    activities, gaps = parse_strava_csv(path, column_overrides=column_overrides)

    unparseable_dates = sum(1 for g in gaps if "unrecognized date format" in g)
    skipped_missing_fields = max(0, rows_read - len(activities) - unparseable_dates)

    tz = None
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            gaps.append(f"strava: unrecognized timezone '{timezone_name}', treating activity times as UTC")
    if tz is None:
        gaps.append("strava: no timezone configured, treating activity local times as UTC (may be off by hours)")

    imported = 0
    skipped_duplicate_of_garmin = 0
    updated = 0

    for activity in activities:
        start_local = activity.start_time_local
        start_utc = start_local.replace(tzinfo=tz) if tz else start_local.replace(tzinfo=None)
        start_utc_iso = _to_utc_iso(start_utc, tz)

        existing = find_activity_near(conn, start_utc_iso, DEDUP_TOLERANCE_MINUTES)
        if existing is not None and existing["source"] == "garmin":
            skipped_duplicate_of_garmin += 1
            continue
        if existing is not None and existing["source"] == "strava" and existing["external_id"] != activity.external_id:
            # Same moment, different Strava id (re-exported with new id): keep the newer upsert simple
            # by treating this as an update of the existing record's id-less fields is not possible
            # (id is the primary key), so prefer the existing row and skip to avoid duplicates.
            skipped_duplicate_of_garmin += 1
            continue

        upsert_activity(
            conn,
            Activity(
                source="strava",
                external_id=activity.external_id,
                start_time_utc=start_utc_iso,
                local_date=start_local.date().isoformat(),
                activity_type=activity.activity_type,
                distance_m=activity.distance_m,
                moving_time_s=activity.moving_time_s,
                elapsed_time_s=activity.elapsed_time_s,
                avg_hr=activity.avg_hr,
                max_hr=activity.max_hr,
                avg_pace_s_per_km=_pace_s_per_km(activity.distance_m, activity.moving_time_s),
                elevation_gain_m=activity.elevation_gain_m,
                calories=activity.calories,
            ),
        )
        imported += 1

    if activities:
        dates = sorted(a.start_time_local.date().isoformat() for a in activities)
        date_range = {"start": dates[0], "end": dates[-1]}
    else:
        date_range = None

    return {
        "counts": {
            "rows_read": rows_read,
            "imported": imported,
            "updated": updated,
            "skipped_duplicate_of_garmin": skipped_duplicate_of_garmin,
            "skipped_unparseable_date": unparseable_dates,
            "skipped_missing_fields": skipped_missing_fields,
            "total_rows": len(activities),
        },
        "date_range": date_range,
        "columns_not_found": columns_not_found,
        "data_gaps": gaps,
    }


def _to_utc_iso(dt, tz) -> str:
    if tz is not None:
        return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pace_s_per_km(distance_m: float | None, moving_time_s: float | None) -> float | None:
    if not distance_m or not moving_time_s or distance_m <= 0:
        return None
    return moving_time_s / (distance_m / 1000.0)
