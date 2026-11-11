from datetime import datetime
from pathlib import Path

from run_coach.strava.importer import inspect_header, parse_strava_csv

FIXTURE = Path(__file__).parent / "fixtures" / "strava_activities.csv"
FIXTURE_ES = Path(__file__).parent / "fixtures" / "strava_activities_es.csv"


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


def test_inspect_header_reports_missing_required_fields(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar\n1,2\n")
    info = inspect_header(bad)
    assert info["available_headers"] == ["Foo", "Bar"]
    assert set(info["missing_required_fields"]) == {"id", "date", "type"}


def test_inspect_header_matches_known_columns():
    info = inspect_header(FIXTURE)
    assert info["missing_required_fields"] == []
    assert info["matched_fields"]["id"] == "Activity ID"


def test_column_overrides_recover_an_unmatched_header(tmp_path):
    custom = tmp_path / "custom.csv"
    custom.write_text("MyId,MyDate,MyType,Distance\n1,\"Jan 5, 2026, 6:00:00 AM\",Run,5000\n")
    info = inspect_header(custom)
    assert set(info["missing_required_fields"]) == {"id", "date", "type"}

    activities, gaps = parse_strava_csv(
        custom, column_overrides={"id": "MyId", "date": "MyDate", "type": "MyType"}
    )
    assert len(activities) == 1
    assert activities[0].external_id == "1"
    assert not any("could not find columns" in g for g in gaps)


def test_spanish_headers_are_recognized(tmp_path):
    spanish = tmp_path / "spanish.csv"
    spanish.write_text(
        "ID de la actividad,Fecha de la actividad,Tipo de actividad,Distancia\n"
        "2001,\"Jan 5, 2026, 6:00:00 AM\",Run,5000\n"
    )
    activities, gaps = parse_strava_csv(spanish)
    assert len(activities) == 1
    assert activities[0].external_id == "2001"
    assert not any("could not find columns" in g for g in gaps)


def test_russian_headers_are_recognized(tmp_path):
    russian = tmp_path / "russian.csv"
    russian.write_text(
        "ID активности,Дата активности,Тип активности,Дистанция\n"
        "3001,\"Jan 5, 2026, 6:00:00 AM\",Run,5000\n",
        encoding="utf-8",
    )
    activities, _gaps = parse_strava_csv(russian)
    assert len(activities) == 1
    assert activities[0].external_id == "3001"


def test_comma_decimal_distance_is_parsed(tmp_path):
    euro = tmp_path / "euro.csv"
    euro.write_text(
        "Activity ID,Activity Date,Activity Type,Distance\n"
        "4001,\"Jan 5, 2026, 6:00:00 AM\",Run,\"5000,5\"\n"
    )
    activities, _gaps = parse_strava_csv(euro)
    assert activities[0].distance_m == 5000.5


def test_hh_mm_ss_duration_is_parsed(tmp_path):
    timed = tmp_path / "timed.csv"
    timed.write_text(
        "Activity ID,Activity Date,Activity Type,Distance,Moving Time\n"
        "5001,\"Jan 5, 2026, 6:00:00 AM\",Run,5000,\"0:30:00\"\n"
    )
    activities, _gaps = parse_strava_csv(timed)
    assert activities[0].moving_time_s == 1800.0


def test_distance_in_km_is_auto_converted_to_meters(tmp_path):
    km = tmp_path / "km.csv"
    # 5 km in 30 minutes is a plausible run; 5 (treated as meters) would not be.
    km.write_text(
        "Activity ID,Activity Date,Activity Type,Distance,Moving Time\n"
        "6001,\"Jan 5, 2026, 6:00:00 AM\",Run,5,1800\n"
    )
    activities, gaps = parse_strava_csv(km)
    assert activities[0].distance_m == 5000.0
    assert any("looks like it's in km" in g for g in gaps)


def test_spanish_date_formats_are_parsed(tmp_path):
    spanish = tmp_path / "spanish_dates.csv"
    spanish.write_text(
        "Activity ID,Activity Date,Activity Type,Distance\n"
        '1,"2 nov 2026, 12:22:18",Run,5000\n'
        '2,"29 sept 2026, 18:36:54",Run,5000\n'
        '3,"3 sep. 2026, 08:05:00",Run,5000\n'
        '4,"4 dic 2026, 09:00:00",Run,5000\n'
        '5,"5 ago. 2026, 07:00:00",Run,5000\n'
        '6,"6 ENE 2026, 06:00:00",Run,5000\n',
        encoding="utf-8",
    )
    activities, gaps = parse_strava_csv(spanish)
    assert not any("unrecognized date" in g for g in gaps)
    by_id = {a.external_id: a.start_time_local for a in activities}
    assert len(by_id) == 6
    assert by_id["1"] == datetime(2026, 11, 2, 12, 22, 18)
    assert by_id["2"] == datetime(2026, 9, 29, 18, 36, 54)
    assert by_id["3"] == datetime(2026, 9, 3, 8, 5, 0)
    assert by_id["4"] == datetime(2026, 12, 4, 9, 0, 0)
    assert by_id["5"] == datetime(2026, 8, 5, 7, 0, 0)
    assert by_id["6"] == datetime(2026, 1, 6, 6, 0, 0)


def test_russian_date_format_is_parsed(tmp_path):
    russian = tmp_path / "russian_dates.csv"
    russian.write_text(
        "Activity ID,Activity Date,Activity Type,Distance\n"
        '1,"2 нояб 2026, 10:00:00",Run,5000\n',
        encoding="utf-8",
    )
    activities, gaps = parse_strava_csv(russian)
    assert not any("unrecognized date" in g for g in gaps)
    assert activities[0].start_time_local == datetime(2026, 11, 2, 10, 0, 0)


def test_english_am_pm_date_format_still_parses(tmp_path):
    english = tmp_path / "english_dates.csv"
    english.write_text(
        "Activity ID,Activity Date,Activity Type,Distance\n"
        '1,"Dec 23, 2023, 7:15:32 PM",Run,5000\n',
        encoding="utf-8",
    )
    activities, _gaps = parse_strava_csv(english)
    assert activities[0].start_time_local == datetime(2023, 12, 23, 19, 15, 32)


def test_unparseable_dates_report_the_unique_format_once(tmp_path):
    bad = tmp_path / "bad_dates.csv"
    rows = "\n".join(f'{i},"not-a-date-{i}",Run,5000' for i in range(1, 6))
    bad.write_text("Activity ID,Activity Date,Activity Type,Distance\n" + rows + "\n")
    activities, gaps = parse_strava_csv(bad)
    assert activities == []
    date_gaps = [g for g in gaps if "unrecognized date format" in g]
    assert len(date_gaps) == 1
    assert "5 row(s)" in date_gaps[0]


def test_spanish_export_is_imported_with_translated_types(tmp_path):
    activities, gaps = parse_strava_csv(FIXTURE_ES)

    assert len(activities) == 3
    by_id = {a.external_id: a for a in activities}

    run = by_id["9001"]
    assert run.activity_type == "Run"
    assert run.start_time_local == datetime(2026, 11, 2, 12, 22, 18)
    assert run.distance_m == 4501.2
    assert run.moving_time_s == 1855.0
    assert run.avg_hr == 130.0
    assert run.max_hr == 150.0
    assert run.elevation_gain_m == 20.0
    assert run.calories == 300.0

    hike = by_id["9002"]
    assert hike.activity_type == "Hike"
    assert hike.distance_m == 6003.0

    yoga = by_id["9003"]
    assert yoga.activity_type == "Yoga"

    assert any("Descripción de la actividad" in g for g in gaps)
    assert any("Nota privada de actividad" in g for g in gaps)
    for activity in activities:
        for field_name in vars(activity):
            assert "note" not in field_name.lower()
            assert "description" not in field_name.lower()


def test_spanish_header_accent_and_wording_variants_are_matched():
    info = inspect_header(FIXTURE_ES)
    assert info["missing_required_fields"] == []
    assert info["matched_fields"]["id"] == "ID de actividad"
    assert info["matched_fields"]["avg_hr"] == "Frecuencia cardiaca promedio"
    assert info["matched_fields"]["max_hr"] == "Frecuencia cardiaca máxima"
