from datetime import date, timedelta

from run_coach.metrics.ranges import (
    filter_by_bounds,
    previous_period_bounds,
    range_bounds,
)


def _row(local_date):
    return {"local_date": local_date}


def test_range_bounds_7d():
    start, end = range_bounds("7d", as_of=date(2026, 3, 10))
    assert start == date(2026, 3, 4)
    assert end == date(2026, 3, 10)


def test_range_bounds_all_has_no_start():
    start, end = range_bounds("all", as_of=date(2026, 3, 10))
    assert start is None
    assert end == date(2026, 3, 10)


def test_previous_period_is_equal_length_and_immediately_before():
    start, end = range_bounds("4w", as_of=date(2026, 3, 10))
    prev_start, prev_end = previous_period_bounds("4w", as_of=date(2026, 3, 10))
    assert (end - start).days == (prev_end - prev_start).days
    assert prev_end == start - timedelta(days=1)


def test_previous_period_is_none_for_all():
    assert previous_period_bounds("all", as_of=date(2026, 3, 10)) is None


def test_filter_by_bounds_includes_endpoints():
    rows = [_row("2026-03-01"), _row("2026-03-05"), _row("2026-03-10")]
    result = filter_by_bounds(rows, date(2026, 3, 1), date(2026, 3, 5))
    assert [r["local_date"] for r in result] == ["2026-03-01", "2026-03-05"]


def test_filter_by_bounds_with_no_start_includes_everything_up_to_end():
    rows = [_row("2020-01-01"), _row("2026-03-10")]
    result = filter_by_bounds(rows, None, date(2026, 3, 10))
    assert len(result) == 2
