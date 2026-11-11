
from run_coach.storage.db import (
    Activity,
    all_activities,
    all_daily_metrics,
    append_sync_log,
    connect,
    get_setting,
    init_db,
    latest_data_gaps,
    set_activity_race,
    set_setting,
    upsert_activity,
    upsert_daily_metric,
)


def test_init_db_creates_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"activities", "daily_metrics", "settings", "sync_log", "cycle_entries"} <= tables
    conn.close()


def test_upsert_activity_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    activity = Activity(
        source="garmin",
        external_id="123",
        start_time_utc="2026-01-01T06:00:00Z",
        local_date="2026-01-01",
        activity_type="running",
        distance_m=5000.0,
        moving_time_s=1500.0,
        elapsed_time_s=1550.0,
        avg_hr=150.0,
        max_hr=170.0,
        avg_pace_s_per_km=300.0,
        elevation_gain_m=20.0,
        calories=400.0,
    )
    upsert_activity(conn, activity)
    upsert_activity(conn, activity)  # re-sync should not duplicate
    conn.commit()

    rows = all_activities(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == "garmin:123"
    assert rows[0]["distance_m"] == 5000.0
    conn.close()


def test_daily_metric_merges_fields_without_clobbering(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    upsert_daily_metric(conn, "2026-01-01", sleep_duration_s=25000.0)
    upsert_daily_metric(conn, "2026-01-01", hrv_ms=55.0)
    conn.commit()

    rows = all_daily_metrics(conn)
    assert len(rows) == 1
    assert rows[0]["sleep_duration_s"] == 25000.0
    assert rows[0]["hrv_ms"] == 55.0
    conn.close()


def test_settings_roundtrip(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    set_setting(conn, "runs_per_week", 4)
    set_setting(conn, "follows_watch_plan", True)
    conn.commit()

    assert get_setting(conn, "runs_per_week") == 4
    assert get_setting(conn, "follows_watch_plan") is True
    assert get_setting(conn, "missing_key", default="fallback") == "fallback"
    conn.close()


def test_activity_defaults_to_not_a_race_and_can_be_tagged(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    activity = Activity(
        source="garmin", external_id="1", start_time_utc="2026-01-01T06:00:00Z", local_date="2026-01-01",
        activity_type="running", distance_m=5000.0, moving_time_s=1500.0, elapsed_time_s=1550.0,
        avg_hr=150.0, max_hr=170.0, avg_pace_s_per_km=300.0, elevation_gain_m=20.0, calories=400.0,
    )
    upsert_activity(conn, activity)
    conn.commit()
    assert all_activities(conn)[0]["is_race"] == 0

    assert set_activity_race(conn, "garmin:1", True) is True
    conn.commit()
    assert all_activities(conn)[0]["is_race"] == 1

    assert set_activity_race(conn, "garmin:does-not-exist", True) is False


def test_resyncing_an_activity_does_not_clear_its_race_tag(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    activity = Activity(
        source="garmin", external_id="1", start_time_utc="2026-01-01T06:00:00Z", local_date="2026-01-01",
        activity_type="running", distance_m=5000.0, moving_time_s=1500.0, elapsed_time_s=1550.0,
        avg_hr=150.0, max_hr=170.0, avg_pace_s_per_km=300.0, elevation_gain_m=20.0, calories=400.0,
    )
    upsert_activity(conn, activity)
    set_activity_race(conn, "garmin:1", True)
    conn.commit()

    upsert_activity(conn, activity)  # a re-sync, e.g. re-running `sync`
    conn.commit()
    assert all_activities(conn)[0]["is_race"] == 1


def test_sync_log_dedups_gaps_across_runs(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    append_sync_log(conn, "garmin", "2026-01-01", "2026-01-07", {"activities": 2}, ["hrv: missing"])
    append_sync_log(conn, "garmin", "2026-01-08", "2026-01-14", {"activities": 1}, ["hrv: missing", "sleep: missing"])
    conn.commit()

    gaps = latest_data_gaps(conn)
    assert gaps == ["hrv: missing", "sleep: missing"]
    conn.close()
