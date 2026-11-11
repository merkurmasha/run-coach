"""/api/activities (the race-tagging list's data source) and
/api/activities/{id}/race (tag/untag, with an optional race name).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from run_coach.storage.db import Activity, connect, upsert_activity
from run_coach.web.app import create_app


def make_run(i, local_date, distance_m=5000.0, moving_time_s=1500.0):
    return Activity(
        source="garmin",
        external_id=str(i),
        start_time_utc=f"{local_date}T06:00:00Z",
        local_date=local_date,
        activity_type="running",
        distance_m=distance_m,
        moving_time_s=moving_time_s,
        elapsed_time_s=moving_time_s + 20,
        avg_hr=150.0,
        max_hr=165.0,
        avg_pace_s_per_km=moving_time_s / (distance_m / 1000.0),
        elevation_gain_m=10.0,
        calories=300.0,
    )


def seeded_client(tmp_path, monkeypatch, activities):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("run_coach.web.app.DB_PATH", db_path)
    app = create_app(demo=False)
    conn = connect(db_path)
    for a in activities:
        upsert_activity(conn, a)
    conn.commit()
    conn.close()
    return TestClient(app)


def test_list_activities_includes_time_and_race_fields(tmp_path, monkeypatch):
    client = seeded_client(tmp_path, monkeypatch, [make_run(1, "2026-01-05", 5000.0, 1500.0)])
    resp = client.get("/api/activities?range=all")
    assert resp.status_code == 200
    activities = resp.json()["activities"]
    assert len(activities) == 1
    row = activities[0]
    assert row["time_s"] == 1500.0
    assert row["is_race"] is False
    assert row["race_name"] is None


def test_tagging_a_race_with_a_name_round_trips(tmp_path, monkeypatch):
    client = seeded_client(tmp_path, monkeypatch, [make_run(1, "2026-01-05")])
    activity_id = client.get("/api/activities?range=all").json()["activities"][0]["id"]

    resp = client.post(f"/api/activities/{activity_id}/race", json={"is_race": True, "race_name": "City 5K"})
    assert resp.status_code == 200

    row = client.get("/api/activities?range=all").json()["activities"][0]
    assert row["is_race"] is True
    assert row["race_name"] == "City 5K"


def test_untagging_a_race_clears_its_name(tmp_path, monkeypatch):
    client = seeded_client(tmp_path, monkeypatch, [make_run(1, "2026-01-05")])
    activity_id = client.get("/api/activities?range=all").json()["activities"][0]["id"]
    client.post(f"/api/activities/{activity_id}/race", json={"is_race": True, "race_name": "City 5K"})

    client.post(f"/api/activities/{activity_id}/race", json={"is_race": False})
    row = client.get("/api/activities?range=all").json()["activities"][0]
    assert row["is_race"] is False
    assert row["race_name"] is None


def test_tagging_an_unknown_activity_404s(tmp_path, monkeypatch):
    client = seeded_client(tmp_path, monkeypatch, [])
    resp = client.post("/api/activities/garmin:does-not-exist/race", json={"is_race": True})
    assert resp.status_code == 404
