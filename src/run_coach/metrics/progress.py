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

from run_coach.metrics.common import is_running, local_date_of, month_key, pace_str

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
