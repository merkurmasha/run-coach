"""generate_and_cache() must never leave the recommendations section
empty: no Claude key, or a failing Claude call, both fall back to the
rule-based recommendations instead of raising or caching nothing.
"""

from run_coach.config import Secrets
from run_coach.recommendations import generate
from run_coach.storage.db import Activity, connect, init_db, upsert_activity


def _seeded_conn(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)
    upsert_activity(
        conn,
        Activity(
            source="garmin", external_id="1", start_time_utc="2026-02-01T06:00:00Z", local_date="2026-02-01",
            activity_type="running", distance_m=5000.0, moving_time_s=1500.0, elapsed_time_s=1550.0,
            avg_hr=150.0, max_hr=165.0, avg_pace_s_per_km=300.0, elevation_gain_m=10.0, calories=300.0,
        ),
    )
    conn.commit()
    return conn


def test_falls_back_to_rule_based_without_a_claude_key(tmp_path):
    conn = _seeded_conn(tmp_path)
    secrets = Secrets(
        garmin_api_key=None, anthropic_api_key=None, claude_model="claude-sonnet-5-5",
        telegram_bot_token=None, telegram_chat_id=None,
    )
    result = generate.generate_and_cache(conn, secrets)
    assert len(result["recommendations"]) >= 1
    assert "rule-based" in result["recommendations"][0]["text"]
    conn.close()


def test_falls_back_to_rule_based_when_claude_call_raises(tmp_path, monkeypatch):
    conn = _seeded_conn(tmp_path)
    secrets = Secrets(
        garmin_api_key=None, anthropic_api_key="fake", claude_model="claude-sonnet-5-5",
        telegram_bot_token=None, telegram_chat_id=None,
    )

    def boom(stats, api_key, model):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(generate, "generate_recommendations", boom)
    result = generate.generate_and_cache(conn, secrets)
    assert len(result["recommendations"]) >= 1
    assert "rule-based" in result["recommendations"][0]["text"]
    conn.close()


def test_uses_claude_output_when_the_call_succeeds(tmp_path, monkeypatch):
    conn = _seeded_conn(tmp_path)
    secrets = Secrets(
        garmin_api_key=None, anthropic_api_key="fake", claude_model="claude-sonnet-5-5",
        telegram_bot_token=None, telegram_chat_id=None,
    )

    def fake_generate(stats, api_key, model):
        return [{"text": "test rec", "evidence": "strong", "rationale": "test"}]

    monkeypatch.setattr(generate, "generate_recommendations", fake_generate)
    result = generate.generate_and_cache(conn, secrets)
    assert result["recommendations"] == [{"text": "test rec", "evidence": "strong", "rationale": "test"}]
    conn.close()
