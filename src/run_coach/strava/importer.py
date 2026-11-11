"""Strava bulk-export activities.csv parser.

We never call the Strava API (per the project's design: this is a one-time,
user-initiated upload of the user's own export, not a live integration).
Strava's exact CSV header set has shifted over the years and is translated
to the account's display language, and some exports carry duplicate header
names across activity types. Rather than assume one fixed header row, we
match each logical field against several candidate header spellings and
skip (recording a gap) when nothing matches — never guess a value.

Header matching (and the description/note exclusion list below) folds
accents and case, so a Spanish export that does or doesn't accent
"cardiaca"/"cardíaca" matches the same candidate either way. The Spanish
and Russian candidates are otherwise best-effort translations verified
against one real Spanish export; a real export in either language that
still doesn't match is covered by the column-mapping step.

Columns we intentionally never read: any header containing "description",
"note", or their Spanish/Russian equivalents (case/accent-insensitive) —
that's "Activity Description" and "Private Note" in English exports,
which the project must never store.

Activity-type labels are also translated (Spanish for now) to the English
canonical forms ("Carrera" -> "Run", etc.) used throughout the rest of the
app, since is_running() and friends key off an English "run" substring.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EXCLUDED_HEADER_SUBSTRINGS = (
    "description",
    "note",
    "nota",
    "descripcion",
    "описание",
    "заметка",
    "примечан",
)

FIELD_CANDIDATES = {
    "id": ["Activity ID", "ID de la actividad", "ID de actividad", "ID активности"],
    "date": ["Activity Date", "Fecha de la actividad", "Дата активности"],
    "type": ["Activity Type", "Tipo de actividad", "Тип активности"],
    "distance": ["Distance", "Distancia", "Дистанция"],
    "moving_time": ["Moving Time", "Tiempo en movimiento", "Время в движении"],
    "elapsed_time": ["Elapsed Time", "Tiempo transcurrido", "Затраченное время"],
    "avg_hr": [
        "Average Heart Rate",
        "Frecuencia cardíaca media",
        "Frecuencia cardiaca promedio",
        "Средний пульс",
    ],
    "max_hr": [
        "Max Heart Rate",
        "Frecuencia cardíaca máxima",
        "Frecuencia cardiaca máxima",
        "Максимальный пульс",
    ],
    "elevation_gain": ["Elevation Gain", "Desnivel positivo", "Набор высоты"],
    "calories": ["Calories", "Calorías", "Калории"],
}

REQUIRED_FIELDS = ("id", "date", "type")

# Strava's CSV export has used a few date formats over the years. These are
# tried first (locale-independent, no month name to translate); anything
# with a month name (English, Spanish, or Russian, abbreviated or full)
# falls through to _parse_month_name_date below.
DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]

RUN_TYPES = {"run", "trail run", "virtual run", "treadmill run"}

# Non-English activity-type labels translated to the canonical English forms
# the rest of the app (is_running() and friends) expects. Keys are folded
# the same way header names are (accent-stripped, lowercased).
ACTIVITY_TYPE_TRANSLATIONS = {
    # Spanish
    "carrera": "Run",
    "carrera trail": "Trail Run",
    "carrera en sendero": "Trail Run",
    "carrera virtual": "Virtual Run",
    "carrera en cinta": "Treadmill Run",
    "carrera en caminadora": "Treadmill Run",
    "senderismo": "Hike",
    "caminata": "Walk",
    "ciclismo": "Ride",
    "bicicleta": "Ride",
    "entrenamiento de fuerza": "Weight Training",
    "musculacion": "Weight Training",
    "pilates": "Pilates",
    "yoga": "Yoga",
    "entrenamiento": "Workout",
}

# Month names/abbreviations in English, Spanish, and Russian, folded to
# lowercase (accents are stripped by _month_lookup before the lookup, so
# e.g. "SEP." and "sep" both land on the same key). Spanish "mar"/"may" and
# English "mar"/"may" happen to agree on the month number, so no collision.
MONTH_ALIASES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
    "ene": 1, "enero": 1,
    "marzo": 3,
    "abr": 4, "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "septiembre": 9, "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "dic": 12, "diciembre": 12,
    "febrero": 2,
    "янв": 1, "январь": 1, "января": 1,
    "фев": 2, "февр": 2, "февраль": 2, "февраля": 2,
    "мар": 3, "март": 3, "марта": 3,
    "апр": 4, "апрель": 4, "апреля": 4,
    "май": 5, "мая": 5,
    "июн": 6, "июнь": 6, "июня": 6,
    "июл": 7, "июль": 7, "июля": 7,
    "авг": 8, "август": 8, "августа": 8,
    "сен": 9, "сент": 9, "сентябрь": 9, "сентября": 9,
    "окт": 10, "октябрь": 10, "октября": 10,
    "ноя": 11, "нояб": 11, "ноябрь": 11, "ноября": 11,
    "дек": 12, "декабрь": 12, "декабря": 12,
}

# "H:MM:SS", optionally followed by an AM/PM marker (English "AM"/"PM" or
# Spanish "a. m."/"p. m." style spacing/dots). Absent, the hour is read as
# 24-hour (the format the Spanish export uses).
TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<mi>\d{2}):(?P<s>\d{2})\s*(?:(?P<ampm>[AaPp])\.?\s*[Mm]\.?)?")

DURATION_RE = re.compile(r"^\d+:\d{2}(:\d{2})?$")


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def _normalize_label(value: str) -> str:
    return _strip_accents(value).strip().lower()


@dataclass
class ParsedStravaActivity:
    external_id: str
    start_time_local: datetime
    activity_type: str
    distance_m: float | None
    moving_time_s: float | None
    elapsed_time_s: float | None
    avg_hr: float | None
    max_hr: float | None
    elevation_gain_m: float | None
    calories: float | None


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Map our logical field names to the actual header text present."""
    normalized = {_normalize_label(name): name for name in fieldnames}
    column_map: dict[str, str] = {}
    for field, candidates in FIELD_CANDIDATES.items():
        for candidate in candidates:
            key = _normalize_label(candidate)
            if key in normalized:
                column_map[field] = normalized[key]
                break
    return column_map


