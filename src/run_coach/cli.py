"""Command-line entry point. `uv run run-coach <command>`."""

from __future__ import annotations

import argparse
import sys

from run_coach.config import APP_NAME, Secrets
from run_coach.storage.db import append_sync_log, init_db, transaction


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Self-hosted running insights.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create the local SQLite database.")
    p_init.set_defaults(func=cmd_init)

    p_sync = sub.add_parser("sync", help="Sync Garmin data for the configured account.")
    p_sync.add_argument("--days", type=int, default=365, help="Days of history to sync (max 365).")
    p_sync.set_defaults(func=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
