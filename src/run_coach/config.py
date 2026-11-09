"""Central configuration: app identity, paths, and the .env reader/writer.

Keep APP_NAME as the single place the product name lives, so renaming the
app is a one-line change.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "run-coach"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / f"{APP_NAME.replace('-', '_')}.db"
ENV_PATH = PROJECT_ROOT / ".env"

# Garmin's Personal API documents no per-request date-range cap for range
# endpoints (verified against the published client source, Nov 2026). This
# window is our own precaution so a 365-day backfill can't send one huge
# request; it is not a Garmin-documented limit.
GARMIN_SYNC_CHUNK_DAYS = 30
GARMIN_MAX_HISTORY_DAYS = 365


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. No interpolation, no escaping."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def write_env(updates: dict[str, str], path: Path = ENV_PATH) -> None:
    """Merge `updates` into the .env file, creating it with chmod 600."""
    current = read_env(path)
    current.update({k: v for k, v in updates.items() if v is not None})
    lines = [f"{key}={value}" for key, value in current.items() if value != ""]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


@dataclass(frozen=True)
class Secrets:
    """Everything that must never land in SQLite, logs, or stdout."""

    garmin_api_key: str | None
    anthropic_api_key: str | None
    claude_model: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def load(cls) -> "Secrets":
        env = {**read_env(), **os.environ}
        return cls(
            garmin_api_key=env.get("GARMIN_API_KEY") or None,
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            claude_model=env.get("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL,
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
        )

    def has_claude(self) -> bool:
        return bool(self.anthropic_api_key)

    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)
