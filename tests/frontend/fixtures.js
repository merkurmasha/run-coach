"use strict";

// Synthetic API responses shaped like the real /api/* endpoints, used to
// drive app.js headlessly. None of these numbers come from a real account;
// they only need to match the shapes the backend actually returns (see
// run_coach/web/app.py and the metrics/ modules) closely enough to exercise
// every render path, including the ones that need non-empty data.

const STATUS = {
  app_name: "run-coach",
  demo: false,
  setup_complete: true,
  has_claude: true,
  has_telegram: false,
  settings: {
    target_pace_s_per_km: 390,
    race_distance_m: 21097.5,
    race_date: "2026-02-14",
    runs_per_week: 4,
    follows_watch_plan: false,
    cycle_mode: "garmin",
    special_conditions_text: "sample note",
    timezone: "UTC",
    units: "km",
    reference_hr: null,
    telegram_enabled: null,
  },
};

const STATS = {
  n_activities_total: 42,
  n_running_activities: 38,
  progress: {
    monthly: [{ month: "2026-10", distance_km: 80.0, runs: 12, avg_pace_s_per_km: 390.0, avg_pace: "6:30/km" }],
    personal_bests: {
      "5k": { moving_time_s: 1500.0, distance_m: 5000.0, pace_s_per_km: 300.0, date: "2026-09-01" },
      "10k": { moving_time_s: 3200.0, distance_m: 10000.0, pace_s_per_km: 320.0, date: "2026-10-01" },
      half_marathon: null,
    },
    race_predictions: {
      "5k": { seconds: 1500.0, is_measured: true, source: "5k" },
      "10k": { seconds: 3200.0, is_measured: true, source: "10k" },
      half_marathon: { seconds: 7100.0, is_measured: false, source: "10k" },
      marathon: { seconds: 14800.0, is_measured: false, source: "10k" },
    },
  },
  aerobic_efficiency: { monthly_pace_at_reference_hr: [{ month: "2026-10", n: 10, pace_at_reference_hr_s_per_km: 385.0, reference_hr: 150.0 }] },
  load: {
    weekly_volume: [{ week: "2026-W40", distance_km: 20.0, runs: 3 }],
    hr_zone_distribution: { available: true, n_activities: 10, zones: { "1": 20.0, "2": 40.0, "3": 25.0, "4": 10.0, "5": 5.0 } },
  },
  recovery: {
    sleep_duration_s: { recent_avg: 25000, baseline_avg: 24500, n_recent: 7, n_baseline: 28, delta: 500 },
    sleep_score: { recent_avg: 78, baseline_avg: 75, n_recent: 7, n_baseline: 28, delta: 3 },
    hrv_ms: { recent_avg: null, baseline_avg: null, n_recent: 0, n_baseline: 0, delta: null },
    resting_hr: { recent_avg: null, baseline_avg: null, n_recent: 0, n_baseline: 0, delta: null },
  },
  patterns: {
    cycle_phase: {
      available: true,
      phases: {
        follicular: { avg_pace_s_per_km: 385.0, avg_hr: 148, n: 10 },
        luteal: { avg_pace_s_per_km: 400.0, avg_hr: 152, n: 8 },
      },
    },
    special_conditions: "sample note",
  },
  standing: {
    current_form_estimates: {
      window_weeks: 8,
      predictions: {
        "5k": { seconds: 1500.0, is_measured: true, source: "5k" },
        "10k": { seconds: 3200.0, is_measured: true, source: "10k" },
        half_marathon: { seconds: 7100.0, is_measured: false, source: "10k" },
        marathon: { seconds: 14800.0, is_measured: false, source: "10k" },
      },
    },
    gap_to_target_pace: { avg_pace_s_per_km_last_4w: 400.0, target_pace_s_per_km: 390.0, gap_s_per_km: 10.0 },
    weeks_until_race: 6,
    weekly_volume_vs_average: { this_week_km: 18.0, avg_4w_km: 16.0, avg_12w_km: 15.0, is_spike: false, spike_threshold: 1.3 },
    consistency: { window_weeks: 8, avg_runs_per_week: 3.2, weeks_with_at_least_one_run: 7, weeks_with_no_runs: 1 },
    long_run_progression: [{ week: "2026-W39", longest_run_km: 12.0 }, { week: "2026-W40", longest_run_km: 14.0 }],
    recovery: {
      sleep_duration_s: { recent_avg: 25000, baseline_avg: 24500, n_recent: 7, n_baseline: 28, delta: 500 },
      sleep_score: { recent_avg: 78, baseline_avg: 75, n_recent: 7, n_baseline: 28, delta: 3 },
      hrv_ms: { recent_avg: null, baseline_avg: null, n_recent: 0, n_baseline: 0, delta: null },
      resting_hr: { recent_avg: null, baseline_avg: null, n_recent: 0, n_baseline: 0, delta: null },
    },
    status: {
      status: "on_track",
      rule: "sample rule text",
      avg_runs_per_week_last_4w: 3.5,
      avg_pace_s_per_km_last_4w: 400.0,
    },
    follows_watch_plan: false,
  },
  goals: { target_pace_s_per_km: 390, race_distance_m: 21097.5, race_date: "2026-02-14", runs_per_week: 4, follows_watch_plan: false },
  data_gaps: ["sample: synthetic data gap for the smoke test"],
};

