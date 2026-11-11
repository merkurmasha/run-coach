from datetime import date

from run_coach.metrics.progress import (
    pace_trend_series,
    personal_bests_timeline,
    race_markers,
    range_progress,
    weekly_distance_series,
)
from run_coach.storage.db import (
    Activity,
    connect,
    init_db,
    set_activity_race,
    upsert_activity,
)


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


def rows(conn):
    return conn.execute("SELECT * FROM activities ORDER BY start_time_utc").fetchall()


def test_range_progress_computes_delta_against_previous_equal_period(tmp_path):
    activities = [
        make_run(1, "2026-02-01", 5000, 1500),  # previous 7d period
        make_run(2, "2026-02-08", 6000, 1700),  # current 7d period (as_of)
    ]
    conn = seeded_conn(tmp_path, activities)
    result = range_progress(rows(conn), "7d", as_of=date(2026, 2, 8))
    assert result["current"]["distance_km"] == 6.0
    assert result["previous"]["distance_km"] == 5.0
    assert result["delta"]["distance_km"] == 1.0
    conn.close()


def test_range_progress_all_time_has_no_previous_period(tmp_path):
    activities = [make_run(1, "2026-02-01", 5000, 1500)]
    conn = seeded_conn(tmp_path, activities)
    result = range_progress(rows(conn), "all", as_of=date(2026, 2, 8))
    assert result["previous"] is None
    assert result["delta"] is None
    conn.close()


def test_weekly_distance_series_groups_by_iso_week(tmp_path):
    activities = [make_run(1, "2026-02-02", 5000, 1500), make_run(2, "2026-02-03", 5000, 1500)]
    conn = seeded_conn(tmp_path, activities)
    series = weekly_distance_series(rows(conn), "4w", as_of=date(2026, 2, 8))
    assert len(series) == 1
    assert series[0]["distance_km"] == 10.0
    conn.close()


def test_pace_trend_series_includes_a_rolling_average(tmp_path):
    activities = [
        make_run(1, "2026-01-05", 5000, 1600),  # 320 s/km
        make_run(2, "2026-01-12", 5000, 1500),  # 300 s/km
    ]
    conn = seeded_conn(tmp_path, activities)
    series = pace_trend_series(rows(conn), "1y", as_of=date(2026, 1, 12), rolling_window=4)
    assert series[-1]["avg_pace_s_per_km"] == 300.0
    assert series[-1]["rolling_avg_pace_s_per_km"] == 310.0
    conn.close()


def test_personal_bests_timeline_emits_one_event_per_improvement(tmp_path):
    activities = [
        make_run(1, "2026-01-05", 5050, 1300),  # first 5k PB
        make_run(2, "2026-01-12", 5050, 1400),  # slower, not a new PB
        make_run(3, "2026-01-19", 5050, 1200),  # improves the PB
    ]
    conn = seeded_conn(tmp_path, activities)
    events = personal_bests_timeline(rows(conn))
    assert [e["moving_time_s"] for e in events if e["distance_label"] == "5k"] == [1300, 1200]
    conn.close()


def test_race_markers_only_includes_tagged_activities(tmp_path):
    activities = [make_run(1, "2026-01-05", 5000, 1500), make_run(2, "2026-01-12", 10000, 2900)]
    conn = seeded_conn(tmp_path, activities)
    set_activity_race(conn, "garmin:2", True)
    conn.commit()
    markers = race_markers(rows(conn))
    assert len(markers) == 1
    assert markers[0]["distance_km"] == 10.0
    conn.close()
