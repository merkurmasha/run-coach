from pathlib import Path

from run_coach.strava.importer import parse_strava_csv

FIXTURE = Path(__file__).parent / "fixtures" / "strava_activities.csv"


def test_parses_known_columns_and_skips_excluded_ones():
    activities, gaps = parse_strava_csv(FIXTURE)

    assert len(activities) == 3
    run = activities[0]
    assert run.external_id == "1001"
    assert run.activity_type == "Run"
    assert run.distance_m == 5000.0
    assert run.moving_time_s == 1800.0
    assert run.avg_hr == 152.0
    assert run.elevation_gain_m == 45.0

    assert any("description/note" in gap for gap in gaps)


def test_never_exposes_description_or_private_note_fields():
    activities, _gaps = parse_strava_csv(FIXTURE)
    for activity in activities:
        for field_name in vars(activity):
            assert "note" not in field_name.lower()
            assert "description" not in field_name.lower()


def test_handles_missing_numeric_fields_without_crashing():
    activities, _gaps = parse_strava_csv(FIXTURE)
    workout = next(a for a in activities if a.activity_type == "Workout")
    assert workout.distance_m is None
    assert workout.avg_hr is None


def test_missing_header_row_reports_gap_and_imports_nothing(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    activities, gaps = parse_strava_csv(empty)
    assert activities == []
    assert gaps and "no header row" in gaps[0]


def test_missing_required_columns_reports_gap(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar\n1,2\n")
    activities, gaps = parse_strava_csv(bad)
    assert activities == []
    assert any("could not find columns" in gap for gap in gaps)
