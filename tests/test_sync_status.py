"""/api/sync/status reports what actually happened (last sync time, ok or
error) honestly, and a sync that blows up mid-way is persisted as a real
result rather than just a 500 that leaves status with nothing to show.
"""

from __future__ import annotations

import garmin_personal_api
import pytest
from fastapi.testclient import TestClient

from run_coach.config import Secrets
from run_coach.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("run_coach.web.app.DB_PATH", db_path)
    monkeypatch.setattr(
        Secrets,
        "load",
        classmethod(
            lambda cls: Secrets(
                garmin_api_key="garmin-test-key",
                anthropic_api_key=None,
                claude_model="claude-sonnet-5-5",
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
        ),
    )
    app = create_app(demo=False)
    return TestClient(app)


def test_sync_status_reports_never_synced_with_no_history(client):
    resp = client.get("/api/sync/status")
    body = resp.json()
    assert body["garmin"] == {"running": False, "last_synced_at": None, "last_ok": None, "last_error": None, "last_counts": None}
    assert body["strava"]["last_synced_at"] is None


def test_a_failing_sync_is_persisted_and_reported_honestly(client, monkeypatch):
    def raise_auth_error(conn, api_key, days):
        raise garmin_personal_api.HttpError(status_code=401, method="POST", url="https://x/token", response_text="")

    monkeypatch.setattr("run_coach.garmin.sync.sync_garmin", raise_auth_error)

    resp = client.post("/api/sync")
    assert resp.status_code == 502
    assert "GARMIN_API_KEY" in resp.json()["detail"]

    status = client.get("/api/sync/status").json()
    assert status["garmin"]["running"] is False
    assert status["garmin"]["last_ok"] is False
    assert "GARMIN_API_KEY" in status["garmin"]["last_error"]
    assert status["garmin"]["last_synced_at"] is not None


def test_a_successful_sync_is_reported_as_ok(client, monkeypatch):
    def fake_sync(conn, api_key, days):
        return {"counts": {"activities": 3}, "data_gaps": [], "range": {"start": "2026-01-01", "end": "2026-01-07"}}

    monkeypatch.setattr("run_coach.garmin.sync.sync_garmin", fake_sync)

    resp = client.post("/api/sync")
    assert resp.status_code == 200

    status = client.get("/api/sync/status").json()
    assert status["garmin"]["last_ok"] is True
    assert status["garmin"]["last_error"] is None
    assert status["garmin"]["last_counts"] == {"activities": 3}
