"""Progress: monthly volume, personal bests, and a Riegel race-time estimate.

Method notes (shown on the dashboard via the "method" tooltip):
- Personal bests only consider whole activities whose total distance is
  within a tolerance band of the target race distance (GPS/course distance
  varies run to run) -- never a best split pulled out of a longer run.
- Race-time predictions use Riegel's formula, T2 = T1 * (D2/D1)^1.06, from
  the single longest personal best on record (longer efforts extrapolate
  more reliably than short ones). Always labelled an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

from run_coach.metrics.common import (
    is_running,
    iso_week_key,
    local_date_of,
    month_key,
    pace_str,
)
from run_coach.metrics.ranges import (
    filter_by_bounds,
    previous_period_bounds,
    range_bounds,
)

RIEGEL_EXPONENT = 1.06

PB_TARGETS = {
    "5k": (5000.0, 0.98, 1.05),
    "10k": (10000.0, 0.98, 1.05),
    "half_marathon": (21097.5, 0.98, 1.05),
}

PREDICTION_TARGETS = {
    "5k": 5000.0,
    "10k": 10000.0,
    "half_marathon": 21097.5,
    "marathon": 42195.0,
}


@dataclass
class PersonalBest:
    distance_label: str
    activity_id: str
    moving_time_s: float
    distance_m: float
    date: str

    @property
    def pace_s_per_km(self) -> float:
        return self.moving_time_s / (self.distance_m / 1000.0)


def monthly_progress(activities: list) -> list[dict]:
    runs = [a for a in activities if is_running(a["activity_type"])]
    months: dict[str, dict] = {}
    for row in runs:
        key = month_key(local_date_of(row))
        bucket = months.setdefault(key, {"distance_m": 0.0, "moving_time_s": 0.0, "runs": 0})
        bucket["distance_m"] += row["distance_m"] or 0.0
        bucket["moving_time_s"] += row["moving_time_s"] or 0.0
        bucket["runs"] += 1

    out = []
    for key in sorted(months):
        bucket = months[key]
        avg_pace = bucket["moving_time_s"] / (bucket["distance_m"] / 1000.0) if bucket["distance_m"] else None
        out.append(
            {
                "month": key,
                "distance_km": round(bucket["distance_m"] / 1000.0, 1),
                "runs": bucket["runs"],
                "avg_pace_s_per_km": avg_pace,
                "avg_pace": pace_str(avg_pace),
            }
        )
    return out


def personal_bests(activities: list) -> dict[str, PersonalBest | None]:
    runs = [a for a in activities if is_running(a["activity_type"]) and a["distance_m"] and a["moving_time_s"]]
    results: dict[str, PersonalBest | None] = {}
    for label, (target_m, lo_frac, hi_frac) in PB_TARGETS.items():
        candidates = [
            row for row in runs if target_m * lo_frac <= row["distance_m"] <= target_m * hi_frac
        ]
        if not candidates:
            results[label] = None
            continue
        best = min(candidates, key=lambda r: r["moving_time_s"])
        results[label] = PersonalBest(
            distance_label=label,
            activity_id=best["id"],
            moving_time_s=best["moving_time_s"],
            distance_m=best["distance_m"],
            date=best["local_date"],
        )
    return results


def riegel_predict(known_distance_m: float, known_time_s: float, target_distance_m: float) -> float:
    return known_time_s * (target_distance_m / known_distance_m) ** RIEGEL_EXPONENT


def race_time_predictions(pbs: dict[str, PersonalBest | None]) -> dict[str, dict | None]:
    known = [pb for pb in pbs.values() if pb is not None]
    if not known:
        return {label: None for label in PREDICTION_TARGETS}

    source = max(known, key=lambda pb: pb.distance_m)
    predictions: dict[str, dict | None] = {}
    for label, target_m in PREDICTION_TARGETS.items():
        if pbs.get(label) is not None and pbs[label].distance_m == source.distance_m:
            # This is the source itself: report the measured time, not a prediction.
            predictions[label] = {
                "seconds": source.moving_time_s,
                "is_measured": True,
                "source": label,
            }
            continue
        seconds = riegel_predict(source.distance_m, source.moving_time_s, target_m)
        predictions[label] = {
            "seconds": seconds,
            "is_measured": False,
            "source": source.distance_label,
        }
    return predictions


def _period_summary(runs: list) -> dict:
    distance_m = sum(r["distance_m"] or 0.0 for r in runs)
    moving_time_s = sum(r["moving_time_s"] or 0.0 for r in runs)
    longest_m = max((r["distance_m"] or 0.0 for r in runs), default=0.0)
    return {
        "distance_km": round(distance_m / 1000.0, 1),
        "runs": len(runs),
        "avg_pace_s_per_km": round(moving_time_s / (distance_m / 1000.0), 1) if distance_m else None,
        "longest_run_km": round(longest_m / 1000.0, 1),
    }


def range_progress(activities: list, range_key: str, as_of=None) -> dict:
    """Headline progress numbers for the selected range, plus the delta
    against the immediately preceding, equal-length period ("all" has no
    previous period, so delta is None there)."""
    runs = [a for a in activities if is_running(a["activity_type"])]
    start, end = range_bounds(range_key, as_of)
    current_summary = _period_summary(filter_by_bounds(runs, start, end))

    previous_bounds = previous_period_bounds(range_key, as_of)
    if previous_bounds is None:
        return {"current": current_summary, "previous": None, "delta": None}

    previous_summary = _period_summary(filter_by_bounds(runs, previous_bounds[0], previous_bounds[1]))
    delta = {
        key: round(current_summary[key] - previous_summary[key], 1)
        for key in ("distance_km", "runs", "longest_run_km")
    }
    if current_summary["avg_pace_s_per_km"] is not None and previous_summary["avg_pace_s_per_km"] is not None:
        delta["avg_pace_s_per_km"] = round(
            current_summary["avg_pace_s_per_km"] - previous_summary["avg_pace_s_per_km"], 1
        )
    else:
        delta["avg_pace_s_per_km"] = None

    return {"current": current_summary, "previous": previous_summary, "delta": delta}


def weekly_distance_series(activities: list, range_key: str, as_of=None) -> list[dict]:
    """Weekly distance within the selected range, for the progress chart."""
    start, end = range_bounds(range_key, as_of)
    runs = filter_by_bounds([a for a in activities if is_running(a["activity_type"])], start, end)
    weeks: dict[str, float] = {}
    for row in runs:
        key = iso_week_key(local_date_of(row))
        weeks[key] = weeks.get(key, 0.0) + (row["distance_m"] or 0.0)
    return [{"week": key, "distance_km": round(weeks[key] / 1000.0, 1)} for key in sorted(weeks)]


def pace_trend_series(activities: list, range_key: str, as_of=None, rolling_window: int = 4) -> list[dict]:
    """Weekly average pace within the range, plus a trailing N-week rolling
    average (default 4 weeks) to smooth out single noisy weeks."""
    start, end = range_bounds(range_key, as_of)
    runs = filter_by_bounds(
        [a for a in activities if is_running(a["activity_type"]) and a["distance_m"] and a["moving_time_s"]],
        start,
        end,
    )
    weeks: dict[str, dict] = {}
    for row in runs:
        key = iso_week_key(local_date_of(row))
        bucket = weeks.setdefault(key, {"distance_m": 0.0, "moving_time_s": 0.0})
        bucket["distance_m"] += row["distance_m"]
        bucket["moving_time_s"] += row["moving_time_s"]

    ordered_keys = sorted(weeks)
    paces = [
        (weeks[key]["moving_time_s"] / (weeks[key]["distance_m"] / 1000.0)) if weeks[key]["distance_m"] else None
        for key in ordered_keys
    ]

    out = []
    for i, key in enumerate(ordered_keys):
        window = [p for p in paces[max(0, i - rolling_window + 1) : i + 1] if p is not None]
        rolling = round(sum(window) / len(window), 1) if window else None
        out.append(
            {
                "week": key,
                "avg_pace_s_per_km": round(paces[i], 1) if paces[i] is not None else None,
                "rolling_avg_pace_s_per_km": rolling,
            }
        )
    return out


def personal_bests_timeline(activities: list) -> list[dict]:
    """Every time a new personal best was set, in chronological order --
    one event per improvement, for the PB timeline chart."""
    runs = [a for a in activities if is_running(a["activity_type"]) and a["distance_m"] and a["moving_time_s"]]
    events = []
    for label, (target_m, lo_frac, hi_frac) in PB_TARGETS.items():
        candidates = sorted(
            (r for r in runs if target_m * lo_frac <= r["distance_m"] <= target_m * hi_frac),
            key=lambda r: r["local_date"],
        )
        best_time = None
        for r in candidates:
            if best_time is None or r["moving_time_s"] < best_time:
                best_time = r["moving_time_s"]
                events.append(
                    {
                        "distance_label": label,
                        "date": r["local_date"],
                        "moving_time_s": r["moving_time_s"],
                        "pace_s_per_km": round(r["moving_time_s"] / (r["distance_m"] / 1000.0), 1),
                    }
                )
    events.sort(key=lambda e: e["date"])
    return events


def race_markers(activities: list, range_key: str | None = None, as_of=None) -> list[dict]:
    """Activities tagged as a race, for annotating the progress charts."""
    races = [a for a in activities if a["is_race"]]
    if range_key is not None:
        start, end = range_bounds(range_key, as_of)
        races = filter_by_bounds(races, start, end)
    return [
        {
            "id": r["id"],
            "date": r["local_date"],
            "activity_type": r["activity_type"],
            "distance_km": round((r["distance_m"] or 0.0) / 1000.0, 1),
            "pace_s_per_km": r["avg_pace_s_per_km"],
            "name": r["race_name"],
        }
        for r in sorted(races, key=lambda r: r["local_date"])
    ]
