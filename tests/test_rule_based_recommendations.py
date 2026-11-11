from run_coach.recommendations.rule_based import generate_rule_based_recommendations
from run_coach.recommendations.validator import contains_jargon


def _base_stats(**overrides):
    stats = {
        "n_running_activities": 10,
        "goals": {"runs_per_week": 4},
        "load": {"hr_zone_distribution": {"available": False}},
        "standing": {
            "weekly_volume_vs_average": {"is_spike": False, "this_week_km": 10.0, "avg_4w_km": 9.0, "spike_threshold": 1.3},
            "consistency": {"avg_runs_per_week": 4.0, "window_weeks": 8},
            "recovery": {"resting_hr": {"recent_avg": 50.0, "baseline_avg": 49.0, "delta": 1.0, "n_recent": 7, "n_baseline": 28}},
        },
    }
    stats.update(overrides)
    return stats


def test_flags_a_volume_spike():
    stats = _base_stats()
    stats["standing"]["weekly_volume_vs_average"] = {
        "is_spike": True, "this_week_km": 20.0, "avg_4w_km": 10.0, "spike_threshold": 1.3,
    }
    recs = generate_rule_based_recommendations(stats)
    assert any("20.0" in r["text"] and r["evidence"] == "moderate" for r in recs)


def test_flags_low_consistency_against_goal():
    stats = _base_stats()
    stats["standing"]["consistency"] = {"avg_runs_per_week": 1.0, "window_weeks": 8}
    recs = generate_rule_based_recommendations(stats)
    assert any("1.0" in r["text"] for r in recs)


def test_flags_elevated_resting_hr():
    stats = _base_stats()
    stats["standing"]["recovery"]["resting_hr"] = {
        "recent_avg": 55.0, "baseline_avg": 48.0, "delta": 7.0, "n_recent": 6, "n_baseline": 28,
    }
    recs = generate_rule_based_recommendations(stats)
    assert any("55.0" in r["text"] for r in recs)


def test_flags_low_easy_running_share():
    stats = _base_stats()
    stats["load"]["hr_zone_distribution"] = {"available": True, "n_activities": 10, "zones": {"1": 5.0, "2": 5.0, "3": 90.0}}
    recs = generate_rule_based_recommendations(stats)
    # The plain-voice "text" describes the pattern in everyday words (no "zones 1-2"
    # jargon); the exact zone labels still live in the technical "rationale" field.
    assert any(r["evidence"] == "hypothesis" and "easy" in r["text"].lower() for r in recs)
    assert any("zones 1-2" in r["rationale"] for r in recs)


def test_never_empty_even_with_no_triggers(tmp_path=None):
    stats = _base_stats(n_running_activities=3)
    stats["goals"] = {}
    recs = generate_rule_based_recommendations(stats)
    assert len(recs) >= 1
    assert "3" in recs[0]["text"]


def test_caps_at_five_recommendations():
    stats = _base_stats()
    stats["standing"]["weekly_volume_vs_average"] = {"is_spike": True, "this_week_km": 1, "avg_4w_km": 1, "spike_threshold": 1.3}
    stats["standing"]["consistency"] = {"avg_runs_per_week": 0.5, "window_weeks": 8}
    stats["standing"]["recovery"]["resting_hr"] = {"recent_avg": 60, "baseline_avg": 50, "delta": 10, "n_recent": 7, "n_baseline": 28}
    stats["load"]["hr_zone_distribution"] = {"available": True, "n_activities": 5, "zones": {"1": 0, "2": 0, "3": 100}}
    recs = generate_rule_based_recommendations(stats)
    assert len(recs) <= 5


def test_fallback_recommendations_use_plain_voice():
    # Every trigger at once, so every rule-based "text" gets exercised.
    stats = _base_stats()
    stats["standing"]["weekly_volume_vs_average"] = {"is_spike": True, "this_week_km": 20.0, "avg_4w_km": 10.0, "spike_threshold": 1.3}
    stats["standing"]["consistency"] = {"avg_runs_per_week": 1.0, "window_weeks": 8}
    stats["standing"]["recovery"]["resting_hr"] = {"recent_avg": 55.0, "baseline_avg": 48.0, "delta": 7.0, "n_recent": 6, "n_baseline": 28}
    stats["load"]["hr_zone_distribution"] = {"available": True, "n_activities": 10, "zones": {"1": 5.0, "2": 5.0, "3": 90.0}}
    recs = generate_rule_based_recommendations(stats)

    for rec in recs:
        assert not contains_jargon(rec["text"]), f"jargon leaked into plain text: {rec['text']!r}"
        assert "why_it_matters" in rec and rec["why_it_matters"]
        assert not contains_jargon(rec["why_it_matters"]), f"jargon leaked into why_it_matters: {rec['why_it_matters']!r}"
