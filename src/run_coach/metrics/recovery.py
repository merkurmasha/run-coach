"""Recovery: sleep, HRV, and resting heart rate against the user's own
trailing 28-day baseline. Garmin-only; there is no Strava equivalent.

Method: baseline = the mean of a metric over the 28 days before the most
recent 7, excluding gaps (missing days are simply not counted, and n says
how many days actually went into each average).
"""

from __future__ import annotations

from datetime import date, timedelta

RECENT_WINDOW_DAYS = 7
BASELINE_WINDOW_DAYS = 28

METRICS = ["sleep_duration_s", "sleep_score", "hrv_ms", "resting_hr"]


def _window_avg(daily_metrics: list, metric: str, start: date, end: date) -> tuple[float | None, int]:
    values = [
        row[metric]
        for row in daily_metrics
        if row[metric] is not None and start <= date.fromisoformat(row["date"]) <= end
    ]
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def recovery_summary(daily_metrics: list, as_of: date | None = None) -> dict:
    if not daily_metrics:
        return {metric: {"recent_avg": None, "baseline_avg": None, "n_recent": 0, "n_baseline": 0, "delta": None} for metric in METRICS}

    if as_of is None:
        as_of = max(date.fromisoformat(row["date"]) for row in daily_metrics)

    recent_start = as_of - timedelta(days=RECENT_WINDOW_DAYS - 1)
    baseline_end = recent_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=BASELINE_WINDOW_DAYS - 1)

    summary = {}
    for metric in METRICS:
        recent_avg, n_recent = _window_avg(daily_metrics, metric, recent_start, as_of)
        baseline_avg, n_baseline = _window_avg(daily_metrics, metric, baseline_start, baseline_end)
        delta = (recent_avg - baseline_avg) if recent_avg is not None and baseline_avg is not None else None
        summary[metric] = {
            "recent_avg": round(recent_avg, 1) if recent_avg is not None else None,
            "baseline_avg": round(baseline_avg, 1) if baseline_avg is not None else None,
            "n_recent": n_recent,
            "n_baseline": n_baseline,
            "delta": round(delta, 1) if delta is not None else None,
        }
    return summary
