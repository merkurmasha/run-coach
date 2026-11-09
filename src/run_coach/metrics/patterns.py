"""Your patterns: runs grouped by menstrual-cycle phase.

Method: each run is assigned to the cycle entry with the latest start_date
on or before the run's date, then placed into one of four phases by its
offset into that cycle, scaled to the entry's own cycle length (default 28
days if unknown). Phase boundaries are the commonly used approximation
(menstrual ~0-18%, follicular ~18-46%, ovulation ~46-57%, luteal the rest)
-- not a personalized measurement. A phase with fewer than MIN_SAMPLE_SIZE
runs reports "not enough data yet" rather than an average, per the
project's rule against drawing conclusions from thin data.

This module never invents a phase for a run with no cycle entry on or
before it, and never correlates against free-text "special conditions" --
that text has no per-day timestamps to correlate against, so it is passed
through as qualitative context only (see recommendations/aggregate).
"""

from __future__ import annotations

from datetime import date

from run_coach.metrics.common import MIN_SAMPLE_SIZE, is_running, local_date_of

PHASE_FRACTIONS = {
    "menstrual": (0.0, 0.18),
    "follicular": (0.18, 0.46),
    "ovulation": (0.46, 0.57),
    "luteal": (0.57, 1.0),
}
DEFAULT_CYCLE_LENGTH = 28


def _phase_for_offset(offset_days: int, cycle_length: int) -> str:
    fraction = (offset_days % cycle_length) / cycle_length
    for phase, (lo, hi) in PHASE_FRACTIONS.items():
        if lo <= fraction < hi:
            return phase
    return "luteal"


def _entry_for_date(cycle_entries: list, run_date: date):
    candidates = [e for e in cycle_entries if date.fromisoformat(e["start_date"]) <= run_date]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e["start_date"])


def cycle_phase_patterns(activities: list, cycle_entries: list, min_n: int = MIN_SAMPLE_SIZE) -> dict:
    if not cycle_entries:
        return {"available": False, "reason": "no cycle data logged", "phases": {}}

    runs = [a for a in activities if is_running(a["activity_type"])]
    buckets: dict[str, list] = {phase: [] for phase in PHASE_FRACTIONS}
    unmatched = 0

    for row in runs:
        run_date = local_date_of(row)
        entry = _entry_for_date(cycle_entries, run_date)
        if entry is None:
            unmatched += 1
            continue
        cycle_length = entry["cycle_length_days"] or DEFAULT_CYCLE_LENGTH
        offset = (run_date - date.fromisoformat(entry["start_date"])).days
        phase = _phase_for_offset(offset, cycle_length)
        buckets[phase].append(row)

    phases = {}
    for phase, rows in buckets.items():
        n = len(rows)
        if n < min_n:
            phases[phase] = {"n": n, "reason": "not enough data yet"}
            continue
        paces = [r["avg_pace_s_per_km"] for r in rows if r["avg_pace_s_per_km"]]
        hrs = [r["avg_hr"] for r in rows if r["avg_hr"]]
        phases[phase] = {
            "n": n,
            "avg_pace_s_per_km": round(sum(paces) / len(paces), 1) if paces else None,
            "avg_hr": round(sum(hrs) / len(hrs), 1) if hrs else None,
        }

    return {"available": True, "phases": phases, "runs_without_cycle_data": unmatched}