def inspect_header(path: Path) -> dict:
    """What the importer could and couldn't match, without importing anything.

    Used by the web layer to decide whether to show a column-mapping step
    instead of silently importing zero rows.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
    column_map = _build_column_map(fieldnames)
    return {
        "available_headers": fieldnames,
        "matched_fields": column_map,
        "missing_required_fields": [f for f in REQUIRED_FIELDS if f not in column_map],
    }


def _safe_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    # European-style decimal comma ("5,0"), vs. a thousands-separator comma
    # ("1,234.56") which we strip instead.
    if "," in value and "." not in value:
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    if "," in value and "." in value:
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _parse_duration_seconds(value: str | None) -> float | None:
    """Accept both Strava's usual raw-seconds export and an "H:MM:SS" string."""
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    if DURATION_RE.match(value):
        parts = [int(p) for p in value.split(":")]
        if len(parts) == 3:
            h, m, s = parts
        else:
            h, m, s = 0, *parts
        return float(h * 3600 + m * 60 + s)
    return _safe_float(value)


def _month_lookup(token: str) -> int | None:
    return MONTH_ALIASES.get(_strip_accents(token.strip(".")).lower())


def _parse_month_name_date(value: str) -> datetime | None:
    """Day-Month-Year or Month-Day-Year, with a named month in English,
    Spanish, or Russian, abbreviated or full, dotted or not (e.g. "2 nov
    2026, 12:22:18", "29 sept 2026, 18:36:54", "Dec 23, 2023, 7:15:32 AM").

    Order-independent: we pick out the 4-digit year and the month-name
    token from the date portion, whichever position each is in, and treat
    whatever numeric token is left as the day.
    """
    time_match = TIME_RE.search(value)
    if not time_match:
        return None
    hour = int(time_match.group("h"))
    minute = int(time_match.group("mi"))
    second = int(time_match.group("s"))
    ampm = time_match.group("ampm")
    if ampm:
        ampm = ampm.lower()
        if ampm == "p" and hour != 12:
            hour += 12
        elif ampm == "a" and hour == 12:
            hour = 0

    date_part = re.sub(r"[,\s]+$", "", value[: time_match.start()])
    raw_tokens = re.split(r"[\s,]+", date_part.strip())
    tokens = [t for t in raw_tokens if t and t.lower() != "de"]

    year: int | None = None
    month: int | None = None
    remaining: list[str] = []
    for token in tokens:
        cleaned = token.strip(".")
        if year is None and re.fullmatch(r"\d{4}", cleaned):
            year = int(cleaned)
            continue
        candidate_month = _month_lookup(cleaned)
        if candidate_month is not None and month is None:
            month = candidate_month
            continue
        remaining.append(cleaned)

    if year is None or month is None:
        return None

    day = next((int(t) for t in remaining if re.fullmatch(r"\d{1,2}", t)), None)
    if day is None:
        return None

    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _date_format_signature(value: str) -> str:
    """Collapse a date string to its shape (digits -> '#', letters -> 'X')
    so that many unparseable rows sharing the same format get reported as
    one gap instead of one per row.
    """
    sig = re.sub(r"\d+", "#", value)
    return re.sub(r"[^\W\d_]+", "X", sig)


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return _parse_month_name_date(value)


