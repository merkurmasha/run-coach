from datetime import date

from run_coach.metrics.common import MIN_SAMPLE_SIZE
from run_coach.metrics.efficiency import _weeks_between, pace_at_hr_trend
from run_coach.storage.db import Activity, connect, init_db, upsert_activity


def make_run(i, local_date, distance_m, moving_time_s, avg_hr):
    return Activity(
        source="garmin", external_id=str(i), start_time_utc=f"{local_date}T06:00:00Z", local_date=local_date,
        activity_type="running", distance_m=distance_m, moving_time_s=moving_time_s, elapsed_time_s=moving_time_s + 20,
        avg_hr=avg_hr, max_hr=avg_hr + 15, avg_pace_s_per_km=moving_time_s / (distance_m / 1000.0),
        elevation_gain_m=10.0, calories=300.0,
    )


def seeded_conn(tmp_path, activities):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    for a in activities:
        upsert_activity(conn, a)
    conn.commit()
    return conn


def rows(conn):
    return conn.execute("SELECT * FROM activities ORDER BY start_time_utc").fetchall()


def test_weeks_between_same_week_is_zero():
    assert _weeks_between("2026-W05", "2026-W05") == 0


def test_weeks_between_across_year_boundary():
    assert _weeks_between("2025-W52", "2026-W02") == 2


def test_pace_at_hr_trend_reports_not_enough_data_below_min_sample(tmp_path):
    activities = [make_run(i, f"2026-01-{i:02d}", 5000, 1500 + i * 5, 140 + i) for i in range(1, MIN_SAMPLE_SIZE)]
    conn = seeded_conn(tmp_path, activities)
    trend = pace_at_hr_trend(rows(conn), "1y", as_of=date(2026, 1, MIN_SAMPLE_SIZE))
    assert trend[-1]["pace_at_reference_hr_s_per_km"] is None
    assert trend[-1]["reason"] == "not enough data yet"
    conn.close()


def test_pace_at_hr_trend_fits_with_enough_runs_in_rolling_window(tmp_path):
    activities = [
        make_run(i, f"2026-01-{i:02d}", 5000, 1400 + i * 10, 140 + i)
        for i in range(1, MIN_SAMPLE_SIZE + 2)
    ]
    conn = seeded_conn(tmp_path, activities)
    trend = pace_at_hr_trend(rows(conn), "1y", as_of=date(2026, 1, MIN_SAMPLE_SIZE + 1))
    assert trend[-1]["pace_at_reference_hr_s_per_km"] is not None
    conn.close()


def test_pace_at_hr_trend_empty_without_qualifying_runs(tmp_path):
    conn = seeded_conn(tmp_path, [])
    assert pace_at_hr_trend(rows(conn), "4w") == []
    conn.close()
