"""Exercises generate_weekly_report with a fake SDK client -- no network call
or real API key needed. Mainly guards against the forced tool_choice bug
(400 on Claude Sonnet 5.5+) regressing: the request must use
output_config.format, never tool_choice.
"""

import json
from types import SimpleNamespace

from run_coach.config import Secrets
from run_coach.report import weekly
from run_coach.storage.db import Activity, connect, init_db, upsert_activity


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessages:
    def __init__(self, response_json):
        self._response_json = response_json
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[FakeTextBlock(json.dumps(self._response_json))])


class FakeAnthropic:
    def __init__(self, response_json, api_key=None):
        self.messages = FakeMessages(response_json)


def _seeded_conn(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    for i, (date, dist) in enumerate(
        [("2026-01-05", 5000.0), ("2026-01-12", 6000.0), ("2026-01-19", 5500.0), ("2026-01-26", 7000.0)]
    ):
        upsert_activity(
            conn,
            Activity(
                source="garmin",
                external_id=str(i),
                start_time_utc=f"{date}T06:00:00Z",
                local_date=date,
                activity_type="running",
                distance_m=dist,
                moving_time_s=dist / 1000.0 * 300,
                elapsed_time_s=dist / 1000.0 * 310,
                avg_hr=150.0,
                max_hr=165.0,
                avg_pace_s_per_km=300.0,
                elevation_gain_m=20.0,
                calories=400.0,
            ),
        )
    conn.commit()
    return conn


def _fake_report():
    return {
        "highlight": "You ran 7.0 km this week.",
        "watch_out": "Nothing concerning this week.",
        "next_week": {
            "objective": "Hold steady volume.",
            "key_results": ["Run 3 times", "Cover 7.0 km total", "Keep pace around 5:00/km"],
            "fallback_sessions": ["Easy 3k", "Rest day", "Short jog"],
        },
    }


def test_generate_weekly_report_uses_structured_output_not_forced_tool_choice(tmp_path, monkeypatch):
    conn = _seeded_conn(tmp_path)
    fake_client = FakeAnthropic(_fake_report())
    monkeypatch.setattr(weekly.anthropic, "Anthropic", lambda api_key: fake_client)

    secrets = Secrets(
        garmin_api_key=None,
        anthropic_api_key="fake",
        claude_model="claude-sonnet-5-5",
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    report = weekly.generate_weekly_report(conn, secrets, weeks=8)

    assert "tool_choice" not in fake_client.messages.last_kwargs
    assert fake_client.messages.last_kwargs["output_config"]["format"]["type"] == "json_schema"
    assert report["highlight"]
    assert len(report["next_week"]["key_results"]) == 3
    conn.close()


def test_generate_weekly_report_requires_claude_key(tmp_path):
    conn = _seeded_conn(tmp_path)
    secrets = Secrets(
        garmin_api_key=None, anthropic_api_key=None, claude_model="claude-sonnet-5-5",
        telegram_bot_token=None, telegram_chat_id=None,
    )
    try:
        weekly.generate_weekly_report(conn, secrets)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    conn.close()
