from run_coach.recommendations.validator import (
    allowed_numbers_from_stats,
    filter_text_against_numbers,
    validate_recommendations,
)

STATS = {
    "progress": {"monthly": [{"month": "2026-01", "distance_km": 42.5, "runs": 6}]},
    "recovery": {"hrv_ms": {"n_baseline": 28, "delta": -3.2}},
}


def test_allowed_numbers_includes_nested_values():
    allowed = allowed_numbers_from_stats(STATS)
    assert "42.5" in allowed
    assert "6" in allowed
    assert "28" in allowed
    assert "-3.2" in allowed


def test_filter_text_keeps_sentence_with_valid_numbers():
    allowed = allowed_numbers_from_stats(STATS)
    text = "You ran 42.5 km across 6 runs this month."
    assert filter_text_against_numbers(text, allowed) == text


def test_filter_text_drops_sentence_with_invented_number():
    allowed = allowed_numbers_from_stats(STATS)
    text = "You ran 42.5 km this month. Your VO2max improved by 11 points."
    result = filter_text_against_numbers(text, allowed)
    assert "42.5" in result
    assert "11" not in result


def test_filter_text_returns_none_when_nothing_survives():
    allowed = allowed_numbers_from_stats(STATS)
    text = "Your cadence jumped to 190 steps per minute."
    assert filter_text_against_numbers(text, allowed) is None


def test_validate_recommendations_drops_whole_recommendation_when_all_fails():
    recs = [
        {"text": "Your cadence jumped to 190 steps per minute.", "evidence": "hypothesis", "rationale": "x"},
        {"text": "You ran 42.5 km across 6 runs this month.", "evidence": "strong", "rationale": "y"},
    ]
    cleaned = validate_recommendations(recs, STATS)
    assert len(cleaned) == 1
    assert cleaned[0]["rationale"] == "y"


def test_validate_recommendations_keeps_partial_sentences():
    recs = [
        {
            "text": "You ran 42.5 km across 6 runs this month. Your VO2max improved by 11 points.",
            "evidence": "moderate",
            "rationale": "z",
        }
    ]
    cleaned = validate_recommendations(recs, STATS)
    assert len(cleaned) == 1
    assert "42.5" in cleaned[0]["text"]
    assert "11" not in cleaned[0]["text"]
