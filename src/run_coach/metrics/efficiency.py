"""Aerobic efficiency: monthly pace at a fixed reference heart rate.

Method (shown on the dashboard): for each month with at least
MIN_SAMPLE_SIZE runs that have both a pace and an average heart rate, fit a
least-squares line of pace (s/km) against average heart rate, then read off
the line's predicted pace at the reference heart rate. A falling line
(faster pace at the same heart rate, month over month) is the signal of
improving aerobic efficiency. Months with fewer runs show "not enough data
yet" instead of a fitted value.
"""

from __future__ import annotations

from run_coach.metrics.common import (
    MIN_SAMPLE_SIZE,
    is_running,
    iso_week_key,
    local_date_of,
    month_key,
)
from run_coach.metrics.ranges import filter_by_bounds, range_bounds

DEFAULT_REFERENCE_HR = 150.0
TREND_ROLLING_WEEKS = 8


def hr_coverage(activities: list) -> dict:
    """How many running activities (overall, and from Strava specifically)
    have heart-rate data -- the number behind every "needs heart-rate
    data" empty state, so the dashboard can say exactly how far off it is
    instead of just "not enough data yet".
    """
    runs = [a for a in activities if is_running(a["activity_type"])]
    strava_runs = [r for r in runs if r["source"] == "strava"]
    return {
        "total_runs": len(runs),
        "runs_with_hr": sum(1 for r in runs if r["avg_hr"] is not None),
        "strava_total": len(strava_runs),
        "strava_with_hr": sum(1 for r in strava_runs if r["avg_hr"] is not None),
    }


def _least_squares(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return None
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept


def monthly_pace_at_hr(activities: list, reference_hr: float = DEFAULT_REFERENCE_HR) -> list[dict]:
    runs = [
        a
        for a in activities
        if is_running(a["activity_type"]) and a["avg_pace_s_per_km"] and a["avg_hr"]
    ]
    months: dict[str, list] = {}
    for row in runs:
        months.setdefault(month_key(local_date_of(row)), []).append(row)

    out = []
    for key in sorted(months):
        rows = months[key]
        n = len(rows)
        if n < MIN_SAMPLE_SIZE:
            out.append({"month": key, "n": n, "pace_at_reference_hr_s_per_km": None, "reason": "not enough data yet"})
            continue
        fit = _least_squares([r["avg_hr"] for r in rows], [r["avg_pace_s_per_km"] for r in rows])
        if fit is None:
            out.append({"month": key, "n": n, "pace_at_reference_hr_s_per_km": None, "reason": "no heart-rate variation to fit"})
            continue
        slope, intercept = fit
        predicted_pace = slope * reference_hr + intercept
        out.append(
            {
                "month": key,
                "n": n,
                "pace_at_reference_hr_s_per_km": round(predicted_pace, 1),
                "reference_hr": reference_hr,
            }
        )
    return out


def pace_at_hr_trend(
    activities: list,
    range_key: str,
    as_of=None,
    reference_hr: float = DEFAULT_REFERENCE_HR,
    rolling_weeks: int = TREND_ROLLING_WEEKS,
) -> list[dict]:
    """A weekly pace-at-reference-HR trend for the selected range.

    Method: each week's point is fit from all qualifying runs in a trailing
    `rolling_weeks`-week window ending that week (not just that single
    week), because a week alone rarely has MIN_SAMPLE_SIZE runs. A week
    whose rolling window still doesn't have enough runs shows "not enough
    data yet" instead of a fitted value.
    """
    start, end = range_bounds(range_key, as_of)
    runs = [
        a
        for a in activities
        if is_running(a["activity_type"]) and a["avg_pace_s_per_km"] and a["avg_hr"]
    ]
    in_range = filter_by_bounds(runs, start, end)
    if not in_range:
        return []

    weeks_present = sorted({iso_week_key(local_date_of(r)) for r in in_range})
    out = []
    for key in weeks_present:
        # ISO week keys sort lexicographically in date order within a range this short.
        window_runs = [
            r
            for r in runs
            if iso_week_key(local_date_of(r)) <= key
            and _weeks_between(iso_week_key(local_date_of(r)), key) < rolling_weeks
        ]
        n = len(window_runs)
        if n < MIN_SAMPLE_SIZE:
            out.append({"week": key, "n": n, "pace_at_reference_hr_s_per_km": None, "reason": "not enough data yet"})
            continue
        fit = _least_squares([r["avg_hr"] for r in window_runs], [r["avg_pace_s_per_km"] for r in window_runs])
        if fit is None:
            out.append({"week": key, "n": n, "pace_at_reference_hr_s_per_km": None, "reason": "no heart-rate variation to fit"})
            continue
        slope, intercept = fit
        out.append(
            {
                "week": key,
                "n": n,
                "pace_at_reference_hr_s_per_km": round(slope * reference_hr + intercept, 1),
                "reference_hr": reference_hr,
            }
        )
    return out


def _weeks_between(week_a: str, week_b: str) -> int:
    """Approximate week distance between two "YYYY-Www" keys (good enough
    for a rolling-window cutoff; a year boundary is off by at most 1 week)."""
    ya, wa = int(week_a[:4]), int(week_a[6:])
    yb, wb = int(week_b[:4]), int(week_b[6:])
    return (yb - ya) * 52 + (wb - wa)