def _translate_activity_type(raw: str) -> str:
    """Translate a non-English activity-type label to the canonical English
    form the rest of the app expects; English labels pass through unchanged.
    """
    return ACTIVITY_TYPE_TRANSLATIONS.get(_normalize_label(raw), raw)


def parse_strava_csv(
    path: Path, column_overrides: dict[str, str] | None = None
) -> tuple[list[ParsedStravaActivity], list[str]]:
    gaps: list[str] = []
    activities: list[ParsedStravaActivity] = []

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            gaps.append("strava: activities.csv has no header row, nothing imported")
            return [], gaps

        excluded = [
            name
            for name in reader.fieldnames
            if any(substr in _normalize_label(name) for substr in EXCLUDED_HEADER_SUBSTRINGS)
        ]
        if excluded:
            gaps.append(f"strava: ignored description/note columns: {', '.join(excluded)}")

        column_map = _build_column_map(reader.fieldnames)
        if column_overrides:
            for field, header_name in column_overrides.items():
                if header_name and header_name in reader.fieldnames:
                    column_map[field] = header_name
        required_missing = [f for f in REQUIRED_FIELDS if f not in column_map]
        if required_missing:
            gaps.append(
                f"strava: could not find columns for {required_missing} in activities.csv header; "
                "nothing imported (Strava may have renamed or translated the header row)"
            )
            return [], gaps

        date_failures: dict[str, dict] = {}
        for row in reader:
            external_id = row.get(column_map["id"], "").strip()
            raw_date = row.get(column_map["date"], "")
            activity_type = _translate_activity_type(row.get(column_map["type"], "").strip())
            if not external_id or not raw_date:
                continue
            start = _parse_date(raw_date)
            if start is None:
                signature = _date_format_signature(raw_date)
                entry = date_failures.setdefault(signature, {"count": 0, "example": raw_date})
                entry["count"] += 1
                continue

            distance_m = _safe_float(row.get(column_map.get("distance", ""), None))
            moving_time_s = _parse_duration_seconds(row.get(column_map.get("moving_time", ""), None))
            elapsed_time_s = _parse_duration_seconds(row.get(column_map.get("elapsed_time", ""), None))

            if (
                activity_type.lower() in RUN_TYPES
                and distance_m
                and moving_time_s
                and not _plausible_running_pace(distance_m, moving_time_s)
            ):
                if _plausible_running_pace(distance_m * 1000, moving_time_s):
                    gaps.append(
                        f"strava activity {external_id}: Distance column looks like it's in km, not "
                        "meters; auto-converted"
                    )
                    distance_m = distance_m * 1000
                else:
                    gaps.append(
                        f"strava activity {external_id}: distance/time combination gives an implausible "
                        "running pace; the Distance column's unit may not be meters as assumed"
                    )

            activities.append(
                ParsedStravaActivity(
                    external_id=external_id,
                    start_time_local=start,
                    activity_type=activity_type,
                    distance_m=distance_m,
                    moving_time_s=moving_time_s,
                    elapsed_time_s=elapsed_time_s,
                    avg_hr=_safe_float(row.get(column_map.get("avg_hr", ""), None)),
                    max_hr=_safe_float(row.get(column_map.get("max_hr", ""), None)),
                    elevation_gain_m=_safe_float(row.get(column_map.get("elevation_gain", ""), None)),
                    calories=_safe_float(row.get(column_map.get("calories", ""), None)),
                )
            )

        for signature, info in date_failures.items():
            gaps.append(
                f"strava: {info['count']} row(s) skipped — unrecognized date format, e.g. "
                f"'{info['example']}' (pattern: {signature})"
            )

    return activities, gaps


def _plausible_running_pace(distance_m: float, moving_time_s: float, lo: float = 90, hi: float = 1200) -> bool:
    """Sanity range for pace in seconds/km, assuming Distance is in meters
    (Strava's API and, per long-standing community parsing scripts, its CSV
    export both use meters). 90 s/km is a 2:30/km sprint; 1200 s/km is a
    20:00/km walk-run, generous on both ends.
    """
    if distance_m <= 0:
        return False
    pace = moving_time_s / (distance_m / 1000.0)
    return lo <= pace <= hi
