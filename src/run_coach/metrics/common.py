"""Shared helpers for the metrics modules: what counts as a run, and the
minimum sample size before we'll show a conclusion instead of "not enough
data yet".
"""

from __future__ import annotations

from datetime import date, datetime

MIN_SAMPLE_SIZE = 8


def is_running(activity_type: str | None) -> bool:
    if not activity_type:
        return False
    return "run" in activity_type.lower()


def parse_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def local_date_of(row) -> date:
    return date.fromisoformat(row["local_date"])


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def pace_str(seconds_per_km: float | None) -> str | None:
    if seconds_per_km is None:
        return None
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}/km"
