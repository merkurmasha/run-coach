from run_coach.storage.db import Activity, all_activities, connect, init_db, upsert_activity
from run_coach.strava.sync import import_strava_csv


def test_import_reports_runs_and_other_activities_separately(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    csv_path = tmp_path / "activities.csv"
    csv_path.write_text(
        "Activity ID,Activity Date,Activity Type,Distance,Moving Time\n"
        '1,"Jan 5, 2026, 6:00:00 AM",Run,5000,1800\n'
        '2,"Jan 6, 2026, 6:00:00 AM",Ride,20000,3600\n'
        '3,"Jan 7, 2026, 6:00:00 AM",Yoga,,2700\n',
    )

    result = import_strava_csv(conn, csv_path, timezone_name="UTC")
    conn.commit()

    assert result["counts"]["runs_imported"] == 1
    assert result["counts"]["other_imported"] == 2
    assert result["counts"]["imported"] == 3
    assert len(all_activities(conn)) == 3


def test_import_skips_rows_that_duplicate_a_garmin_activity(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    upsert_activity(
        conn,
        Activity(
            source="garmin",
            external_id="g1",
            start_time_utc="2026-01-05T06:00:00Z",
            local_date="2026-01-05",
            activity_type="running",
            distance_m=5000.0,
            moving_time_s=1800.0,
            elapsed_time_s=1800.0,
            avg_hr=150.0,
            max_hr=165.0,
            avg_pace_s_per_km=360.0,
            elevation_gain_m=10.0,
            calories=300.0,
        ),
    )
    conn.commit()

    csv_path = tmp_path / "activities.csv"
    csv_path.write_text(
        "Activity ID,Activity Date,Activity Type,Distance,Moving Time\n"
        '1,"Jan 5, 2026, 6:00:00 AM",Run,5000,1800\n'
    )

    result = import_strava_csv(conn, csv_path, timezone_name="UTC")
    conn.commit()

    assert result["counts"]["skipped_duplicate_of_garmin"] == 1
    assert result["counts"]["imported"] == 0
    assert len(all_activities(conn)) == 1
