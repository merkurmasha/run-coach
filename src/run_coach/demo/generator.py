"""Synthetic data for --demo: a plausible 9-month training history with no
real keys and no personal data, so the dashboard can be tried (and
screenshotted) without a Garmin account.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

from run_coach.metrics.aggregate import build_stats
from run_coach.storage.db import (
    Activity,
    set_cached_recommendations,
    set_setting,
    upsert_activity,
    upsert_cycle_entry,
    upsert_daily_metric,
)

DEMO_RECOMMENDATIONS = [
    {
        "text": (
            "Your monthly distance has grown steadily over this training block without a matching jump in "
            "pace-at-reference-heart-rate, which is consistent with building aerobic base before intensity."
        ),
        "evidence": "moderate",
        "rationale": "progressive-overload trend read from monthly distance and the pace-at-HR regression",
    },
    {
        "text": (
            "Recent HRV and resting heart rate sit close to your own 28-day baseline, so nothing in recovery "
            "is flagging overreaching right now."
        ),
        "evidence": "strong",
        "rationale": "7-day vs. trailing 28-day baseline comparison",
    },
    {
        "text": (
            "Heart-rate zone time this period is fairly evenly spread across zones rather than concentrated in "
            "an easy zone, which is worth a look if the goal is a bigger easy-running base."
        ),
        "evidence": "hypothesis",
        "rationale": "zone-distribution share across logged activities",
    },
    {
        "text": (
            "You've noted shin tightness after longer runs; if that persists or worsens, it's worth getting a "
            "physiotherapist's opinion rather than adjusting training on a guess."
        ),
        "evidence": "strong",
        "rationale": "logged special-conditions text naming a possible injury",
    },
]

DEMO_SEED = 20261109


def generate_demo_data(conn: sqlite3.Connection, days: int = 270) -> None:
    rng = random.Random(DEMO_SEED)
    today = date.today()
    start = today - timedelta(days=days)

    base_pace = 330.0  # 5:30/km, improves slowly over the period
    activity_counter = 0

    day = start
    while day <= today:
        # ~4 runs/week, skip some days, long run on Sundays
        is_long_run_day = day.weekday() == 6
        runs_this_week_chance = 0.6 if not is_long_run_day else 0.85
        if rng.random() < runs_this_week_chance:
            progress_fraction = (day - start).days / max(days, 1)
            pace = base_pace - 25 * progress_fraction + rng.uniform(-15, 15)
            distance_km = rng.uniform(9, 16) if is_long_run_day else rng.uniform(4, 9)
            distance_m = distance_km * 1000
            moving_time_s = pace * distance_km
            avg_hr = 150 + rng.uniform(-8, 10) - 10 * progress_fraction
            activity_counter += 1
            upsert_activity(
                conn,
                Activity(
                    source="garmin",
                    external_id=f"demo-{activity_counter}",
                    start_time_utc=f"{day.isoformat()}T06:30:00Z",
                    local_date=day.isoformat(),
                    activity_type="running",
                    distance_m=round(distance_m, 1),
                    moving_time_s=round(moving_time_s, 1),
                    elapsed_time_s=round(moving_time_s + rng.uniform(20, 90), 1),
                    avg_hr=round(avg_hr, 1),
                    max_hr=round(avg_hr + rng.uniform(15, 25), 1),
                    avg_pace_s_per_km=round(moving_time_s / distance_km, 1),
                    elevation_gain_m=round(rng.uniform(10, 120), 1),
                    calories=round(distance_km * 65, 1),
                    hr_zone_minutes=_synthetic_zones(rng, moving_time_s),
                ),
            )

        upsert_daily_metric(
            conn,
            day.isoformat(),
            sleep_duration_s=rng.uniform(6.0, 8.5) * 3600,
            sleep_score=rng.uniform(60, 92),
            hrv_ms=rng.uniform(42, 60),
            resting_hr=rng.uniform(48, 58),
            body_battery_high=rng.uniform(75, 100),
            body_battery_low=rng.uniform(10, 35),
            stress_avg=rng.uniform(15, 45),
        )
        day += timedelta(days=1)

    # A synthetic 28-day cycle history for the patterns section.
    cycle_day = start
    while cycle_day <= today:
        upsert_cycle_entry(conn, cycle_day.isoformat(), 28, source="manual")
        cycle_day += timedelta(days=28)

    set_setting(conn, "demo_mode", True)
    set_setting(conn, "runs_per_week", 4)
    set_setting(conn, "follows_watch_plan", False)
    set_setting(conn, "target_pace_s_per_km", 300)
    set_setting(conn, "race_distance_m", 21097.5)
    set_setting(conn, "race_date", (today + timedelta(days=90)).isoformat())
    set_setting(conn, "special_conditions_text", "Mild shin tightness after longer runs (demo data).")
    set_setting(conn, "timezone", "UTC")
    set_setting(conn, "units", "km")

    stats = build_stats(conn)
    set_cached_recommendations(conn, stats, DEMO_RECOMMENDATIONS)


def _synthetic_zones(rng: random.Random, moving_time_s: float) -> dict[int, float]:
    minutes = moving_time_s / 60.0
    weights = [rng.uniform(0.5, 1.5) for _ in range(5)]
    total_weight = sum(weights)
    return {zone: round(minutes * w / total_weight, 1) for zone, w in enumerate(weights, start=1)}
