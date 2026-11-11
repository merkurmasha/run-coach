"""Where am I in my training: status relative to the goals set in setup.

Method notes (shown on the dashboard):
- "Current estimated race times" use only the best qualifying effort from
  the last RECENT_FORM_WEEKS weeks (not all-time), extrapolated with
  Riegel's formula -- an estimate of current fitness, always labelled as
  such, and distinct from the Progress section's all-time personal bests.
- The ahead / on_track / behind status line is one explicit, score-based
  rule (shown in the UI, never hidden): for each goal that's actually set
  (runs_per_week, target pace), compute actual / goal as a ratio (pace is
  inverted so faster-than-target scores above 1.0), then average the
  ratios that apply. >=1.1 is "ahead", >=0.9 is "on_track", below that is
  "behind". With no goal set at all, there's nothing to compare against
  and the status is "no_goal_set". This never prescribes a change -- it
  only describes where the numbers currently sit, which matters when
  follows_watch_plan is true and the watch, not this app, owns the plan.
- A "volume spike" flags when the current week's distance exceeds
  SPIKE_THRESHOLD times the trailing 4-week average -- a common,
  non-personalized rule of thumb, not a measured injury-risk threshold.
"""

from __future__ import annotations

from datetime import date, timedelta

from run_coach.metrics.common import is_running, iso_week_key, local_date_of
from run_coach.metrics.progress import personal_bests, race_time_predictions
from run_coach.metrics.recovery import recovery_summary

RECENT_FORM_WEEKS = 8
CONSISTENCY_WEEKS = 8
LONG_RUN_WEEKS = 12
SPIKE_THRESHOLD = 1.3
STATUS_RULE = (
    "For each goal that's set (runs_per_week, target pace), actual / goal over the last 4 "
    "weeks is scored as a ratio (pace inverted, so faster-than-target scores above 1.0); the "
    "applicable ratios are averaged. >=1.1 average is 'ahead', >=0.9 is 'on track', below that "
    "is 'behind'."
)


def _runs(activities: list) -> list:
    return [a for a in activities if is_running(a["activity_type"])]


def _in_window(runs: list, weeks: int, as_of: date) -> list:
    start = as_of - timedelta(weeks=weeks)
    return [r for r in runs if start <= local_date_of(r) <= as_of]


def current_form_estimates(activities: list, as_of: date | None = None) -> dict:
    """5k/10k/half estimates from the best qualifying effort in the last
    RECENT_FORM_WEEKS weeks, via Riegel."""
    if as_of is None:
        as_of = date.today()
    recent = _in_window(_runs(activities), RECENT_FORM_WEEKS, as_of)
    pbs = personal_bests(recent)
    return {"window_weeks": RECENT_FORM_WEEKS, "predictions": race_time_predictions(pbs)}


def gap_to_target_pace(activities: list, target_pace_s_per_km: float | None, as_of: date | None = None) -> dict | None:
    if target_pace_s_per_km is None:
        return None
    if as_of is None:
        as_of = date.today()
    recent = _in_window(_runs(activities), 4, as_of)
    distance_m = sum(r["distance_m"] or 0.0 for r in recent)
    moving_time_s = sum(r["moving_time_s"] or 0.0 for r in recent)
    if not distance_m:
        return {"avg_pace_s_per_km_last_4w": None, "target_pace_s_per_km": target_pace_s_per_km, "gap_s_per_km": None}
    avg_pace = moving_time_s / (distance_m / 1000.0)
    return {
        "avg_pace_s_per_km_last_4w": round(avg_pace, 1),
        "target_pace_s_per_km": target_pace_s_per_km,
        "gap_s_per_km": round(avg_pace - target_pace_s_per_km, 1),
    }


def weeks_until_race(race_date: str | None, as_of: date | None = None) -> int | None:
    if not race_date:
        return None
    if as_of is None:
        as_of = date.today()
    days = (date.fromisoformat(race_date) - as_of).days
    return days // 7


def weekly_volume_vs_average(activities: list, as_of: date | None = None) -> dict:
    if as_of is None:
        as_of = date.today()
    runs = _runs(activities)
    this_week_km = sum((r["distance_m"] or 0.0) for r in _in_window(runs, 1, as_of)) / 1000.0

    def avg_weekly_km(weeks: int) -> float:
        total = sum((r["distance_m"] or 0.0) for r in _in_window(runs, weeks, as_of))
        return round(total / 1000.0 / weeks, 1)

    avg_4w = avg_weekly_km(4)
    avg_12w = avg_weekly_km(12)
    is_spike = avg_4w > 0 and this_week_km > SPIKE_THRESHOLD * avg_4w
    return {
        "this_week_km": round(this_week_km, 1),
        "avg_4w_km": avg_4w,
        "avg_12w_km": avg_12w,
        "is_spike": is_spike,
        "spike_threshold": SPIKE_THRESHOLD,
    }


