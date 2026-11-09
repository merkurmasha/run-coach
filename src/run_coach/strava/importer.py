"""Strava bulk-export activities.csv parser.

We never call the Strava API (per the project's design: this is a one-time,
user-initiated upload of the user's own export, not a live integration).
Strava's exact CSV header set has shifted over the years and is translated
to the account's display language, and some exports carry duplicate header
names across activity types. Rather than assume one fixed header row, we
match each logical field against several candidate header spellings and
skip (recording a gap) when nothing matches — never guess a value.

Columns we intentionally never read: any header containing "description" or
"note" (case-insensitive) — that's "Activity Description" and "Private
Note" in English exports, which the project must never store.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EXCLUDED_HEADER_SUBSTRINGS = ("description", "note")

FIELD_CANDIDATES = {
    "id": ["Activity ID"],
    "date": ["Activity Date"],
    "type": ["Activity Type"],
    "distance": ["Distance"],
    "moving_time": ["Moving Time"],
    "elapsed_time": ["Elapsed Time"],
    "avg_hr": ["Average Heart Rate"],
    "max_hr": ["Max Heart Rate"],
    "elevation_gain": ["Elevation Gain"],
    "calories": ["Calories"],
}

# Strava's CSV export has used a few date formats over the years.
DATE_FORMATS = [
    "%b %d, %Y, %I:%M:%S %p",  # "Dec 23, 2023, 7:15:32 AM"
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]

RUN_TYPES = {"run", "trail run", "virtual run"}


@dataclass
class ParsedStravaActivity:
    external_id: str
    start_time_local: datetime
    activity_type: str
    distance_m: float | None
    moving_time_s: float | None
    elapsed_time_s: float | None
    avg_hr: float | None
    max_hr: float | None
    elevation_gain_m: float | None
    calories: float | None


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Map our logical field names to the actual header text present."""
    normalized = {name.strip().lower(): name for name in fieldnames}
    column_map: dict[str, str] = {}
    for field, candidates in FIELD_CANDIDATES.items():
        for candidate in candidates:
            key = candidate.strip().lower()
            if key in normalized:
                column_map[field] = normalized[key]
                break
    return column_map


def _safe_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_strava_csv(path: Path) -> tuple[list[ParsedStravaActivity], list[str]]:
    gaps: list[str] = []
    activities: list[ParsedStravaActivity] = []

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            gaps.append("strava: activities.csv has no header row, nothing imported")
            return [], gaps

        excluded = [
            name
            for name in reader.fieldnames
            if any(substr in name.lower() for substr in EXCLUDED_HEADER_SUBSTRINGS)
        ]
        if excluded:
            gaps.append(f"strava: ignored description/note columns: {', '.join(excluded)}")

        column_map = _build_column_map(reader.fieldnames)
        required_missing = [f for f in ("id", "date", "type") if f not in column_map]
        if required_missing:
            gaps.append(
                f"strava: could not find columns for {required_missing} in activities.csv header; "
                "nothing imported (Strava may have renamed or translated the header row)"
            )
            return [], gaps

        for row in reader:
            external_id = row.get(column_map["id"], "").strip()
            raw_date = row.get(column_map["date"], "")
            activity_type = row.get(column_map["type"], "").strip()
            if not external_id or not raw_date:
                continue
            start = _parse_date(raw_date)
            if start is None:
                gaps.append(f"strava activity {external_id}: unrecognized date format '{raw_date}', skipped")
                continue

            distance_m = _safe_float(row.get(column_map.get("distance", ""), None))
            moving_time_s = _safe_float(row.get(column_map.get("moving_time", ""), None))
            elapsed_time_s = _safe_float(row.get(column_map.get("elapsed_time", ""), None))

            if (
                activity_type.lower() in RUN_TYPES
                and distance_m
                and moving_time_s
                and not _plausible_running_pace(distance_m, moving_time_s)
            ):
                gaps.append(
                    f"strava activity {external_id}: distance/time combination gives an implausible "
                    "running pace; the Distance column's unit may not be meters as assumed"
                )

            activities.append(
                ParsedStravaActivity(
                    external_id=external_id,
                    start_time_local=start,
                    activity_type=activity_type,
                    distance_m=distance_m,
                    moving_time_s=moving_time_s,
                    elapsed_time_s=elapsed_time_s,
                    avg_hr=_safe_float(row.get(column_map.get("avg_hr", ""), None)),
                    max_hr=_safe_float(row.get(column_map.get("max_hr", ""), None)),
                    elevation_gain_m=_safe_float(row.get(column_map.get("elevation_gain", ""), None)),
                    calories=_safe_float(row.get(column_map.get("calories", ""), None)),
                )
            )

    return activities, gaps


def _plausible_running_pace(distance_m: float, moving_time_s: float, lo: float = 90, hi: float = 1200) -> bool:
    """Sanity range for pace in seconds/km, assuming Distance is in meters
    (Strava's API and, per long-standing community parsing scripts, its CSV
    export both use meters). 90 s/km is a 2:30/km sprint; 1200 s/km is a
    20:00/km walk-run, generous on both ends.
    """
    if distance_m <= 0:
        return False
    pace = moving_time_s / (distance_m / 1000.0)
    return lo <= pace <= hi
