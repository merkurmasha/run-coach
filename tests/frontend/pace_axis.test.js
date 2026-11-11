"use strict";

// Locks in the "faster goes up" rule for every pace-on-the-y-axis chart:
// chart-pace-trend, chart-efficiency and chart-pb-timeline must all set
// the same y-axis reversal, min:sec tick/tooltip formatting and "faster ↑"
// axis label. A future edit that reverses one chart's axis without the
// others (or that bypasses the shared paceAxis flag) fails this test.

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const { STATUS, STATS, progressFor, RECOMMENDATIONS, ACTIVITIES, STRAVA_LAST_IMPORT, SYNC_STATUS } = require("./fixtures");

const STATIC_DIR = path.resolve(__dirname, "../../src/run_coach/web/static");

// This fixture's pace_at_hr_trend has no non-null pace values, which makes
// renderEfficiencyTrendChart render a "not enough data" message instead of
// a chart -- not useful for checking its axis config. Give it one real
// data point so the chart actually gets built.
function progressWithEfficiencyData(range) {
  const progress = progressFor(range);
  progress.pace_at_hr_trend = [
    { week: "2026-W39", n: 9, pace_at_reference_hr_s_per_km: 390.0 },
    { week: "2026-W40", n: 10, pace_at_reference_hr_s_per_km: 380.0 },
  ];
  return progress;
}

function routeFor(url) {
  const u = new URL(url, "http://localhost/");
  if (u.pathname === "/api/status") return STATUS;
  if (u.pathname === "/api/stats") return STATS;
  if (u.pathname === "/api/progress") return progressWithEfficiencyData(u.searchParams.get("range") || "4w");
  if (u.pathname === "/api/recommendations") return RECOMMENDATIONS;
  if (u.pathname === "/api/activities") return ACTIVITIES;
  if (u.pathname === "/api/strava/last-import") return STRAVA_LAST_IMPORT;
  if (u.pathname === "/api/sync/status") return SYNC_STATUS;
  throw new Error(`unstubbed fetch: ${url}`);
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitUntil(conditionFn, timeoutMs = 4000, stepMs = 25) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (conditionFn()) return true;
    await sleep(stepMs);
  }
  return conditionFn();
}

async function run() {
  const html = fs.readFileSync(path.join(STATIC_DIR, "index.html"), "utf8");
  const appJs = fs.readFileSync(path.join(STATIC_DIR, "js", "app.js"), "utf8");

  const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/", pretendToBeVisual: true });
  const { window } = dom;

  window.addEventListener("error", () => {});
  window.addEventListener("unhandledrejection", () => {});
  window.alert = () => {};

  // Records every chart built, keyed by the canvas id it was attached to,
  // so the config passed to Chart.js can be inspected directly instead of
  // re-deriving it by re-rendering a real canvas.
  const configsById = {};
  class RecordingChart {
    constructor(canvas, config) {
      configsById[canvas.id] = config;
    }
    destroy() {}
  }
  window.Chart = RecordingChart;

  window.fetch = async (url) => {
    let body;
    try {
      body = routeFor(url);
    } catch (e) {
      return { ok: false, status: 404, statusText: "Not Found", json: async () => ({ error: e.message }) };
    }
    return { ok: true, status: 200, json: async () => body };
  };

  window.eval(appJs);

  await waitUntil(
    () =>
      !window.document.getElementById("dashboard-view").classList.contains("hidden") &&
      configsById["chart-efficiency"] != null
  );
  await sleep(200);

  const failures = [];

  const PACE_CHARTS = ["chart-pace-trend", "chart-efficiency", "chart-pb-timeline"];
  const NON_PACE_CHARTS = ["chart-weekly-distance", "chart-long-run", "chart-hr-zones"];

  for (const id of PACE_CHARTS) {
    const config = configsById[id];
    if (!config) {
      failures.push(`${id}: chart was never built`);
      continue;
    }
    const y = config.options.scales.y;
    if (y.reverse !== true) {
      failures.push(`${id}: y-axis must set reverse: true so faster (lower s/km) draws higher, got ${y.reverse}`);
    }
    if (!y.title || !y.title.display || !/faster\s*↑/.test(y.title.text || "")) {
      failures.push(`${id}: y-axis must show a "faster ↑" axis label, got ${JSON.stringify(y.title)}`);
    }
    if (typeof y.ticks.callback !== "function") {
      failures.push(`${id}: y-axis ticks must be formatted (min:sec/km)`);
    } else if (y.ticks.callback(390) !== "6:30/km") {
      failures.push(`${id}: y-axis tick for 390s should read "6:30/km", got "${y.ticks.callback(390)}"`);
    }
    const tooltipLabel = config.options.plugins.tooltip.callbacks.label;
    if (typeof tooltipLabel !== "function") {
      failures.push(`${id}: tooltip must format pace values in min:sec/km, not raw seconds`);
    } else {
      const formatted = tooltipLabel({ dataset: { label: "" }, parsed: { y: 390 } });
      if (!formatted.includes("6:30/km")) {
        failures.push(`${id}: tooltip for 390s should include "6:30/km", got "${formatted}"`);
      }
    }
  }

  for (const id of NON_PACE_CHARTS) {
    const config = configsById[id];
    if (!config) continue; // not every fixture guarantees every chart renders
    const y = config.options.scales.y;
    if (y.reverse) {
      failures.push(`${id}: non-pace chart should not have a reversed y-axis`);
    }
  }

  if (failures.length > 0) {
    console.error("FAIL\n" + failures.map((f) => ` - ${f}`).join("\n"));
    process.exit(1);
  }
  console.log(`PASS (${PACE_CHARTS.length} pace charts checked for consistent "faster ↑" reversed axis)`);
}

run().catch((e) => {
  console.error("FAIL (test harness error):", e);
  process.exit(1);
});
