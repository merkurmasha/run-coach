"""Rule-based recommendations: the fallback when Claude is unavailable (no
key configured, or the API call failed), so the recommendations section is
never empty. Every rule is plain code against the same aggregated stats
dict Claude would have seen -- no model call, no invented numbers, and the
rule each recommendation is based on is named in its own rationale.

Written in the same plain-coach voice as Claude's own recommendations (see
claude_client.SYSTEM_PROMPT): "text" and "why_it_matters" are short,
jargon-free sentences a non-technical runner can read; "rationale" is the
one field allowed to carry the exact stat and the rule's name, shown only
behind the "Show the numbers" disclosure in the UI.
"""

from __future__ import annotations

FALLBACK_NOTE = "(This is a simple rule-based check, not a Claude-written note.)"


def generate_rule_based_recommendations(stats: dict) -> list[dict]:
    recs: list[dict] = []

    standing = stats.get("standing") or {}
    volume = standing.get("weekly_volume_vs_average") or {}
    if volume.get("is_spike"):
        this_week = volume["this_week_km"]
        avg_4w = volume["avg_4w_km"]
        recs.append(
            {
                "text": (
                    f"This week you've run {this_week} km, well above your usual recent average of about "
                    f"{avg_4w} km a week. A sudden jump like that raises your injury risk, so it's worth taking "
                    f"it a bit easier for the next few days. {FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "why_it_matters": "Ramping volume up too fast, too soon is one of the most common ways runners end up injured.",
                "rationale": (
                    f"Ramp-rate rule of thumb: this_week_km={this_week} is more than {volume['spike_threshold']}x "
                    f"avg_4w_km={avg_4w} -- a common, non-personalized injury-risk flag."
                ),
            }
        )

    consistency = standing.get("consistency") or {}
    runs_goal = stats.get("goals", {}).get("runs_per_week")
    avg_runs = consistency.get("avg_runs_per_week")
    window_weeks = consistency.get("window_weeks")
    if runs_goal and avg_runs is not None and avg_runs < 0.7 * runs_goal:
        recs.append(
            {
                "text": (
                    f"Over the last {window_weeks} weeks you've averaged about {avg_runs} runs a week, but your "
                    f"plan calls for {runs_goal}. Try to fit in one more run this week if you can, even a short one. "
                    f"{FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "why_it_matters": "Showing up consistently, even for shorter runs, matters more for building fitness than any single long run.",
                "rationale": f"avg_runs_per_week={avg_runs} over window_weeks={window_weeks} vs. goals.runs_per_week={runs_goal}.",
            }
        )

    recovery = standing.get("recovery") or {}
    resting_hr = recovery.get("resting_hr") or {}
    if resting_hr.get("delta") is not None and resting_hr["delta"] > 3 and resting_hr.get("n_recent", 0) >= 3:
        recs.append(
            {
                "text": (
                    f"Your resting heart rate has averaged about {resting_hr['recent_avg']} beats per minute over "
                    f"the last {resting_hr['n_recent']} days -- about {resting_hr['delta']} beats higher than your "
                    f"usual baseline of {resting_hr['baseline_avg']}. That can be a sign your body hasn't fully "
                    f"bounced back yet, so an easier day or some extra sleep would help. {FALLBACK_NOTE}"
                ),
                "evidence": "moderate",
                "why_it_matters": "A resting heart rate above your own normal is a common early signal that you need more recovery, not necessarily less training overall.",
                "rationale": (
                    f"resting_hr.recent_avg={resting_hr['recent_avg']} is delta={resting_hr['delta']} bpm above "
                    f"baseline_avg={resting_hr['baseline_avg']} (n_recent={resting_hr['n_recent']})."
                ),
            }
        )

    hr_zones = stats.get("load", {}).get("hr_zone_distribution") or {}
    if hr_zones.get("available"):
        easy_share = round(hr_zones["zones"].get("1", 0.0) + hr_zones["zones"].get("2", 0.0), 1)
        if easy_share < 20.0:
            recs.append(
                {
                    "text": (
                        "Less than a fifth of your recent running time has been at an easy, conversational pace -- "
                        "most of it's been harder effort. Adding more truly easy runs, paced so you could hold a "
                        "conversation, would build your aerobic base without adding extra strain. "
                        f"{FALLBACK_NOTE}"
                    ),
                    "evidence": "hypothesis",
                    "why_it_matters": "This is a pattern worth testing, not a firm diagnosis -- heart-rate zone boundaries are set generically by your watch, not personally calibrated.",
                    "rationale": (
                        f"easy_share (zones 1-2) = {easy_share}% across n_activities={hr_zones['n_activities']} "
                        f"zone-tagged activities, below the 20% easy-time guideline."
                    ),
                }
            )

    if not recs:
        n = stats.get("n_running_activities", 0)
        recs.append(
            {
                "text": (
                    f"You've logged {n} runs so far. Keep building a consistent routine and check back here as "
                    f"more data comes in -- there's not yet a clear pattern worth flagging. {FALLBACK_NOTE}"
                ),
                "evidence": "hypothesis",
                "why_it_matters": "More runs on record means better, more personal advice next time.",
                "rationale": f"n_running_activities={n}; no rule-based trigger fired against current data, so this is a plain status note.",
            }
        )

    return recs[:5]
