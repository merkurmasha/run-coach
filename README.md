# run-coach

A self-hosted running-insights dashboard. It combines your Garmin data,
an optional Strava history, and your own personal context into one
dashboard with evidence-labelled recommendations and a weekly report.

You run it on your own computer with your own API keys. There is no
hosted version, no account, and no server anywhere that collects your
data. Not affiliated with Garmin or Strava.

The product name is "run-coach" everywhere, but it's one constant:
`APP_NAME` in `src/run_coach/config.py`. Change it there to rename the
whole app.

**Status: early version.** This has only been run end-to-end against
one real Garmin account so far, and real-world Strava exports and
long-running schedules haven't been battle-tested. Garmin's Personal
API response shapes aren't fully documented, so some fields are
best-effort guesses — check the dashboard's data-gaps panel after your
first sync. Issues and PRs welcome.

## Try it with no keys at all

```
uv sync
uv run run-coach --demo
```

This opens a browser tab with the full dashboard running on a synthetic
270-day dataset, generated fresh each time you start it. Nothing real is
read or written. Use this to see what the app does before connecting a
real Garmin account, or to take screenshots.

## Real setup

1. Get a Garmin Personal API key from
   [connect.garmin.com/app/settings/personalApiToken](https://connect.garmin.com/app/settings/personalApiToken).
   Garmin issues these for a fixed period of your choosing, from 30 days
   up to a year — pick what you're comfortable with, and plan to generate
   a new one before it expires (the dashboard keeps working on data
   already synced; a new sync just needs a valid key).
2. Run the app and open the setup wizard:

   ```
   uv sync
   uv run run-coach
   ```

   A browser tab opens automatically. The wizard asks for the Garmin key
   (required), an optional Claude API key, your goals, optional cycle
   and condition context, an optional Strava export upload, and your
   timezone/units. Everything except the Garmin key is skippable.
3. The wizard triggers your first sync automatically. After that:

   ```
   uv run run-coach sync --days 365       # re-sync manually any time
   uv run run-coach import-strava path/to/activities.csv
   uv run run-coach report --weeks 8                 # needs ANTHROPIC_API_KEY
   uv run run-coach report --weeks 8 --send-telegram # also needs the Telegram setup
   ```

Data lives only in `./data` (gitignored). Secrets live only in `.env`
(written by the wizard at `chmod 600`, never logged or printed).

## What stays local, and what goes to Claude

- **Garmin and Strava data, and everything derived from it** (activities,
  sleep, HRV, resting heart rate, cycle tracking, your special-conditions
  text, computed stats) stays in the local SQLite database in `./data`.
  Nothing is uploaded anywhere by default.
- **When you click "Regenerate" on the recommendations panel, or run
  `report`**, the app sends Claude a small JSON of *aggregated statistics
  only* — monthly totals, personal bests, pace-at-heart-rate figures,
  recovery baselines, sample sizes — never raw activity-by-activity data,
  and never your name or any identifier. The system prompt instructs
  Claude to never invent a number, and a local validator strips any
  sentence whose numbers don't actually appear in that JSON before you
  see it.
- **The Garmin Personal API key is yours and for your own data only** —
  it is not a general Garmin Connect credential, and this app never asks
  for your Garmin password. The key is exchanged for a short-lived bearer
  token on each sync; there's no refresh token, so an expired or revoked
  key just means the next sync fails cleanly (check the data-gaps panel).
- **This is not medical advice.** Recommendations and reports never
  diagnose anything. If you've logged a special condition that sounds
  like pain or an injury, the app is instructed to suggest seeing a
  qualified professional, not to give you a training workaround for it.

## Scheduling the weekly report

`run-coach report --weeks 8 --send-telegram` is a plain CLI command, so
any scheduler that can run a shell command can run it. The laptop has to
actually be awake at the scheduled time — neither launchd nor cron will
wake a sleeping Mac, and a missed run just doesn't happen (there's no
catch-up).

**macOS launchd** (recommended on a Mac — survives reboots, and `RunAtLoad`
with `StartCalendarInterval` is the native way to do this):

Create `~/Library/LaunchAgents/com.run-coach.weekly-report.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.run-coach.weekly-report</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>uv</string>
    <string>run</string>
    <string>run-coach</string>
    <string>report</string>
    <string>--weeks</string><string>8</string>
    <string>--send-telegram</string>
  </array>
  <key>WorkingDirectory</key><string>/absolute/path/to/run-coach</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/absolute/path/to/run-coach/data/report.log</string>
  <key>StandardErrorPath</key><string>/absolute/path/to/run-coach/data/report.log</string>
</dict>
</plist>
```

Then:

```
launchctl load ~/Library/LaunchAgents/com.run-coach.weekly-report.plist
```

**cron** (simpler, works on macOS and Linux, but has no concept of "the
laptop was asleep, catch up now"):

```
# Mondays at 08:00
0 8 * * 1 cd /absolute/path/to/run-coach && /usr/bin/env uv run run-coach report --weeks 8 --send-telegram >> data/report.log 2>&1
```

## Architecture

- **Python 3.12 + uv**, FastAPI backend, SQLite storage, plain HTML/JS
  frontend with Chart.js vendored locally (`src/run_coach/web/static/vendor`)
  — no CDN, no build step.
- `src/run_coach/garmin/` wraps the official
  [`garmin-connect-personal-api-python`](https://github.com/garmin/connect-personal-api-python)
  client: date-range chunking and defensive field extraction, since
  Garmin doesn't publish the Personal API's response schemas. A missing
  or unexpectedly-shaped field is recorded in `data_gaps`, never a crash.
- `src/run_coach/strava/` parses a Strava bulk-export `activities.csv`
  by candidate column-name matching (headers drift across export
  versions and locales), explicitly drops any description/note column,
  and deduplicates against Garmin by start time.
- `src/run_coach/metrics/` computes everything the dashboard shows —
  nothing is computed client-side or by Claude.
- `src/run_coach/recommendations/` and `src/run_coach/report/` are the
  only two places that call the Claude API, both via a forced tool call
  (never free-text parsing) and both validated against the stats JSON
  before being shown or sent.
- `src/run_coach/demo/` generates a synthetic dataset for `--demo`.

## Development

```
uv sync
uv run pytest
```

Tests use synthetic fixtures and make no network calls. Run
`scripts/check-secrets.sh` before committing (or wire it up once with
`git config core.hooksPath scripts/hooks` to run automatically).

## License

MIT — see `LICENSE`.
