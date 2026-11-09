"""Thin wrapper around garmin_personal_api: token handling, date chunking,
and defensive field extraction.

The Personal API's response payload shapes are not published in the
client's README or source (confirmed Nov 2026; see the Swagger docs link
in the README for anything more precise). The field-name candidates below
come from Garmin's internal Connect API, which the Personal API's service
paths (sleep-service, hrv-service, wellness-service, ...) match, and from
community clients that document that internal API. They may not be exact.
Every extraction here is defensive: a missing or renamed field becomes a
data gap, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
)

from run_coach.config import GARMIN_SYNC_CHUNK_DAYS


def chunk_date_range(start: date, end: date, chunk_days: int = GARMIN_SYNC_CHUNK_DAYS) -> list[tuple[date, date]]:
    """Split an inclusive date range into chunks of at most `chunk_days` days."""
    if start > end:
        return []
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def dig(data: Any, *paths: str, default: Any = None) -> Any:
    """Try each dotted-path candidate against `data` (dict or list of dicts).

    For a list, each path is tried against every item and the first hit wins.
    """
    if data is None:
        return default
    candidates = data if isinstance(data, list) else [data]
    for item in candidates:
        for path in paths:
            cursor = item
            ok = True
            for key in path.split("."):
                if isinstance(cursor, dict) and key in cursor:
                    cursor = cursor[key]
                else:
                    ok = False
                    break
            if ok and cursor is not None:
                return cursor
    return default


class GarminClient:
    """Wraps the official Personal API client with a token obtained once per sync."""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._authenticator = PersonalApiAuthenticator(timeout=timeout)
        token = self._authenticator.obtain_token(api_key)
        self._client = GarminPersonalApiClient(token.access_token, timeout=timeout)

    def close(self) -> None:
        self._client.close()
        self._authenticator.close()

    def __enter__(self) -> "GarminClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def safe_call(self, label: str, fn, gaps: list[str], *args, **kwargs):
        """Call `fn`; on any API or parsing error, append to `gaps` and return None."""
        try:
            return fn(*args, **kwargs)
        except (HttpError, GarminPersonalApiError) as exc:
            gaps.append(f"{label}: {exc}")
            return None
        except Exception as exc:  # defensive: a field-shape surprise must not crash a sync
            gaps.append(f"{label}: unexpected error ({exc})")
            return None

    def search_activities(self, start: date, end: date, gaps: list[str], limit: int = 100) -> list[dict]:
        results: list[dict] = []
        offset = 0
        while True:
            page = self.safe_call(
                "search_activities",
                self._client.search_activities,
                gaps,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                start=offset,
                limit=limit,
            )
            if not page:
                break
            results.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return results

    def daily_sleep_summaries(self, start: date, end: date, gaps: list[str]) -> list[dict]:
        raw = self.safe_call(
            "sleep", self._client.get_daily_sleep_summaries, gaps, start.isoformat(), end.isoformat()
        )
        return normalize_list(raw, "dailySleepDTO", "sleepSummaries")

    def daily_hrv_summaries(self, start: date, end: date, gaps: list[str]) -> list[dict]:
        raw = self.safe_call(
            "hrv", self._client.get_daily_hrv_summaries, gaps, start.isoformat(), end.isoformat()
        )
        return normalize_list(raw, "hrvSummaries")

    def daily_body_battery(self, start: date, end: date, gaps: list[str]) -> list[dict]:
        raw = self.safe_call(
            "body_battery", self._client.get_daily_body_battery, gaps, start.isoformat(), end.isoformat()
        )
        return normalize_list(raw)

    def daily_stress(self, start: date, end: date, gaps: list[str]) -> list[dict]:
        raw = self.safe_call(
            "stress", self._client.get_daily_stress, gaps, start.isoformat(), end.isoformat()
        )
        return normalize_list(raw)

    def daily_summaries(self, start: date, end: date, gaps: list[str]) -> list[dict]:
        """Resting HR and other per-day aggregates."""
        raw = self.safe_call(
            "daily_summaries", self._client.get_daily_summaries, gaps, start.isoformat(), end.isoformat()
        )
        return normalize_list(raw)

    def menstrual_cycle_summary(self, day: date, gaps: list[str]) -> dict | None:
        return self.safe_call(
            "cycle", self._client.get_menstrual_cycle_summary, gaps, day.isoformat()
        )

    def activity_workouts(self, activity_id: str, gaps: list[str]) -> dict | None:
        return self.safe_call("activity_workouts", self._client.get_activity_workouts, gaps, activity_id)


def normalize_list(raw: Any, *wrapper_keys: str) -> list[dict]:
    """Garmin range endpoints return either a bare list or a dict wrapping one.
    Try each known wrapper key, then fall back to treating the dict itself as
    a single-item list.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in wrapper_keys:
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        return [raw]
    return []


