from datetime import date, timedelta

from run_coach.demo.generator import (
    GAP_LENGTH_DAYS,
    GAP_START_DAYS_AGO,
    generate_demo_data,
)
from run_coach.storage.db import all_activities, connect, init_db


def test_demo_data_tags_exactly_one_race(tmp_path):
    db_path = tmp_path / "demo.db"
    init_db(db_path)
    conn = connect(db_path)
    generate_demo_data(conn)
    conn.commit()

    activities = all_activities(conn)
    races = [a for a in activities if a["is_race"]]
    assert len(races) == 1
    conn.close()


def test_demo_data_has_a_multi_week_gap_with_no_runs(tmp_path):
    db_path = tmp_path / "demo.db"
    init_db(db_path)
    conn = connect(db_path)
    generate_demo_data(conn)
    conn.commit()

    activities = all_activities(conn)
    run_dates = {a["local_date"] for a in activities}
    gap_start = date.today() - timedelta(days=GAP_START_DAYS_AGO)
    gap_dates = {(gap_start + timedelta(days=i)).isoformat() for i in range(1, GAP_LENGTH_DAYS)}
    # The gap excludes its exact boundary days to tolerate off-by-one, but the
    # interior must be run-free.
    assert run_dates.isdisjoint(gap_dates)
    conn.close()


def test_demo_data_spans_roughly_a_year(tmp_path):
    db_path = tmp_path / "demo.db"
    init_db(db_path)
    conn = connect(db_path)
    generate_demo_data(conn)
    conn.commit()

    activities = all_activities(conn)
    dates = sorted(a["local_date"] for a in activities)
    span_days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
    assert span_days > 300
    conn.close()
