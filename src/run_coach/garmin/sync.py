"""Orchestrates a Garmin sync: fetch, parse defensively, upsert into SQLite."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from run_coach.config import GARMIN_MAX_HISTORY_DAYS
from run_coach.garmin.client import (
    GarminClient,
    chunk_date_range,
    dig,
    parse_activity,
    parse_hr_zone_minutes,
)
from run_coach.storage.db import Activity, upsert_activity, upsert_cycle_entry, upsert_daily_metric


def sync_garmin(
    conn: sqlite3.Connection,
    api_key: str | None = None,
    days: int = GARMIN_MAX_HISTORY_DAYS,
    client: GarminClient | None = None,
) -> dict:
    """Sync up to `days` of history (capped at GARMIN_MAX_HISTORY_DAYS).

    `client` can be injected (e.g. a fake in tests) to avoid constructing a
    real GarminClient, which exchanges the API key for a token on init.

    Returns {"counts": {...}, "data_gaps": [...], "range": {...}}.
    """
    days = min(days, GARMIN_MAX_HISTORY_DAYS)
    end = date.today()
    start = end - timedelta(days=days - 1)
    gaps: list[str] = []
    counts = {"activities": 0, "sleep_days": 0, "hrv_days": 0, "body_battery_days": 0, "stress_days": 0, "resting_hr_days": 0, "cycle_entries": 0}

    owns_client = client is None
    client = client or GarminClient(api_key)
    try:
        for chunk_start, chunk_end in chunk_date_range(start, end):
            for raw in client.search_activities(chunk_start, chunk_end, gaps):
                parsed = parse_activity(raw, gaps)
                if parsed is None or parsed.start_time_utc is None:
                    continue
                zone_minutes = parse_hr_zone_minutes(raw)
                upsert_activity(
                    conn,
                    Activity(
                        source="garmin",
                        external_id=parsed.external_id,
                        start_time_utc=parsed.start_time_utc,
                        local_date=parsed.local_date or parsed.start_time_utc[:10],
                        activity_type=parsed.activity_type,
                        distance_m=parsed.distance_m,
                        moving_time_s=parsed.moving_time_s,
                        elapsed_time_s=parsed.elapsed_time_s,
                        avg_hr=parsed.avg_hr,
                        max_hr=parsed.max_hr,
                        avg_pace_s_per_km=_pace_s_per_km(parsed.distance_m, parsed.moving_time_s),
                        elevation_gain_m=parsed.elevation_gain_m,
                        calories=parsed.calories,
                        hr_zone_minutes=zone_minutes,
                    ),
                )
                counts["activities"] += 1

            for entry in client.daily_sleep_summaries(chunk_start, chunk_end, gaps):
                day = dig(entry, "calendarDate", "dailySleepDTO.calendarDate")
                duration = dig(entry, "sleepTimeSeconds", "dailySleepDTO.sleepTimeSeconds")
                score = dig(entry, "sleepScores.overall.value", "dailySleepDTO.sleepScores.overall.value")
                if day is None:
                    continue
                upsert_daily_metric(conn, str(day)[:10], sleep_duration_s=duration, sleep_score=score)
                if duration is not None or score is not None:
                    counts["sleep_days"] += 1

            for entry in client.daily_hrv_summaries(chunk_start, chunk_end, gaps):
                day = dig(entry, "calendarDate")
                hrv = dig(entry, "lastNightAvg", "weeklyAvg", "lastNight5MinHigh")
                if day is None or hrv is None:
                    continue
                upsert_daily_metric(conn, str(day)[:10], hrv_ms=hrv)
                counts["hrv_days"] += 1

            for entry in client.daily_body_battery(chunk_start, chunk_end, gaps):
                day = dig(entry, "date", "calendarDate")
                high = dig(entry, "highestBodyBattery", "charged")
                low = dig(entry, "lowestBodyBattery", "drained")
                if day is None:
                    continue
                upsert_daily_metric(conn, str(day)[:10], body_battery_high=high, body_battery_low=low)
                if high is not None or low is not None:
                    counts["body_battery_days"] += 1

            for entry in client.daily_stress(chunk_start, chunk_end, gaps):
                day = dig(entry, "calendarDate", "date")
                stress = dig(entry, "averageStressLevel", "overallStressLevel", "avgStressLevel")
                if day is None or stress is None:
                    continue
                upsert_daily_metric(conn, str(day)[:10], stress_avg=stress)
                counts["stress_days"] += 1

            for entry in client.daily_summaries(chunk_start, chunk_end, gaps):
                day = dig(entry, "calendarDate", "date")
                resting_hr = dig(entry, "restingHeartRate", "restingHr")
                if day is None or resting_hr is None:
                    continue
                upsert_daily_metric(conn, str(day)[:10], resting_hr=resting_hr)
                counts["resting_hr_days"] += 1

        cycle_summary = client.menstrual_cycle_summary(end, gaps)
        if cycle_summary:
            period_starts = dig(cycle_summary, "periodStartDates", "cycleStartDates") or []
            cycle_length = dig(cycle_summary, "cycleLength", "averageCycleLength")
            if isinstance(period_starts, list):
                for entry_date in period_starts:
                    upsert_cycle_entry(conn, str(entry_date)[:10], cycle_length, source="garmin")
                    counts["cycle_entries"] += 1
            if counts["cycle_entries"] == 0:
                gaps.append("cycle: Garmin returned no period start dates for this account")
        else:
            gaps.append("cycle: not available from Garmin for this account (use manual entry in setup instead)")
    finally:
        if owns_client:
            client.close()

    return {
        "counts": counts,
        "data_gaps": gaps,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
    }


def _pace_s_per_km(distance_m: float | None, moving_time_s: float | None) -> float | None:
    if not distance_m or not moving_time_s or distance_m <= 0:
        return None
    return moving_time_s / (distance_m / 1000.0)