@dataclass
class ParsedActivity:
    external_id: str
    start_time_utc: str | None
    local_date: str | None
    activity_type: str | None
    distance_m: float | None
    moving_time_s: float | None
    elapsed_time_s: float | None
    avg_hr: float | None
    max_hr: float | None
    elevation_gain_m: float | None
    calories: float | None
    raw: dict = field(default_factory=dict)


def parse_hr_zone_minutes(raw: dict) -> dict[int, float] | None:
    """Best-effort extraction of per-zone time from an activity summary.

    Garmin does not document a stable field for this on the Personal API;
    these candidates (a flat hrTimeInZone_N set of seconds fields, or a
    nested zone-list shape) are the patterns seen on Garmin's internal
    Connect API. Returns None, not an exception, if neither matches.
    """
    flat_keys = [f"hrTimeInZone_{i}" for i in range(1, 6)]
    if all(raw.get(key) is not None for key in flat_keys[:3]):
        return {i: _to_float(raw.get(key)) / 60.0 for i, key in enumerate(flat_keys, start=1) if raw.get(key) is not None}
    nested = dig(raw, "timeInHrZones", "hrZones", "zoneDTOs")
    if isinstance(nested, list) and nested:
        zones: dict[int, float] = {}
        for entry in nested:
            zone_num = dig(entry, "zoneNumber", "zone")
            seconds = dig(entry, "secsInZone", "timeInZone", "seconds")
            if zone_num is not None and seconds is not None:
                zones[int(zone_num)] = _to_float(seconds) / 60.0
        return zones or None
    return None


def parse_activity(raw: dict, gaps: list[str]) -> ParsedActivity | None:
    activity_id = dig(raw, "activityId", "activityID", "id")
    if activity_id is None:
        gaps.append("activity: missing activityId, skipped one record")
        return None
    start_gmt = dig(raw, "startTimeGMT", "startTimeUtc", "startTimeGmt")
    start_local = dig(raw, "startTimeLocal")
    if start_gmt is None and start_local is None:
        gaps.append(f"activity {activity_id}: missing start time")
    elif start_gmt is None:
        gaps.append(f"activity {activity_id}: no GMT timestamp, using local time as an approximation of UTC")
    local_date = None
    if start_local:
        local_date = str(start_local)[:10]
    elif start_gmt:
        local_date = str(start_gmt)[:10]
    return ParsedActivity(
        external_id=str(activity_id),
        start_time_utc=_to_iso(start_gmt) or _to_iso(start_local),
        local_date=local_date,
        activity_type=dig(raw, "activityType.typeKey", "activityType"),
        distance_m=_to_float(dig(raw, "distance")),
        moving_time_s=_to_float(dig(raw, "movingDuration", "duration")),
        elapsed_time_s=_to_float(dig(raw, "elapsedDuration", "duration")),
        avg_hr=_to_float(dig(raw, "averageHR", "avgHr")),
        max_hr=_to_float(dig(raw, "maxHR", "maxHr")),
        elevation_gain_m=_to_float(dig(raw, "elevationGain")),
        calories=_to_float(dig(raw, "calories")),
        raw=raw,
    )


def _to_iso(value: Any) -> str | None:
    """Garmin formats timestamps as "yyyy-MM-dd HH:mm:ss". Normalize the
    separator and always mark the result as UTC (Z suffix) so every stored
    start_time_utc is timezone-aware and comparable; callers that pass a
    local-time fallback already logged a gap noting the approximation.
    """
    if value is None:
        return None
    text = str(value).replace(" ", "T")[:19]
    if not text.endswith("Z"):
        text += "Z"
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
