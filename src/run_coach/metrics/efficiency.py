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
    local_date_of,
    month_key,
)

DEFAULT_REFERENCE_HR = 150.0


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
