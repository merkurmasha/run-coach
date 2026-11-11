"""FastAPI app: the dashboard's static front end plus a small JSON API.

Everything here is local-only. The server binds to 127.0.0.1 (see cli.py's
`serve` command) and holds no auth, because it is meant to run on the
user's own machine for the user alone.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from run_coach.config import (
    APP_NAME,
    DATA_DIR,
    DB_PATH,
    Secrets,
    clear_env,
    ensure_data_dir,
    write_env,
)
from run_coach.demo.generator import generate_demo_data
from run_coach.metrics.aggregate import build_stats
from run_coach.storage.db import (
    append_sync_log,
    connect,
    get_cached_recommendations,
    init_db,
    set_setting,
    transaction,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEMO_DB_PATH = DATA_DIR / "demo.db"

SETTINGS_FIELDS = [
    "target_pace_s_per_km",
    "race_distance_m",
    "race_date",
    "runs_per_week",
    "follows_watch_plan",
    "cycle_mode",
    "special_conditions_text",
    "timezone",
    "units",
    "reference_hr",
    "telegram_enabled",
]

_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def _describe_claude_error(exc: Exception) -> str:
    """A short, redacted, user-facing description of a Claude API failure."""
    message = str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        message = "Authentication failed -- check that ANTHROPIC_API_KEY in .env is correct."
    elif isinstance(exc, anthropic.PermissionDeniedError):
        message = "The API key is valid but lacks permission for this model."
    elif isinstance(exc, anthropic.NotFoundError):
        message = f"Model or endpoint not found: {message}"
    elif isinstance(exc, anthropic.RateLimitError):
        message = "Rate limited by the Anthropic API -- try again shortly."
    elif isinstance(exc, anthropic.APIConnectionError):
        message = "Could not reach the Anthropic API -- check your network connection."
    elif isinstance(exc, anthropic.APIStatusError):
        message = f"Anthropic API error ({exc.status_code}): {exc.message}"
    return _KEY_PATTERN.sub("[REDACTED]", message)


def create_app(demo: bool = False) -> FastAPI:
    app = FastAPI(title=APP_NAME)
    db_path = DEMO_DB_PATH if demo else DB_PATH

    if demo:
        ensure_data_dir()
        if DEMO_DB_PATH.exists():
            DEMO_DB_PATH.unlink()
        init_db(DEMO_DB_PATH)
        conn = connect(DEMO_DB_PATH)
        generate_demo_data(conn)
        conn.commit()
        conn.close()
    else:
        init_db(db_path)

    def get_conn():
        return connect(db_path)

    @app.get("/api/status")
    def status() -> dict:
        secrets = Secrets.load()
        with get_conn() as conn:
            from run_coach.storage.db import all_settings

            settings = all_settings(conn)
        setup_complete = demo or bool(secrets.garmin_api_key)
        return {
            "app_name": APP_NAME,
            "demo": demo,
            "setup_complete": setup_complete,
            "has_claude": demo or secrets.has_claude(),
            "has_telegram": demo or secrets.has_telegram(),
            "settings": {k: settings.get(k) for k in SETTINGS_FIELDS},
        }

    @app.get("/api/stats")
    def stats() -> dict:
        conn = get_conn()
        try:
            return build_stats(conn)
        finally:
            conn.close()

    @app.get("/api/recommendations")
    def recommendations() -> dict:
        conn = get_conn()
        try:
            cached = get_cached_recommendations(conn)
        finally:
            conn.close()
        if cached is None:
            return {"generated_at": None, "recommendations": [], "stats_summary": None}
        return cached

    @app.post("/api/recommendations/generate")
    def generate_recommendations() -> dict:
        if demo:
            raise HTTPException(400, "Recommendations are pre-cached in demo mode; nothing to regenerate.")
        from run_coach.recommendations.generate import generate_and_cache

        secrets = Secrets.load()
        if not secrets.has_claude():
            raise HTTPException(400, "No ANTHROPIC_API_KEY configured. Add one in setup to enable this.")
        conn = get_conn()
        try:
            try:
                result = generate_and_cache(conn, secrets)
            except Exception as exc:
                raise HTTPException(502, _describe_claude_error(exc)) from exc
            conn.commit()
        finally:
            conn.close()
        return result

    @app.post("/api/claude/test")
    def test_claude() -> dict:
        if demo:
            raise HTTPException(400, "Demo mode doesn't use the Claude API.")
        secrets = Secrets.load()
        if not secrets.anthropic_api_key:
            return {"ok": False, "stage": "config", "message": "ANTHROPIC_API_KEY is not set in .env."}

        client = anthropic.Anthropic(api_key=secrets.anthropic_api_key)
        try:
            client.messages.create(
                model=secrets.claude_model,
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with only the word: ok"}],
            )
        except Exception as exc:  # defensive: this is a diagnostic endpoint, any failure is a result to show
            return {"ok": False, "stage": "api", "message": _describe_claude_error(exc)}
        return {"ok": True, "stage": "done", "message": f"Connected -- {secrets.claude_model} responded."}

    @app.post("/api/settings")
    def save_settings(payload: dict[str, Any]) -> dict:
        if demo:
            raise HTTPException(400, "Settings are read-only in demo mode.")
        conn = get_conn()
        try:
            for key in SETTINGS_FIELDS:
                if key in payload:
                    set_setting(conn, key, payload[key])
            conn.commit()
        finally:
            conn.close()
        return {"ok": True}

    @app.post("/api/setup/secrets")
    def save_secrets(payload: dict[str, str]) -> dict:
        if demo:
            raise HTTPException(400, "Setup is disabled in demo mode.")
        updates = {}
        for key in ("GARMIN_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if key in payload and payload[key] is not None:
                updates[key] = payload[key]
        write_env(updates)
        return {"ok": True}

    @app.post("/api/reset")
    def reset() -> dict:
        if demo:
            raise HTTPException(400, "Demo mode has nothing to reset.")
        clear_env()
        if db_path.exists():
            db_path.unlink()
        uploads_dir = DATA_DIR / "uploads"
        if uploads_dir.exists():
            shutil.rmtree(uploads_dir)
        init_db(db_path)
        return {"ok": True}

    @app.post("/api/sync")
    def trigger_sync(days: int = 365) -> dict:
        if demo:
            raise HTTPException(400, "Demo mode uses synthetic data; there is nothing to sync.")
        from run_coach.garmin.sync import sync_garmin

        secrets = Secrets.load()
        if not secrets.garmin_api_key:
            raise HTTPException(400, "No GARMIN_API_KEY configured yet.")
        with transaction(db_path) as conn:
            result = sync_garmin(conn, api_key=secrets.garmin_api_key, days=days)
            append_sync_log(
                conn,
                source="garmin",
                range_start=result["range"]["start"],
                range_end=result["range"]["end"],
                counts=result["counts"],
                data_gaps=result["data_gaps"],
            )
        return result

    def _strava_upload_path() -> Path:
        return ensure_data_dir() / "uploads" / "activities.csv"

    def _run_strava_import(column_overrides: dict[str, str] | None) -> dict:
        from run_coach.storage.db import get_setting, set_setting
        from run_coach.strava.sync import import_strava_csv

        with transaction(db_path) as conn:
            timezone_name = get_setting(conn, "timezone")
            result = import_strava_csv(
                conn, _strava_upload_path(), timezone_name=timezone_name, column_overrides=column_overrides
            )
            append_sync_log(
                conn, source="strava", range_start=None, range_end=None,
                counts=result["counts"], data_gaps=result["data_gaps"],
            )
            set_setting(conn, "last_strava_import_report", result)
        return result

    @app.post("/api/strava/import")
    async def strava_import(file: UploadFile) -> dict:
        if demo:
            raise HTTPException(400, "Demo mode uses synthetic data; there is nothing to import.")
        from run_coach.strava.importer import inspect_header

        upload_dir = ensure_data_dir() / "uploads"
        upload_dir.mkdir(exist_ok=True)
        dest = _strava_upload_path()
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        header_info = inspect_header(dest)
        if header_info["missing_required_fields"]:
            return {
                "needs_mapping": True,
                "available_headers": header_info["available_headers"],
                "missing_required_fields": header_info["missing_required_fields"],
                "matched_fields": header_info["matched_fields"],
            }
        return _run_strava_import(None)

    @app.post("/api/strava/import-with-mapping")
    def strava_import_with_mapping(payload: dict[str, dict[str, str]]) -> dict:
        if demo:
            raise HTTPException(400, "Demo mode uses synthetic data; there is nothing to import.")
        if not _strava_upload_path().exists():
            raise HTTPException(400, "No uploaded activities.csv found; upload the file again.")
        return _run_strava_import(payload.get("column_mapping", {}))

    @app.get("/api/strava/last-import")
    def strava_last_import() -> dict:
        from run_coach.storage.db import get_setting

        with get_conn() as conn:
            report = get_setting(conn, "last_strava_import_report")
        return {"report": report}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.exception_handler(404)
    async def not_found(_request, _exc):
        return JSONResponse({"error": "not found"}, status_code=404)

    return app
