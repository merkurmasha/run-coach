"""The dashboard's global time-range switcher: last 7 days, 4 weeks, 3
months, 1 year, or all time. Each named range also has a "previous equal
period" immediately before it, used for the progress deltas.
"""

from __future__ import annotations

from datetime import date, timedelta

from run_coach.metrics.common import local_date_of

RANGE_DAYS = {"7d": 7, "4w": 28, "3m": 90, "1y": 365, "all": None}
DEFAULT_RANGE = "4w"


def range_bounds(range_key: str, as_of: date | None = None) -> tuple[date | None, date]:
    """(start, end) for the named range. start is None for "all"."""
    if as_of is None:
        as_of = date.today()
    days = RANGE_DAYS.get(range_key, RANGE_DAYS[DEFAULT_RANGE])
    if days is None:
        return None, as_of
    return as_of - timedelta(days=days - 1), as_of


def previous_period_bounds(range_key: str, as_of: date | None = None) -> tuple[date, date] | None:
    """The equal-length period immediately before the current range. None for "all"."""
    start, _end = range_bounds(range_key, as_of)
    if start is None:
        return None
    days = RANGE_DAYS[range_key if range_key in RANGE_DAYS else DEFAULT_RANGE]
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return previous_start, previous_end


def filter_by_bounds(activities: list, start: date | None, end: date) -> list:
    if start is None:
        return [a for a in activities if local_date_of(a) <= end]
    return [a for a in activities if start <= local_date_of(a) <= end]
