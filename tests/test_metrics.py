import sqlite3

from run_coach.metrics.common import MIN_SAMPLE_SIZE
from run_coach.metrics.efficiency import monthly_pace_at_hr
from run_coach.metrics.load import weekly_volume
from run_coach.metrics.patterns import cycle_phase_patterns
from run_coach.metrics.progress import (
    PersonalBest,
    monthly_progress,
    personal_bests,
    race_time_predictions,
    riegel_predict,
)
from run_coach.metrics.recovery import recovery_summary
from run_coach.storage.db import Activity, connect, init_db, upsert_activity, upsert_cycle_entry, upsert_daily_metric


def make_run(i, local_date, distance_m, moving_time_s, avg_hr=150.0):
    return Activity(
        source="garmin",
        external_id=str(i),
        start_time_utc=f"{local_date}T06:00:00Z",
        local_date=local_date,
        activity_type="running",
        distance_m=distance_m,
        moving_time_s=moving_time_s,
        elapsed_time_s=moving_time_s + 20,
        avg_hr=avg_hr,
        max_hr=avg_hr + 15,
        avg_pace_s_per_km=moving_time_s / (distance_m / 1000.0),
        elevation_gain_m=10.0,
        calories=300.0,
    )


def seeded_conn(tmp_path, activities):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    for a in activities:
        upsert_activity(conn, a)
    conn.commit()
    return conn


def rows(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM activities ORDER BY start_time_utc").fetchall()


def test_monthly_progress_aggregates_distance_and_pace(tmp_path):
    activities = [
        make_run(1, "2026-01-05", 5000, 1500),
        make_run(2, "2026-01-12", 5000, 1600),
        make_run(3, "2026-02-01", 10000, 3200),
    ]
    conn = seeded_conn(tmp_path, activities)
    months = monthly_progress(rows(conn))
    jan = next(m for m in months if m["month"] == "2026-01")
    assert jan["runs"] == 2
    assert jan["distance_km"] == 10.0
    assert jan["avg_pace_s_per_km"] == (1500 + 1600) / (10.0)
    conn.close()


def test_personal_bests_only_count_whole_activities_near_target_distance(tmp_path):
    activities = [
        make_run(1, "2026-01-05", 5050, 1200),  # qualifies for 5k PB
        make_run(2, "2026-01-12", 16000, 4800),  # not within any PB band
    ]
    conn = seeded_conn(tmp_path, activities)
    pbs = personal_bests(rows(conn))
    assert pbs["5k"] is not None
    assert pbs["5k"].moving_time_s == 1200
    assert pbs["10k"] is None
    conn.close()


def test_riegel_predicts_slower_time_for_longer_distance():
    predicted = riegel_predict(known_distance_m=5000, known_time_s=1200, target_distance_m=10000)
    assert predicted > 1200 * 2  # Riegel's exponent > 1 means more than double for double distance
    assert predicted < 1200 * 2.2


def test_race_time_predictions_reports_measured_for_the_source_pb():
    pbs = {
        "5k": PersonalBest("5k", "a", 1200.0, 5000.0, "2026-01-01"),
        "10k": None,
        "half_marathon": None,
    }
    predictions = race_time_predictions(pbs)
    assert predictions["5k"]["is_measured"] is True
    assert predictions["10k"]["is_measured"] is False
    assert predictions["10k"]["seconds"] > predictions["5k"]["seconds"]


def test_efficiency_requires_minimum_sample_size(tmp_path):
    few = [make_run(i, f"2026-01-{i:02d}", 5000, 1500 + i * 5) for i in range(1, MIN_SAMPLE_SIZE)]
    conn = seeded_conn(tmp_path, few)
    result = monthly_pace_at_hr(rows(conn))
    assert result[0]["pace_at_reference_hr_s_per_km"] is None
    assert result[0]["reason"] == "not enough data yet"
    conn.close()


def test_efficiency_fits_with_enough_samples(tmp_path):
    many = [
        make_run(i, f"2026-01-{i:02d}", 5000, 1400 + i * 10, avg_hr=140 + i)
        for i in range(1, MIN_SAMPLE_SIZE + 2)
    ]
    conn = seeded_conn(tmp_path, many)
    result = monthly_pace_at_hr(rows(conn))
    assert result[0]["pace_at_reference_hr_s_per_km"] is not None
    conn.close()


def test_weekly_volume_groups_by_iso_week(tmp_path):
    activities = [make_run(1, "2026-01-05", 5000, 1500), make_run(2, "2026-01-06", 5000, 1500)]
    conn = seeded_conn(tmp_path, activities)
    weeks = weekly_volume(rows(conn))
    assert len(weeks) == 1
    assert weeks[0]["runs"] == 2
    assert weeks[0]["distance_km"] == 10.0
    conn.close()


def test_recovery_baseline_uses_prior_28_days_not_recent_window(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    from datetime import date, timedelta

    today = date(2026, 3, 1)
    for i in range(35):
        d = today - timedelta(days=i)
        hrv = 40.0 if i < 7 else 50.0  # recent week lower than the prior baseline
        upsert_daily_metric(conn, d.isoformat(), hrv_ms=hrv)
    conn.commit()

    summary = recovery_summary(conn.execute("SELECT * FROM daily_metrics").fetchall(), as_of=today)
    assert summary["hrv_ms"]["recent_avg"] == 40.0
    assert summary["hrv_ms"]["baseline_avg"] == 50.0
    assert summary["hrv_ms"]["n_baseline"] == 28
    assert summary["hrv_ms"]["delta"] == -10.0
    conn.close()


def test_cycle_phase_patterns_respects_minimum_sample_size(tmp_path):
    activities = [make_run(1, "2026-01-05", 5000, 1500)]  # only one run total
    conn = seeded_conn(tmp_path, activities)
    upsert_cycle_entry(conn, "2026-01-01", 28, source="manual")
    conn.commit()

    from run_coach.storage.db import all_activities, all_cycle_entries

    result = cycle_phase_patterns(all_activities(conn), all_cycle_entries(conn))
    assert result["available"] is True
    # the single run's phase bucket has n=1, below MIN_SAMPLE_SIZE
    matched_phase = next(p for p in result["phases"].values() if p["n"] == 1)
    assert matched_phase["reason"] == "not enough data yet"
    conn.close()


def test_cycle_phase_patterns_without_any_cycle_entries():
    result = cycle_phase_patterns([], [])
    assert result["available"] is False