def consistency(activities: list, as_of: date | None = None, weeks: int = CONSISTENCY_WEEKS) -> dict:
    if as_of is None:
        as_of = date.today()
    recent = _in_window(_runs(activities), weeks, as_of)
    per_week: dict[str, int] = {}
    for r in recent:
        key = iso_week_key(local_date_of(r))
        per_week[key] = per_week.get(key, 0) + 1

    # Count against the exact set of calendar weeks the window covers --
    # not `weeks` itself, since a 7*weeks-day lookback can straddle one
    # more or fewer ISO week boundaries than its nominal week count.
    expected_week_keys = {iso_week_key(as_of - timedelta(weeks=i)) for i in range(weeks)}
    weeks_with_no_runs = sum(1 for key in expected_week_keys if key not in per_week)

    return {
        "window_weeks": weeks,
        "avg_runs_per_week": round(len(recent) / weeks, 1) if weeks else 0.0,
        "weeks_with_at_least_one_run": len(expected_week_keys) - weeks_with_no_runs,
        "weeks_with_no_runs": weeks_with_no_runs,
    }


def long_run_progression(activities: list, as_of: date | None = None, weeks: int = LONG_RUN_WEEKS) -> list[dict]:
    if as_of is None:
        as_of = date.today()
    recent = _in_window(_runs(activities), weeks, as_of)
    longest_by_week: dict[str, float] = {}
    for r in recent:
        key = iso_week_key(local_date_of(r))
        longest_by_week[key] = max(longest_by_week.get(key, 0.0), r["distance_m"] or 0.0)
    return [
        {"week": key, "longest_run_km": round(longest_by_week[key] / 1000.0, 1)} for key in sorted(longest_by_week)
    ]


def status_line(activities: list, settings: dict, as_of: date | None = None) -> dict:
    if as_of is None:
        as_of = date.today()
    runs_per_week_goal = settings.get("runs_per_week")
    target_pace = settings.get("target_pace_s_per_km")
    if not runs_per_week_goal and not target_pace:
        return {"status": "no_goal_set", "rule": STATUS_RULE}

    recent = _in_window(_runs(activities), 4, as_of)
    avg_runs_per_week = len(recent) / 4.0
    distance_m = sum(r["distance_m"] or 0.0 for r in recent)
    moving_time_s = sum(r["moving_time_s"] or 0.0 for r in recent)
    avg_pace = (moving_time_s / (distance_m / 1000.0)) if distance_m else None

    ratios = []
    if runs_per_week_goal:
        ratios.append(avg_runs_per_week / runs_per_week_goal)
    if target_pace and avg_pace:
        ratios.append(target_pace / avg_pace)  # faster than target => > 1.0

    if not ratios:
        status = "no_goal_set"
    else:
        score = sum(ratios) / len(ratios)
        status = "ahead" if score >= 1.1 else "on_track" if score >= 0.9 else "behind"

    return {
        "status": status,
        "rule": STATUS_RULE,
        "avg_runs_per_week_last_4w": round(avg_runs_per_week, 1),
        "avg_pace_s_per_km_last_4w": round(avg_pace, 1) if avg_pace is not None else None,
    }


def training_standing(activities: list, daily_metrics: list, settings: dict, as_of: date | None = None) -> dict:
    """Everything the "Where am I in my training?" section needs."""
    return {
        "current_form_estimates": current_form_estimates(activities, as_of),
        "gap_to_target_pace": gap_to_target_pace(activities, settings.get("target_pace_s_per_km"), as_of),
        "weeks_until_race": weeks_until_race(settings.get("race_date"), as_of),
        "weekly_volume_vs_average": weekly_volume_vs_average(activities, as_of),
        "consistency": consistency(activities, as_of),
        "long_run_progression": long_run_progression(activities, as_of),
        "recovery": recovery_summary(daily_metrics, as_of=as_of),
        "status": status_line(activities, settings, as_of),
        "follows_watch_plan": bool(settings.get("follows_watch_plan", False)),
    }
