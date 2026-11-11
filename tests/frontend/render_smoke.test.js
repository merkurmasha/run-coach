"use strict";

// Headless smoke test for app.js: drives the real dashboard boot() sequence
// in jsdom against synthetic (fabricated, not-real-user) API fixtures, and
// fails if anything throws uncaught or any section renders a `.render-error`
// card. This is the kind of test that would have caught the
// renderEfficiencyTrendChart "Cannot set properties of null" bug: that bug
// only showed up once real data had zero HR-tagged runs, at which point the
// buggy `.parentElement.querySelector(".chart-wrap")` lookup returned null
// and the whole boot() sequence died right there, well before relevant
// manual tests would be re-run for the one specific empty/zero-HR data
// shape that triggers it.

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const { STATUS, STATS, progressFor, RECOMMENDATIONS, ACTIVITIES, STRAVA_LAST_IMPORT, SYNC_STATUS } = require("./fixtures");

const STATIC_DIR = path.resolve(__dirname, "../../src/run_coach/web/static");

function routeFor(url) {
  const u = new URL(url, "http://localhost/");
  if (u.pathname === "/api/status") return STATUS;
  if (u.pathname === "/api/stats") return STATS;
  if (u.pathname === "/api/progress") return progressFor(u.searchParams.get("range") || "4w");
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

  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.error || e.message));
  window.addEventListener("unhandledrejection", (e) => errors.push(e.reason));
  window.alert = (msg) => errors.push(new Error(`window.alert() called unexpectedly: ${msg}`));

  class FakeChart {
    constructor(canvas, config) {
      this.canvas = canvas;
      this.config = config;
    }
    destroy() {}
  }
  window.Chart = FakeChart;

  // Captured before boot() runs: a "not enough data" render replaces this
  // node's children (including the canvas itself), so the canvas can't be
  // used to re-find its own wrapper afterwards -- the wrapper reference has
  // to be grabbed while the canvas is still there.
  const efficiencyWrap = window.document.getElementById("chart-efficiency").closest(".chart-wrap");

  window.fetch = async (url, _init) => {
    let body;
    try {
      body = routeFor(url);
    } catch (e) {
      return { ok: false, status: 404, statusText: "Not Found", json: async () => ({ error: e.message }) };
    }
    return { ok: true, status: 200, json: async () => body };
  };

  // app.js is a plain IIFE (no module exports), so it's executed the same
  // way a <script src="app.js"> tag would run it: eval'd directly against
  // this window, after the stubs above are in place.
  window.eval(appJs);

  const settled = await waitUntil(
    () =>
      !window.document.getElementById("dashboard-view").classList.contains("hidden") ||
      window.document.body.querySelector(".render-error") != null
  );
  if (!settled) errors.push(new Error("boot() never finished: dashboard-view stayed hidden"));

  // Let any still-in-flight microtasks (e.g. renderRaceTagList's own fetch)
  // resolve before asserting.
  await sleep(200);

  const failures = [];
  if (errors.length > 0) {
    for (const e of errors) failures.push(`uncaught: ${e && e.stack ? e.stack : e}`);
  }

  const errorCards = [...window.document.querySelectorAll(".render-error")];
  for (const card of errorCards) failures.push(`render-error card present: ${card.textContent}`);

  // This fixture's pace_at_hr_trend has zero runs with HR data (the real
  // shape that triggered the original bug: a Spanish Strava export where
  // almost no rows had heart-rate columns populated), so the chart-wrap
  // must contain an explanatory "not enough data" message -- not be
  // silently left empty.
  if (!efficiencyWrap || efficiencyWrap.textContent.trim().length === 0) {
    failures.push("chart-efficiency's chart-wrap is empty (should show a not-enough-data message for zero-HR-data runs)");
  }

  const nonEmptyChecks = [
    ["progress-tiles", (n) => n.children.length > 0],
    ["chart-weekly-distance", (n) => n != null],
    ["race-predictions-table", (n) => n.rows.length > 1],
    ["standing-status", (n) => n.textContent.trim().length > 0],
    ["standing-tiles", (n) => n.children.length > 0],
    ["gaps-list", (n) => n.textContent.trim().length > 0],
    ["recs-list", (n) => n.textContent.trim().length > 0],
    ["patterns-cycle", (n) => n.textContent.trim().length > 0],
    ["glance-grid", (n) => n.children.length === 3],
    ["race-tag-list", (n) => n.textContent.trim().length > 0],
    ["hr-zone-wrap", (n) => n.textContent.trim().length > 0 || n.querySelector("canvas") != null],
    ["sync-status-table", (n) => n.rows.length > 1],
  ];
  for (const [id, check] of nonEmptyChecks) {
    const node = window.document.getElementById(id);
    if (!node) {
      failures.push(`missing element #${id}`);
      continue;
    }
    if (!check(node)) failures.push(`#${id} rendered empty`);
  }

  // Exercise the range switcher too (refreshProgress path), since it's a
  // second, separate entry point into the same chart renderers.
  const rangeBtn = window.document.querySelector('#range-switcher button[data-range="1y"]');
  rangeBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(300);
  const errorCardsAfterRangeSwitch = [...window.document.querySelectorAll(".render-error")];
  for (const card of errorCardsAfterRangeSwitch) failures.push(`render-error card present after range switch: ${card.textContent}`);

  // The known race date (2026-11-08) isn't the most recent activity in
  // the fixture, so this only passes if renderRaceTagList's own pin-to-top
  // logic actually ran, not just by accident of fixture ordering.
  const firstRaceRow = window.document.querySelector("#race-tag-list .race-tag-row");
  if (!firstRaceRow || !firstRaceRow.textContent.includes("2026-11-08")) {
    failures.push(`race-tag-list's first row should be the known race date (2026-11-08), got: ${firstRaceRow ? firstRaceRow.textContent : "(none)"}`);
  }

  if (failures.length > 0) {
    console.error("FAIL\n" + failures.map((f) => ` - ${f}`).join("\n"));
    process.exit(1);
  }
  console.log(`PASS (${nonEmptyChecks.length} sections checked non-empty, 0 render errors, 0 uncaught exceptions)`);
}

run().catch((e) => {
  console.error("FAIL (test harness error):", e);
  process.exit(1);
});
