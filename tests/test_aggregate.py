from run_coach.metrics.aggregate import build_stats, compute_data_gaps
from run_coach.metrics.efficiency import hr_coverage
from run_coach.storage.db import Activity, all_activities, connect, init_db, upsert_activity


def make_run(source, i, local_date, avg_hr=None):
    return Activity(
        source=source,
        external_id=str(i),
        start_time_utc=f"{local_date}T06:00:00Z",
        local_date=local_date,
        activity_type="Run" if source == "strava" else "running",
        distance_m=5000.0,
        moving_time_s=1800.0,
        elapsed_time_s=1820.0,
        avg_hr=avg_hr,
        max_hr=avg_hr + 15 if avg_hr else None,
        avg_pace_s_per_km=360.0,
        elevation_gain_m=10.0,
        calories=300.0,
    )


def rows_for(tmp_path, *activities):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    for a in activities:
        upsert_activity(conn, a)
    conn.commit()
    return conn, all_activities(conn)


def test_hr_coverage_counts_strava_and_total_separately(tmp_path):
    _conn, rows = rows_for(
        tmp_path,
        make_run("garmin", 1, "2026-01-01", avg_hr=150.0),
        make_run("strava", 2, "2026-01-02", avg_hr=148.0),
        make_run("strava", 3, "2026-01-03", avg_hr=None),
        make_run("strava", 4, "2026-01-04", avg_hr=None),
    )
    coverage = hr_coverage(rows)
    assert coverage == {"total_runs": 4, "runs_with_hr": 2, "strava_total": 3, "strava_with_hr": 1}


def test_hr_coverage_empty_when_no_runs():
    assert hr_coverage([]) == {"total_runs": 0, "runs_with_hr": 0, "strava_total": 0, "strava_with_hr": 0}


def test_data_gaps_always_state_garmin_history_span(tmp_path):
    conn, rows = rows_for(
        tmp_path,
        make_run("garmin", 1, "2026-01-01", avg_hr=150.0),
        make_run("garmin", 2, "2026-01-29", avg_hr=150.0),
    )
    gaps = compute_data_gaps(
        conn,
        activities=rows,
        recovery={},
        coverage=hr_coverage(rows),
        hr_zone_dist={"available": True, "n_activities": 2, "zones": {}},
    )
    assert any("Garmin activity history covers 2026-01-01 to 2026-01-29 (29 days)" in g for g in gaps)


def test_data_gaps_say_so_when_no_garmin_activities_at_all(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    gaps = compute_data_gaps(
        conn, activities=[], recovery={}, coverage=hr_coverage([]), hr_zone_dist={"available": False, "n_activities": 0, "zones": {}}
    )
    assert "no Garmin activities synced yet" in gaps


def test_data_gaps_flag_low_hr_coverage_but_not_when_absent(tmp_path):
    conn, rows = rows_for(
        tmp_path, *(make_run("strava", i, f"2026-01-{i:02d}", avg_hr=150.0 if i == 1 else None) for i in range(1, 6))
    )
    coverage = hr_coverage(rows)
    gaps = compute_data_gaps(conn, rows, recovery={}, coverage=coverage, hr_zone_dist={"available": False, "n_activities": 0, "zones": {}})
    assert any("1 of 5 runs have heart-rate data" in g for g in gaps)
    assert any("no per-zone heart-rate minutes" in g for g in gaps)

    # No runs at all: nothing to say about coverage.
    gaps_empty = compute_data_gaps(conn, [], recovery={}, coverage=hr_coverage([]), hr_zone_dist={"available": False, "n_activities": 0, "zones": {}})
    assert not any("heart-rate data" in g for g in gaps_empty)


def test_data_gaps_flag_stale_recovery_metrics(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    recovery = {
        "sleep_duration_s": {"recent_avg": 25000.0, "n_recent": 7},
        "hrv_ms": {"recent_avg": None, "n_recent": 0},
        "resting_hr": {"recent_avg": None, "n_recent": 0},
        "sleep_score": {"recent_avg": 80.0, "n_recent": 7},
    }
    gaps = compute_data_gaps(conn, [], recovery, hr_coverage([]), {"available": False, "n_activities": 0, "zones": {}})
    assert any("no HRV readings from Garmin in the last 7 days" in g for g in gaps)
    assert any("no resting heart rate readings from Garmin in the last 7 days" in g for g in gaps)
    assert not any("sleep" in g.lower() for g in gaps)


def test_build_stats_data_gaps_never_empty_even_with_no_sync_log(tmp_path):
    """Previously this fell back to "none recorded" whenever a sync hadn't
    logged anything -- now there's always at least the Garmin-history note."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    stats = build_stats(conn)
    assert len(stats["data_gaps"]) > 0
    assert "hr_coverage" in stats
