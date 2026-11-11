from run_coach.recommendations.validator import (
    allowed_numbers_from_stats,
    contains_jargon,
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


# ---- plain-voice conversions: the validator must resolve a min:sec pace, an
# "X in Y" fraction, or a rounded number back to the stat it represents,
# rather than rejecting every converted phrasing as an invented number.

PACE_STATS = {
    "progress": {"pace_at_reference_hr_s_per_km": 309.6},
    "load": {"hr_zone_distribution": {"zones": {"4": 74.6, "2": 68.0}}},
    "standing": {"longest_run_km": 21.0975},
}


def test_min_sec_pace_matching_the_underlying_seconds_is_kept():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    text = "Your easy pace was about 5:10/km last month."  # 5:10 = 310s, rounds from 309.6
    assert filter_text_against_numbers(text, allowed) == text


def test_min_sec_pace_not_matching_any_stat_is_dropped():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    text = "Your easy pace was about 6:00/km last month."  # 360s, not present anywhere
    assert filter_text_against_numbers(text, allowed) is None


def test_x_in_y_fraction_matching_a_percentage_stat_is_kept():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    text = "About 3 in 4 of your running minutes were at a hard effort."  # 75%, rounds to the 74.6 stat
    assert filter_text_against_numbers(text, allowed) == text


def test_x_in_y_fraction_not_matching_any_stat_is_dropped():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    text = "About 1 in 2 of your running minutes were at a hard effort."  # 50%, no matching stat
    assert filter_text_against_numbers(text, allowed) is None


def test_word_fraction_within_tolerance_of_a_percentage_stat_is_kept():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    # "three quarters" = 75, within FRACTION_TOLERANCE of the 68.0 zone-2 stat.
    text = "Roughly three quarters of your time was spent at an easy effort."
    assert filter_text_against_numbers(text, allowed) == text


def test_word_fraction_far_from_every_percentage_stat_is_dropped():
    allowed = allowed_numbers_from_stats({"load": {"hr_zone_distribution": {"zones": {"4": 5.0}}}})
    text = "Roughly three quarters of your time was spent at an easy effort."
    assert filter_text_against_numbers(text, allowed) is None


def test_plain_number_matching_a_rounded_stat_is_kept():
    allowed = allowed_numbers_from_stats(PACE_STATS)
    text = "Your longest run was about 21 km."  # rounds from 21.0975
    assert filter_text_against_numbers(text, allowed) == text


# ---- jargon: field names, ISO week codes, and raw "s/km" must never reach
# user-facing text, even when every number in the sentence checks out.


def test_contains_jargon_detects_field_names_week_codes_and_s_per_km():
    assert contains_jargon("Your weeks_until_race is 3.")
    assert contains_jargon("Check back in W42.")
    assert contains_jargon("Your pace was 309.6 s/km.")
    assert not contains_jargon("Your pace was about 5:10 per km, two weeks before your race.")


def test_filter_text_drops_jargon_sentence_only_when_checked():
    allowed = {"3"}
    text = "Your weeks_until_race is 3."
    assert filter_text_against_numbers(text, allowed, check_jargon=True) is None
    # Without the flag (e.g. the technical "rationale" field), jargon is allowed through.
    assert filter_text_against_numbers(text, allowed, check_jargon=False) == text


def test_validate_recommendations_strips_jargon_from_text_and_why_it_matters():
    recs = [
        {
            "text": "Your weeks_until_race is 6.",
            "why_it_matters": "This matters because weeks_until_race=6.",
            "evidence": "moderate",
            "rationale": "weeks_until_race=6 (technical detail, fine here)",
        }
    ]
    stats = {"standing": {"weeks_until_race": 6}}
    cleaned = validate_recommendations(recs, stats)
    # Both user-facing fields had nothing left once the jargon sentence was dropped.
    assert len(cleaned) == 0
