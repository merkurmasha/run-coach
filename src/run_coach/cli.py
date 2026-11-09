"""Command-line entry point. `uv run run-coach <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from run_coach.config import APP_NAME, Secrets
from run_coach.storage.db import append_sync_log, get_setting, init_db, transaction


def cmd_init(_args: argparse.Namespace) -> int:
    init_db()
    print(f"{APP_NAME}: database initialized in ./data")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from run_coach.garmin.sync import sync_garmin

    secrets = Secrets.load()
    if not secrets.garmin_api_key:
        print("No GARMIN_API_KEY found in .env. Run the setup wizard first.", file=sys.stderr)
        return 1

    init_db()
    with transaction() as conn:
        result = sync_garmin(conn, api_key=secrets.garmin_api_key, days=args.days)
        append_sync_log(
            conn,
            source="garmin",
            range_start=result["range"]["start"],
            range_end=result["range"]["end"],
            counts=result["counts"],
            data_gaps=result["data_gaps"],
        )

    print(f"Synced Garmin data for {result['range']['start']} to {result['range']['end']}")
    for key, value in result["counts"].items():
        print(f"  {key}: {value}")
    if result["data_gaps"]:
        print(f"  data gaps recorded: {len(result['data_gaps'])} (see dashboard data-gaps panel)")
    return 0


def cmd_import_strava(args: argparse.Namespace) -> int:
    from run_coach.strava.sync import import_strava_csv

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"No such file: {csv_path}", file=sys.stderr)
        return 1

    init_db()
    with transaction() as conn:
        timezone_name = args.timezone or get_setting(conn, "timezone")
        result = import_strava_csv(conn, csv_path, timezone_name=timezone_name)
        append_sync_log(
            conn,
            source="strava",
            range_start=None,
            range_end=None,
            counts=result["counts"],
            data_gaps=result["data_gaps"],
        )

    print(f"Imported {result['counts']['imported']} Strava activities")
    print(f"  skipped as duplicates of Garmin: {result['counts']['skipped_duplicate_of_garmin']}")
    if result["data_gaps"]:
        print(f"  notes: {len(result['data_gaps'])} (see dashboard data-gaps panel)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import threading
    import time
    import webbrowser

    import uvicorn

    from run_coach.web.app import create_app

    if not args.demo:
        init_db()
        secrets = Secrets.load()
        if not secrets.garmin_api_key:
            print(f"{APP_NAME}: no GARMIN_API_KEY in .env yet -- opening the setup wizard.")

    app = create_app(demo=args.demo)
    url = f"http://127.0.0.1:{args.port}/"

    def open_browser() -> None:
        time.sleep(1.0)
        webbrowser.open(url)

    if not args.no_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    mode = "demo" if args.demo else "live"
    print(f"{APP_NAME} ({mode} mode) running at {url}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--demo", action="store_true", help="Run on synthetic data, no keys required.")
    parser.add_argument("--port", type=int, default=8787, help="Port to serve the dashboard on.")
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab automatically.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Self-hosted running insights.")
    _add_serve_args(parser)
    parser.set_defaults(func=cmd_serve)
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Start the dashboard (same as running with no command).")
    _add_serve_args(p_serve)
    p_serve.set_defaults(func=cmd_serve)

    p_init = sub.add_parser("init", help="Create the local SQLite database.")
    p_init.set_defaults(func=cmd_init)

    p_sync = sub.add_parser("sync", help="Sync Garmin data for the configured account.")
    p_sync.add_argument("--days", type=int, default=365, help="Days of history to sync (max 365).")
    p_sync.set_defaults(func=cmd_sync)

    p_strava = sub.add_parser("import-strava", help="Import a Strava bulk-export activities.csv.")
    p_strava.add_argument("csv_path", help="Path to activities.csv from your Strava export.")
    p_strava.add_argument("--timezone", default=None, help="IANA timezone, e.g. Europe/Berlin.")
    p_strava.set_defaults(func=cmd_import_strava)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
