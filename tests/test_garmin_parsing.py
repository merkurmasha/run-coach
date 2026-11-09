from datetime import date

from run_coach.garmin.client import (
    chunk_date_range,
    dig,
    normalize_list,
    parse_activity,
    parse_hr_zone_minutes,
)


def test_chunk_date_range_splits_long_spans():
    chunks = chunk_date_range(date(2026, 1, 1), date(2026, 3, 1), chunk_days=30)
    assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 30))
    assert chunks[-1][1] == date(2026, 3, 1)
    # every day covered exactly once, no gaps or overlaps
    covered = []
    for start, end in chunks:
        covered.append((start, end))
        assert start <= end
    for (s1, e1), (s2, _e2) in zip(covered, covered[1:]):
        assert (s2 - e1).days == 1


def test_chunk_date_range_single_day():
    assert chunk_date_range(date(2026, 1, 1), date(2026, 1, 1)) == [(date(2026, 1, 1), date(2026, 1, 1))]


def test_chunk_date_range_empty_when_inverted():
    assert chunk_date_range(date(2026, 2, 1), date(2026, 1, 1)) == []


def test_dig_tries_candidates_in_order():
    data = {"dailySleepDTO": {"sleepTimeSeconds": 25200}}
    assert dig(data, "sleepTimeSeconds", "dailySleepDTO.sleepTimeSeconds") == 25200
    assert dig(data, "nonexistent", default="fallback") == "fallback"


def test_dig_over_list_returns_first_match():
    data = [{"a": 1}, {"b": 2}]
    assert dig(data, "b") == 2
    assert dig(data, "missing", default=None) is None


def test_normalize_list_unwraps_known_keys():
    assert normalize_list({"hrvSummaries": [{"x": 1}]}, "hrvSummaries") == [{"x": 1}]
    assert normalize_list([{"x": 1}]) == [{"x": 1}]
    assert normalize_list(None) == []
    assert normalize_list({"x": 1}) == [{"x": 1}]  # unknown shape: treat dict as one record


def test_parse_activity_happy_path():
    gaps: list[str] = []
    raw = {
        "activityId": 987,
        "startTimeGMT": "2026-06-01 06:00:00",
        "startTimeLocal": "2026-06-01 09:00:00",
        "activityType": {"typeKey": "running"},
        "distance": 5000.0,
        "movingDuration": 1500.0,
        "elapsedDuration": 1550.0,
        "averageHR": 150,
        "maxHR": 172,
        "elevationGain": 30.0,
        "calories": 410,
    }
    parsed = parse_activity(raw, gaps)
    assert gaps == []
    assert parsed.external_id == "987"
    assert parsed.start_time_utc == "2026-06-01T06:00:00Z"
    assert parsed.local_date == "2026-06-01"
    assert parsed.activity_type == "running"
    assert parsed.distance_m == 5000.0
    assert parsed.avg_hr == 150.0


def test_parse_activity_missing_id_is_skipped_not_raised():
    gaps: list[str] = []
    parsed = parse_activity({"distance": 1000}, gaps)
    assert parsed is None
    assert any("activityId" in gap for gap in gaps)


def test_parse_activity_missing_gmt_falls_back_to_local_and_logs_gap():
    gaps: list[str] = []
    raw = {"activityId": 1, "startTimeLocal": "2026-06-01 09:00:00", "distance": 1000}
    parsed = parse_activity(raw, gaps)
    assert parsed is not None
    assert parsed.start_time_utc == "2026-06-01T09:00:00Z"
    assert any("approximation" in gap for gap in gaps)


def test_parse_hr_zone_minutes_flat_fields():
    raw = {"hrTimeInZone_1": 600, "hrTimeInZone_2": 300, "hrTimeInZone_3": 120}
    zones = parse_hr_zone_minutes(raw)
    assert zones == {1: 10.0, 2: 5.0, 3: 2.0}


def test_parse_hr_zone_minutes_missing_returns_none():
    assert parse_hr_zone_minutes({"distance": 100}) is None