function progressFor(range) {
  return {
    range,
    range_progress: { current: { distance_km: 20.0, runs: 3, avg_pace_s_per_km: 400.0, longest_run_km: 10.0 }, previous: { distance_km: 18.0, runs: 3, avg_pace_s_per_km: 410.0, longest_run_km: 9.0 }, delta: { distance_km: 2.0, runs: 0, longest_run_km: 1.0, avg_pace_s_per_km: -10.0 } },
    weekly_distance: [{ week: "2026-W39", distance_km: 15.0 }, { week: "2026-W40", distance_km: 20.0 }],
    pace_trend: [{ week: "2026-W39", avg_pace_s_per_km: 410.0, rolling_avg_pace_s_per_km: 405.0 }, { week: "2026-W40", avg_pace_s_per_km: 400.0, rolling_avg_pace_s_per_km: 402.0 }],
    pace_at_hr_trend: [{ week: "2026-W40", n: 1, pace_at_reference_hr_s_per_km: null, reason: "not enough data yet" }],
    personal_bests_timeline: [{ distance_label: "5k", date: "2026-09-01", moving_time_s: 1500.0, pace_s_per_km: 300.0 }],
    race_markers: [{ id: "garmin:1", date: "2026-11-08", activity_type: "Run", distance_km: 10.2, pace_s_per_km: 330.0, name: "Sample 10K" }],
    race_predictions: {
      "5k": { seconds: 1500.0, is_measured: true, source: "5k" },
      "10k": { seconds: 3200.0, is_measured: true, source: "10k" },
      half_marathon: { seconds: 7100.0, is_measured: false, source: "10k" },
      marathon: { seconds: 14800.0, is_measured: false, source: "10k" },
    },
    hr_coverage: { runs_with_hr: 10, total_runs: 38, strava_with_hr: 4, strava_total: 30 },
  };
}

const RECOMMENDATIONS = {
  generated_at: "2026-11-01T00:00:00Z",
  recommendations: [{ evidence: "strong", text: "Sample recommendation text.", rationale: "Sample rationale." }],
  stats_summary: null,
};

const ACTIVITIES = {
  activities: [
    { id: "garmin:1", date: "2026-11-08", activity_type: "Run", distance_km: 10.2, is_race: false, moving_time_s: 3300, race_name: null },
    { id: "strava:1", date: "2026-11-05", activity_type: "Run", distance_km: 8.0, is_race: false, moving_time_s: 2900, race_name: null },
    { id: "strava:2", date: "2026-11-02", activity_type: "Run", distance_km: 5.0, is_race: false, moving_time_s: 1700, race_name: null },
  ],
};

const STRAVA_LAST_IMPORT = { report: null };

module.exports = { STATUS, STATS, progressFor, RECOMMENDATIONS, ACTIVITIES, STRAVA_LAST_IMPORT };
