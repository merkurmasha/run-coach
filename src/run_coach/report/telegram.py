"""Sends the weekly report to Telegram as formatted HTML. The bot only ever
messages the one chat ID configured in .env -- there is no way to target
any other chat from this code path.
"""

from __future__ import annotations

from html import escape

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def format_report_html(report: dict) -> str:
    next_week = report.get("next_week", {})
    key_results = "\n".join(f"  • {escape(kr)}" for kr in next_week.get("key_results", []))
    fallbacks = "\n".join(f"  • {escape(fs)}" for fs in next_week.get("fallback_sessions", []))

    return (
        "<b>Weekly running report</b>\n\n"
        f"<b>Highlight:</b> {escape(report.get('highlight', ''))}\n"
        f"<b>Watch out:</b> {escape(report.get('watch_out', ''))}\n\n"
        f"<b>Next week's objective:</b> {escape(next_week.get('objective', ''))}\n"
        f"<b>Key results:</b>\n{key_results}\n\n"
        f"<b>Fallback sessions:</b>\n{fallbacks}"
    )


def send_telegram_report(report: dict, bot_token: str, chat_id: str) -> None:
    text = format_report_html(report)
    response = requests.post(
        TELEGRAM_API.format(token=bot_token),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    response.raise_for_status()
