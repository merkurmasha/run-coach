# run-coach

A self-hosted running-insights dashboard. You run it on your own machine with
your own API keys; nothing is hosted for you and nothing leaves your
computer except the aggregated numbers you explicitly send to Claude for
recommendations. Not affiliated with Garmin or Strava.

**Status: under construction.** This README grows with each phase; see
`git log` for what's landed so far.

## Quickstart (coming together over the next few phases)

```
uv sync
uv run run-coach init   # create ./data/run_coach.db
uv run run-coach sync --days 365   # requires GARMIN_API_KEY in .env
```

More to come: the setup wizard, the dashboard, demo mode, recommendations,
and the weekly Telegram report.
