from pathlib import Path

from run_coach.storage.db import Activity, all_activities, connect, init_db, upsert_activity
from run_coach.strava.sync import import_strava_csv

FIXTURE = Path(__file__).parent / "fixtures" / "strava_activities.csv"


def test_strava_activity_matching_existing_garmin_is_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    # A Garmin activity already covers the first CSV row's start time (UTC).
    upsert_activity(
        conn,
        Activity(
            source="garmin",
            external_id="g1",
            start_time_utc="2026-01-05T06:00:00Z",
            local_date="2026-01-05",
            activity_type="running",
            distance_m=5000.0,
            moving_time_s=1795.0,
            elapsed_time_s=1845.0,
            avg_hr=151.0,
            max_hr=169.0,
            avg_pace_s_per_km=359.0,
            elevation_gain_m=44.0,
            calories=405.0,
        ),
    )
    conn.commit()

    result = import_strava_csv(conn, FIXTURE, timezone_name="UTC")
    conn.commit()

    rows = all_activities(conn)
    garmin_rows = [r for r in rows if r["source"] == "garmin"]
    strava_rows = [r for r in rows if r["source"] == "strava"]

    assert len(garmin_rows) == 1
    # Row 1 (1001) deduped against Garmin; rows 1002 and 1003 are new.
    assert len(strava_rows) == 2
    assert result["counts"]["skipped_duplicate_of_garmin"] == 1
    assert result["counts"]["imported"] == 2
    conn.close()


def test_strava_import_without_garmin_overlap_keeps_everything(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    result = import_strava_csv(conn, FIXTURE, timezone_name="UTC")
    conn.commit()

    rows = all_activities(conn)
    assert len(rows) == 3
    assert result["counts"]["imported"] == 3
    assert result["counts"]["skipped_duplicate_of_garmin"] == 0
    conn.close()


def test_strava_import_is_idempotent_on_rerun(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    import_strava_csv(conn, FIXTURE, timezone_name="UTC")
    import_strava_csv(conn, FIXTURE, timezone_name="UTC")
    conn.commit()

    rows = all_activities(conn)
    assert len(rows) == 3
    conn.close()
