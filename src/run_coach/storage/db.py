"""SQLite schema and data access. Everything here stays local to ./data."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from run_coach.config import DB_PATH, ensure_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('garmin', 'strava')),
    external_id TEXT NOT NULL,
    start_time_utc TEXT NOT NULL,
    local_date TEXT NOT NULL,
    activity_type TEXT,
    distance_m REAL,
    moving_time_s REAL,
    elapsed_time_s REAL,
    avg_hr REAL,
    max_hr REAL,
    avg_pace_s_per_km REAL,
    elevation_gain_m REAL,
    calories REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time_utc);
CREATE INDEX IF NOT EXISTS idx_activities_local_date ON activities(local_date);

CREATE TABLE IF NOT EXISTS activity_hr_zones (
    activity_id TEXT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    zone INTEGER NOT NULL,
    minutes REAL NOT NULL,
    PRIMARY KEY (activity_id, zone)
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    date TEXT PRIMARY KEY,
    sleep_duration_s REAL,
    sleep_score REAL,
    hrv_ms REAL,
    resting_hr REAL,
    body_battery_high REAL,
    body_battery_low REAL,
    stress_avg REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycle_entries (
    start_date TEXT PRIMARY KEY,
    cycle_length_days INTEGER,
    source TEXT NOT NULL CHECK (source IN ('garmin', 'manual'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    range_start TEXT,
    range_end TEXT,
    counts_json TEXT NOT NULL,
    data_gaps_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with contextlib.closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Activity:
    source: str
    external_id: str
    start_time_utc: str
    local_date: str
    activity_type: str | None
    distance_m: float | None
    moving_time_s: float | None
    elapsed_time_s: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_pace_s_per_km: float | None
    elevation_gain_m: float | None
    calories: float | None
    hr_zone_minutes: dict[int, float] | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.external_id}"


def upsert_activity(conn: sqlite3.Connection, activity: Activity) -> None:
    conn.execute(
        """
        INSERT INTO activities (
            id, source, external_id, start_time_utc, local_date, activity_type,
            distance_m, moving_time_s, elapsed_time_s, avg_hr, max_hr,
            avg_pace_s_per_km, elevation_gain_m, calories, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            start_time_utc=excluded.start_time_utc,
            local_date=excluded.local_date,
            activity_type=excluded.activity_type,
            distance_m=excluded.distance_m,
            moving_time_s=excluded.moving_time_s,
            elapsed_time_s=excluded.elapsed_time_s,
            avg_hr=excluded.avg_hr,
            max_hr=excluded.max_hr,
            avg_pace_s_per_km=excluded.avg_pace_s_per_km,
            elevation_gain_m=excluded.elevation_gain_m,
            calories=excluded.calories
        """,
        (
            activity.id,
            activity.source,
            activity.external_id,
            activity.start_time_utc,
            activity.local_date,
            activity.activity_type,
            activity.distance_m,
            activity.moving_time_s,
            activity.elapsed_time_s,
            activity.avg_hr,
            activity.max_hr,
            activity.avg_pace_s_per_km,
            activity.elevation_gain_m,
            activity.calories,
            now_iso(),
        ),
    )
    if activity.hr_zone_minutes:
        for zone, minutes in activity.hr_zone_minutes.items():
            conn.execute(
                """
                INSERT INTO activity_hr_zones (activity_id, zone, minutes)
                VALUES (?, ?, ?)
                ON CONFLICT(activity_id, zone) DO UPDATE SET minutes=excluded.minutes
                """,
                (activity.id, zone, minutes),
            )


def find_activity_near(
    conn: sqlite3.Connection, start_time_utc: str, tolerance_minutes: int = 5
) -> sqlite3.Row | None:
    """Find any activity (any source) starting within `tolerance_minutes` of the given time."""
    target = datetime.fromisoformat(start_time_utc)
    rows = conn.execute(
        "SELECT * FROM activities WHERE local_date BETWEEN ? AND ?",
        (
            (target.date().isoformat()),
            (target.date().isoformat()),
        ),
    ).fetchall()
    for row in rows:
        other = datetime.fromisoformat(row["start_time_utc"])
        if abs((other - target).total_seconds()) <= tolerance_minutes * 60:
            return row
    return None


def upsert_daily_metric(conn: sqlite3.Connection, date: str, **fields: float | None) -> None:
    existing = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", (date,)).fetchone()
    merged = dict(existing) if existing else {
        "date": date,
        "sleep_duration_s": None,
        "sleep_score": None,
        "hrv_ms": None,
        "resting_hr": None,
        "body_battery_high": None,
        "body_battery_low": None,
        "stress_avg": None,
    }
    for key, value in fields.items():
        if value is not None:
            merged[key] = value
    conn.execute(
        """
        INSERT INTO daily_metrics (
            date, sleep_duration_s, sleep_score, hrv_ms, resting_hr,
            body_battery_high, body_battery_low, stress_avg, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            sleep_duration_s=excluded.sleep_duration_s,
            sleep_score=excluded.sleep_score,
            hrv_ms=excluded.hrv_ms,
            resting_hr=excluded.resting_hr,
            body_battery_high=excluded.body_battery_high,
            body_battery_low=excluded.body_battery_low,
            stress_avg=excluded.stress_avg,
            updated_at=excluded.updated_at
        """,
        (
            date,
            merged["sleep_duration_s"],
            merged["sleep_score"],
            merged["hrv_ms"],
            merged["resting_hr"],
            merged["body_battery_high"],
            merged["body_battery_low"],
            merged["stress_avg"],
            now_iso(),
        ),
    )


def upsert_cycle_entry(
    conn: sqlite3.Connection, start_date: str, cycle_length_days: int | None, source: str
) -> None:
    conn.execute(
        """
        INSERT INTO cycle_entries (start_date, cycle_length_days, source)
        VALUES (?, ?, ?)
        ON CONFLICT(start_date) DO UPDATE SET
            cycle_length_days=excluded.cycle_length_days,
            source=excluded.source
        """,
        (start_date, cycle_length_days, source),
    )


def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, json.dumps(value)),
    )


def all_settings(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: json.loads(row["value"]) for row in rows}


def append_sync_log(
    conn: sqlite3.Connection,
    source: str,
    range_start: str | None,
    range_end: str | None,
    counts: dict,
    data_gaps: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO sync_log (ts, source, range_start, range_end, counts_json, data_gaps_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (now_iso(), source, range_start, range_end, json.dumps(counts), json.dumps(data_gaps)),
    )


def latest_data_gaps(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT data_gaps_json FROM sync_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    gaps: list[str] = []
    for row in rows:
        for gap in json.loads(row["data_gaps_json"]):
            if gap not in gaps:
                gaps.append(gap)
    return gaps


def set_cached_recommendations(conn: sqlite3.Connection, stats: dict, recommendations: list) -> None:
    conn.execute(
        """
        INSERT INTO recommendations_cache (id, generated_at, stats_json, recommendations_json)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            generated_at=excluded.generated_at,
            stats_json=excluded.stats_json,
            recommendations_json=excluded.recommendations_json
        """,
        (now_iso(), json.dumps(stats), json.dumps(recommendations)),
    )


def get_cached_recommendations(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT generated_at, stats_json, recommendations_json FROM recommendations_cache WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "generated_at": row["generated_at"],
        "stats": json.loads(row["stats_json"]),
        "recommendations": json.loads(row["recommendations_json"]),
    }


def all_activities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM activities ORDER BY start_time_utc").fetchall()


def all_daily_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM daily_metrics ORDER BY date").fetchall()


def all_cycle_entries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cycle_entries ORDER BY start_date").fetchall()


def activity_hr_zones(conn: sqlite3.Connection, activity_id: str) -> dict[int, float]:
    rows = conn.execute(
        "SELECT zone, minutes FROM activity_hr_zones WHERE activity_id = ?", (activity_id,)
    ).fetchall()
    return {row["zone"]: row["minutes"] for row in rows}


@contextlib.contextmanager
def transaction(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
