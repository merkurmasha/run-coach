"""Rule-based recommendations: the fallback when Claude is unavailable (no
key configured, or the API call failed), so the recommendations section is
never empty. Every rule is plain code against the same aggregated stats
dict Claude would have seen -- no model call, no invented numbers, and the
rule each recommendation is based on is named in its own rationale.
"""

from __future__ import annotations

FALLBACK_NOTE = "(rule-based: Claude is unavailable, so this is a code-computed fallback, not an LLM recommendation)"


def generate_rule_based_recommendations(stats: dict) -> list[dict]:
    recs: list[dict] = []

    standing = stats.get("standing") or {}
    volume = standing.get("weekly_volume_vs_average") or {}
    if volume.get("is_spike"):
        recs.append(
            {
                "text": (
                    f"This week's {volume['this_week_km']} km is more than "
                    f"{volume['spike_threshold']}x your trailing 4-week average of {volume['avg_4w_km']} km. "
                    f"{FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "rationale": "Ramp-rate rule of thumb: a week's volume well above the recent average is a common, non-personalized injury-risk flag.",
            }
        )

    consistency = standing.get("consistency") or {}
    runs_goal = stats.get("goals", {}).get("runs_per_week")
    avg_runs = consistency.get("avg_runs_per_week")
    if runs_goal and avg_runs is not None and avg_runs < 0.7 * runs_goal:
        recs.append(
            {
                "text": (
                    f"You've averaged {avg_runs} runs/week over the last {consistency.get('window_weeks')} weeks, "
                    f"below your goal of {runs_goal}. {FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "rationale": "Directly compares your logged run frequency against the runs_per_week goal from setup.",
            }
        )

    recovery = standing.get("recovery") or {}
    resting_hr = recovery.get("resting_hr") or {}
    if resting_hr.get("delta") is not None and resting_hr["delta"] > 3 and resting_hr.get("n_recent", 0) >= 3:
        recs.append(
            {
                "text": (
                    f"Your resting heart rate has averaged {resting_hr['recent_avg']} bpm over the last "
                    f"{resting_hr['n_recent']} days, {resting_hr['delta']} bpm above your own 28-day baseline "
                    f"of {resting_hr['baseline_avg']} bpm. {FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "rationale": "Elevated resting heart rate against your own baseline is a common recovery-strain signal.",
            }
        )

    hr_zones = stats.get("load", {}).get("hr_zone_distribution") or {}
    if hr_zones.get("available"):
        easy_share = hr_zones["zones"].get("1", 0.0) + hr_zones["zones"].get("2", 0.0)
        if easy_share < 20.0:
            recs.append(
                {
                    "text": (
                        f"Only {round(easy_share, 1)}% of your zone-tagged running time is in zones 1-2, "
                        f"across {hr_zones['n_activities']} activities with zone data. {FALLBACK_NOTE}"
                    ),
                    "evidence": "hypothesis",
                    "rationale": "A low share of easy-zone time is a pattern worth noting, not a diagnosis -- zone boundaries are Garmin's own and not personally calibrated here.",
                }
            )

    if not recs:
        n = stats.get("n_running_activities", 0)
        recs.append(
            {
                "text": f"You have {n} running activities on record. {FALLBACK_NOTE}",
                "evidence": "hypothesis",
                "rationale": "No rule-based pattern triggered against your current data; this is a plain status note so the section is never empty.",
            }
        )

    return recs[:5]
