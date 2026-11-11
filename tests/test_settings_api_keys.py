"""The Settings "Save and test" endpoints for the Claude and Garmin keys:
cleans what was pasted, writes it to .env, reloads os.environ in this
process, and makes a real minimal call to confirm it works -- without ever
echoing the key back (only its last 4 characters).

No test here touches the real .env or database: init_db and write_env are
monkeypatched to in-memory stand-ins, and the real network calls
(anthropic.Anthropic / GarminClient) are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import anthropic
import garmin_personal_api
import httpx2
import pytest
from fastapi.testclient import TestClient

from run_coach.web.app import _clean_secret_value, _describe_garmin_error, _mask_key, create_app


def _request():
    return httpx2.Request("POST", "https://example.invalid/")


# ---------- pure helpers ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  sk-ant-abc123  ", "sk-ant-abc123"),
        ('"sk-ant-abc123"', "sk-ant-abc123"),
        ("'sk-ant-abc123'", "sk-ant-abc123"),
        ("", ""),
        (None, ""),
        ("   ", ""),
        ("'", "'"),  # a single stray quote char isn't a matching pair
    ],
)
def test_clean_secret_value(raw, expected):
    assert _clean_secret_value(raw) == expected


def test_mask_key_shows_only_last_four_chars():
    assert _mask_key("sk-ant-abcdefgh1234") == "...1234"


def test_mask_key_handles_short_and_empty_values():
    assert _mask_key("") is None
    assert _mask_key(None) is None
    assert _mask_key("ab") == "..."


def test_describe_garmin_error_recognizes_auth_failure():
    exc = garmin_personal_api.HttpError(status_code=401, method="POST", url="https://x/token", response_text="")
    message = _describe_garmin_error(exc)
    assert "GARMIN_API_KEY" in message


def test_describe_garmin_error_other_http_status():
    exc = garmin_personal_api.HttpError(status_code=500, method="POST", url="https://x/token", response_text="boom")
    message = _describe_garmin_error(exc)
    assert "500" in message
    assert "boom" not in message  # response body isn't echoed


def test_describe_garmin_error_network_failure():
    message = _describe_garmin_error(ConnectionError("no route to host"))
    assert "network" in message.lower() or "reach" in message.lower()


# ---------- endpoints ----------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("run_coach.web.app.init_db", lambda *_a, **_kw: None)
    written: dict[str, str] = {}
    monkeypatch.setattr("run_coach.web.app.write_env", lambda updates: written.update(updates))
    app = create_app(demo=False)
    app.state.written = written
    return TestClient(app)


def test_save_claude_key_rejects_empty_input(client):
    resp = client.post("/api/settings/claude-key", json={"api_key": "   "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "No Claude API key entered" in body["message"]
    assert body["masked_key"] is None
    assert client.app.state.written == {}


def test_save_claude_key_success_never_echoes_the_key(client, monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: fake_client)

    resp = client.post("/api/settings/claude-key", json={"api_key": '  "sk-ant-realkeyvalue1234"  '})
    body = resp.json()

    assert client.app.state.written == {"ANTHROPIC_API_KEY": "sk-ant-realkeyvalue1234"}
    assert body["ok"] is True
    assert body["masked_key"] == "...1234"
    assert "sk-ant-realkeyvalue1234" not in resp.text
    fake_client.messages.create.assert_called_once()


def test_save_claude_key_still_saves_when_the_test_call_fails(client, monkeypatch):
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx2.Response(401, request=_request()), body=None
    )
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: fake_client)

    resp = client.post("/api/settings/claude-key", json={"api_key": "sk-ant-badkey0000"})
    body = resp.json()

    assert client.app.state.written == {"ANTHROPIC_API_KEY": "sk-ant-badkey0000"}
    assert body["ok"] is False
    assert "ANTHROPIC_API_KEY" in body["message"]
    assert "sk-ant-" not in body["message"]
    assert body["masked_key"] == "...0000"


def test_save_garmin_key_rejects_empty_input(client):
    resp = client.post("/api/settings/garmin-key", json={"api_key": ""})
    body = resp.json()
    assert body["ok"] is False
    assert "No Garmin API key entered" in body["message"]
    assert client.app.state.written == {}


def test_save_garmin_key_runs_a_real_token_exchange(client, monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr("run_coach.garmin.client.GarminClient", lambda api_key: fake_client)

    resp = client.post("/api/settings/garmin-key", json={"api_key": "garmin-real-key-5678"})
    body = resp.json()

    assert client.app.state.written == {"GARMIN_API_KEY": "garmin-real-key-5678"}
    assert body["ok"] is True
    assert body["masked_key"] == "...5678"
    assert "garmin-real-key-5678" not in resp.text
    fake_client.close.assert_called_once()


def test_save_garmin_key_reports_auth_failure(client, monkeypatch):
    def raise_auth_error(api_key):
        raise garmin_personal_api.HttpError(status_code=403, method="POST", url="https://x/token", response_text="")

    monkeypatch.setattr("run_coach.garmin.client.GarminClient", raise_auth_error)

    resp = client.post("/api/settings/garmin-key", json={"api_key": "wrong-key"})
    body = resp.json()
    assert body["ok"] is False
    assert "GARMIN_API_KEY" in body["message"]


def test_settings_endpoints_disabled_in_demo_mode():
    # Demo mode regenerates its own disposable data/demo.db (separate from
    # the real database by design), so this is safe to run for real.
    app = create_app(demo=True)
    client = TestClient(app)
    assert client.post("/api/settings/claude-key", json={"api_key": "x"}).status_code == 400
    assert client.post("/api/settings/garmin-key", json={"api_key": "x"}).status_code == 400
