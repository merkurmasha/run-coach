"""Strava bulk-export activities.csv parser.

We never call the Strava API (per the project's design: this is a one-time,
user-initiated upload of the user's own export, not a live integration).
Strava's exact CSV header set has shifted over the years and is translated
to the account's display language, and some exports carry duplicate header
names across activity types. Rather than assume one fixed header row, we
match each logical field against several candidate header spellings and
skip (recording a gap) when nothing matches — never guess a value.

The Spanish and Russian candidates below are best-effort: we don't have a
real export in either language to verify against (same caveat as Garmin's
undocumented response fields -- see garmin/client.py). If a real export
doesn't match, the column-mapping step covers it.

Columns we intentionally never read: any header containing "description" or
"note" (case-insensitive) — that's "Activity Description" and "Private
Note" in English exports, which the project must never store.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EXCLUDED_HEADER_SUBSTRINGS = ("description", "note", "nota", "описание", "заметка")

FIELD_CANDIDATES = {
    "id": ["Activity ID", "ID de la actividad", "ID активности"],
    "date": ["Activity Date", "Fecha de la actividad", "Дата активности"],
    "type": ["Activity Type", "Tipo de actividad", "Тип активности"],
    "distance": ["Distance", "Distancia", "Дистанция"],
    "moving_time": ["Moving Time", "Tiempo en movimiento", "Время в движении"],
    "elapsed_time": ["Elapsed Time", "Tiempo transcurrido", "Затраченное время"],
    "avg_hr": ["Average Heart Rate", "Frecuencia cardíaca media", "Средний пульс"],
    "max_hr": ["Max Heart Rate", "Frecuencia cardíaca máxima", "Максимальный пульс"],
    "elevation_gain": ["Elevation Gain", "Desnivel positivo", "Набор высоты"],
    "calories": ["Calories", "Calorías", "Калории"],
}

REQUIRED_FIELDS = ("id", "date", "type")

# Strava's CSV export has used a few date formats over the years.
DATE_FORMATS = [
    "%b %d, %Y, %I:%M:%S %p",  # "Dec 23, 2023, 7:15:32 AM"
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]

RUN_TYPES = {"run", "trail run", "virtual run"}

DURATION_RE = re.compile(r"^\d+:\d{2}(:\d{2})?$")


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


def inspect_header(path: Path) -> dict:
    """What the importer could and couldn't match, without importing anything.

    Used by the web layer to decide whether to show a column-mapping step
    instead of silently importing zero rows.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
    column_map = _build_column_map(fieldnames)
    return {
        "available_headers": fieldnames,
        "matched_fields": column_map,
        "missing_required_fields": [f for f in REQUIRED_FIELDS if f not in column_map],
    }


def _safe_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    # European-style decimal comma ("5,0"), vs. a thousands-separator comma
    # ("1,234.56") which we strip instead.
    if "," in value and "." not in value:
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    if "," in value and "." in value:
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _parse_duration_seconds(value: str | None) -> float | None:
    """Accept both Strava's usual raw-seconds export and an "H:MM:SS" string."""
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    if DURATION_RE.match(value):
        parts = [int(p) for p in value.split(":")]
        if len(parts) == 3:
            h, m, s = parts
        else:
            h, m, s = 0, *parts
        return float(h * 3600 + m * 60 + s)
    return _safe_float(value)


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_strava_csv(
    path: Path, column_overrides: dict[str, str] | None = None
) -> tuple[list[ParsedStravaActivity], list[str]]:
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
        if column_overrides:
            for field, header_name in column_overrides.items():
                if header_name and header_name in reader.fieldnames:
                    column_map[field] = header_name
        required_missing = [f for f in REQUIRED_FIELDS if f not in column_map]
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
            moving_time_s = _parse_duration_seconds(row.get(column_map.get("moving_time", ""), None))
            elapsed_time_s = _parse_duration_seconds(row.get(column_map.get("elapsed_time", ""), None))

            if (
                activity_type.lower() in RUN_TYPES
                and distance_m
                and moving_time_s
                and not _plausible_running_pace(distance_m, moving_time_s)
            ):
                if _plausible_running_pace(distance_m * 1000, moving_time_s):
                    gaps.append(
                        f"strava activity {external_id}: Distance column looks like it's in km, not "
                        "meters; auto-converted"
                    )
                    distance_m = distance_m * 1000
                else:
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
