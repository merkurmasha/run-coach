from datetime import date

from run_coach.metrics.standing import (
    consistency,
    gap_to_target_pace,
    status_line,
    weekly_volume_vs_average,
    weeks_until_race,
)
from run_coach.storage.db import Activity, connect, init_db, upsert_activity


def make_run(i, local_date, distance_m, moving_time_s):
    return Activity(
        source="garmin", external_id=str(i), start_time_utc=f"{local_date}T06:00:00Z", local_date=local_date,
        activity_type="running", distance_m=distance_m, moving_time_s=moving_time_s, elapsed_time_s=moving_time_s + 20,
        avg_hr=150.0, max_hr=165.0, avg_pace_s_per_km=moving_time_s / (distance_m / 1000.0),
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


def test_gap_to_target_pace_is_none_without_a_goal(tmp_path):
    conn = seeded_conn(tmp_path, [make_run(1, "2026-02-01", 5000, 1500)])
    assert gap_to_target_pace(rows(conn), None) is None
    conn.close()


def test_gap_to_target_pace_reports_positive_gap_when_slower_than_target(tmp_path):
    conn = seeded_conn(tmp_path, [make_run(1, "2026-02-05", 5000, 1600)])  # 320 s/km
    result = gap_to_target_pace(rows(conn), target_pace_s_per_km=300.0, as_of=date(2026, 2, 8))
    assert result["avg_pace_s_per_km_last_4w"] == 320.0
    assert result["gap_s_per_km"] == 20.0
    conn.close()


def test_weeks_until_race_counts_whole_weeks():
    assert weeks_until_race("2026-04-01", as_of=date(2026, 3, 11)) == 3


def test_weeks_until_race_is_none_without_a_race_date():
    assert weeks_until_race(None) is None


def test_weekly_volume_flags_a_spike(tmp_path):
    # Four quiet weeks (10km each) then one much bigger week.
    activities = [make_run(1, "2026-01-05", 10000, 3000), make_run(2, "2026-01-12", 10000, 3000)]
    activities += [make_run(3, "2026-02-03", 20000, 6000)]  # this week: 20km vs ~5km/wk 4w avg
    conn = seeded_conn(tmp_path, activities)
    result = weekly_volume_vs_average(rows(conn), as_of=date(2026, 2, 3))
    assert result["this_week_km"] == 20.0
    assert result["is_spike"] is True
    conn.close()


def test_consistency_counts_weeks_with_no_runs(tmp_path):
    activities = [make_run(1, "2026-01-05", 5000, 1500), make_run(2, "2026-01-19", 5000, 1500)]
    conn = seeded_conn(tmp_path, activities)
    result = consistency(rows(conn), as_of=date(2026, 2, 1), weeks=4)
    assert result["weeks_with_no_runs"] >= 1
    conn.close()


def test_consistency_weeks_with_no_runs_is_never_negative(tmp_path):
    # A dense run of activities across many real calendar weeks, to catch
    # the ISO-week/calendar-day boundary mismatch that once went negative.
    activities = [make_run(i, f"2026-01-{(i % 28) + 1:02d}", 5000, 1500) for i in range(1, 40)]
    conn = seeded_conn(tmp_path, activities)
    for weeks in (4, 8, 12):
        result = consistency(rows(conn), as_of=date(2026, 3, 1), weeks=weeks)
        assert result["weeks_with_no_runs"] >= 0
        assert result["weeks_with_at_least_one_run"] + result["weeks_with_no_runs"] == weeks
    conn.close()


def test_status_line_is_no_goal_set_without_goals(tmp_path):
    conn = seeded_conn(tmp_path, [make_run(1, "2026-02-01", 5000, 1500)])
    result = status_line(rows(conn), settings={})
    assert result["status"] == "no_goal_set"
    assert "rule" in result
    conn.close()


def test_status_line_behind_when_under_goal(tmp_path):
    conn = seeded_conn(tmp_path, [make_run(1, "2026-02-01", 5000, 1500)])  # 1 run in the window
    result = status_line(rows(conn), settings={"runs_per_week": 5}, as_of=date(2026, 2, 8))
    assert result["status"] == "behind"
    conn.close()
