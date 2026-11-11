(() => {
  "use strict";

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmtKm = (v) => (v == null ? "—" : `${v.toFixed(1)} km`);
  const fmtPaceSec = (s) => {
    if (s == null) return "—";
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return `${m}:${String(sec).padStart(2, "0")}/km`;
  };
  const fmtTime = (s) => {
    if (s == null) return "—";
    s = Math.round(s);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  };
  const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    Object.entries(props).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else node.setAttribute(k, v);
    });
    children.forEach((c) => node.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return node;
  };

  // ---------- theme ----------
  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }
  function initThemeToggle() {
    let saved = null;
    try { saved = localStorage.getItem("run-coach-theme"); } catch (e) { /* ignore */ }
    applyTheme(saved);
    const btn = el("button", { id: "theme-toggle", title: "Toggle theme" }, ["◐"]);
    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      const next = current === "dark" ? "light" : current === "light" ? null : "dark";
      applyTheme(next);
      try {
        if (next) localStorage.setItem("run-coach-theme", next);
        else localStorage.removeItem("run-coach-theme");
      } catch (e) { /* ignore */ }
    });
    return btn;
  }

  // ---------- API ----------
  const SYNC_TIMEOUT_MS = 120000; // generous: a full history sync makes many sequential Garmin calls

  // A plain fetch() has no timeout of its own, so a request that never
  // gets a response (dead network, a server stuck mid-sync) leaves the
  // caller's "Syncing…" button text stuck forever with nothing to tell
  // the user why. This aborts the client-side wait after `timeoutMs`;
  // the server-side work may well still finish on its own (there's no
  // cross-process cancellation here), and a later /api/sync/status poll
  // picks up however it actually ended.
  function fetchWithTimeout(url, init, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer));
  }

  // Every call throws on a non-2xx response, carrying the server's own
  // detail message, so a failure is never silently swallowed into an empty
  // or "not enough data" UI state (see api-root-cause notes in app.py).
  async function asJson(responsePromise) {
    const r = await responsePromise;
    let body = null;
    try {
      body = await r.json();
    } catch (e) { /* non-JSON body, fall through to status text below */ }
    if (!r.ok) {
      const detail = (body && (body.detail || body.error)) || r.statusText || `HTTP ${r.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  const api = {
    status: () => asJson(fetch("/api/status")),
    stats: () => asJson(fetch("/api/stats")),
    recommendations: () => asJson(fetch("/api/recommendations")),
    generateRecommendations: () => asJson(fetch("/api/recommendations/generate", { method: "POST" })),
    saveSettings: (payload) => asJson(fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })),
    saveSecrets: (payload) => asJson(fetch("/api/setup/secrets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })),
    sync: () => asJson(fetchWithTimeout("/api/sync", { method: "POST" }, SYNC_TIMEOUT_MS)),
    syncStatus: () => asJson(fetch("/api/sync/status")),
    reset: () => asJson(fetch("/api/reset", { method: "POST" })),
    testClaude: () => asJson(fetch("/api/claude/test", { method: "POST" })),
    saveClaudeKey: (apiKey) =>
      asJson(fetch("/api/settings/claude-key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey }) })),
    saveGarminKey: (apiKey) =>
      asJson(fetch("/api/settings/garmin-key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey }) })),
    importStrava: (file) => {
      const form = new FormData();
      form.append("file", file);
      return asJson(fetch("/api/strava/import", { method: "POST", body: form }));
    },
    importStravaWithMapping: (columnMapping) =>
      asJson(fetch("/api/strava/import-with-mapping", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ column_mapping: columnMapping }) })),
    lastStravaImport: () => asJson(fetch("/api/strava/last-import")),
    progress: (range) => asJson(fetch(`/api/progress?range=${encodeURIComponent(range)}`)),
    activities: (range) => asJson(fetch(`/api/activities?range=${encodeURIComponent(range)}`)),
    setRace: (activityId, isRace, raceName) =>
      asJson(fetch(`/api/activities/${encodeURIComponent(activityId)}/race`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_race: isRace, race_name: raceName || null }) })),
  };

  const RANGE_LABELS = { "7d": "last 7 days", "4w": "last 4 weeks", "3m": "last 3 months", "1y": "last year", all: "all time" };

  function isoWeekKey(dateStr) {
    const d = new Date(dateStr + "T00:00:00Z");
    const dayNum = (d.getUTCDay() + 6) % 7; // Mon=0..Sun=6
    d.setUTCDate(d.getUTCDate() - dayNum + 3); // nearest Thursday
    const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    const diffWeeks = Math.round((d - firstThursday) / (7 * 24 * 3600 * 1000));
    return `${d.getUTCFullYear()}-W${String(diffWeeks + 1).padStart(2, "0")}`;
  }

  // ---------- wizard ----------
  const WIZARD_STEPS = 6;
  let wizardStep = 0;
  let wizardStravaFile = null;

  function showWizardStep(i) {
    document.querySelectorAll(".wizard-step").forEach((n) => n.classList.add("hidden"));
    document.querySelector(`.wizard-step[data-step="${i}"]`).classList.remove("hidden");
    document.querySelectorAll("#wizard-progress span").forEach((n, idx) => n.classList.toggle("done", idx <= i));
    document.getElementById("wizard-back").style.visibility = i === 0 ? "hidden" : "visible";
    document.getElementById("wizard-next").textContent = i === WIZARD_STEPS - 1 ? "Finish" : "Next";
    document.getElementById("wizard-skip").classList.toggle("hidden", i === 0);
  }

  async function finishWizard() {
    const secretsPayload = {
      GARMIN_API_KEY: document.getElementById("garmin_key").value.trim(),
      ANTHROPIC_API_KEY: document.getElementById("anthropic_key").value.trim(),
      TELEGRAM_BOT_TOKEN: document.getElementById("telegram_token").value.trim(),
      TELEGRAM_CHAT_ID: document.getElementById("telegram_chat").value.trim(),
    };
    await api.saveSecrets(secretsPayload);

    const paceText = document.getElementById("target_pace").value.trim();
    let targetPaceS = null;
    if (/^\d+:\d{2}$/.test(paceText)) {
      const [m, s] = paceText.split(":").map(Number);
      targetPaceS = m * 60 + s;
    }

    const settingsPayload = {
      target_pace_s_per_km: targetPaceS,
      race_distance_m: document.getElementById("race_distance").value ? Number(document.getElementById("race_distance").value) : null,
      race_date: document.getElementById("race_date").value || null,
      runs_per_week: Number(document.getElementById("runs_per_week").value || 4),
      follows_watch_plan: document.getElementById("follows_watch_plan").checked,
      cycle_mode: document.getElementById("cycle_mode").value,
      special_conditions_text: document.getElementById("has_conditions").checked
        ? document.getElementById("conditions_text").value.trim()
        : null,
      timezone: document.getElementById("timezone").value.trim() || "UTC",
      units: document.getElementById("units").value,
    };
    await api.saveSettings(settingsPayload);

    if (wizardStravaFile) {
      try {
        const result = await api.importStrava(wizardStravaFile);
        if (result && result.needs_mapping) {
          alert(
            "Your Strava export's column headers weren't recognized automatically. " +
            "Setup will continue without it — finish the import from the Settings section on the dashboard, " +
            "where you can map the columns by hand."
          );
        }
      } catch (e) {
        alert("Strava import failed: " + e.message + "\n\nSetup will continue; you can retry the import from the Settings section on the dashboard.");
      }
    }

    document.getElementById("wizard-next").textContent = "Syncing…";
    document.getElementById("wizard-next").disabled = true;
    try {
      await api.sync();
    } catch (e) { /* surfaced on dashboard's data-gaps panel instead of blocking here */ }

    location.reload();
  }

  function initWizard() {
    const progress = document.getElementById("wizard-progress");
    for (let i = 0; i < WIZARD_STEPS; i++) progress.appendChild(el("span"));
    showWizardStep(0);

    document.getElementById("cycle_mode").addEventListener("change", (e) => {
      document.getElementById("cycle_manual_fields").classList.toggle("hidden", e.target.value !== "manual");
    });
    document.getElementById("has_conditions").addEventListener("change", (e) => {
      document.getElementById("conditions_text_field").classList.toggle("hidden", !e.target.checked);
    });
    document.getElementById("strava_file").addEventListener("change", (e) => {
      wizardStravaFile = e.target.files[0] || null;
    });

    document.getElementById("wizard-back").addEventListener("click", () => {
      if (wizardStep > 0) { wizardStep--; showWizardStep(wizardStep); }
    });
    document.getElementById("wizard-skip").addEventListener("click", () => {
      if (wizardStep < WIZARD_STEPS - 1) { wizardStep++; showWizardStep(wizardStep); }
      else finishWizard();
    });
    document.getElementById("wizard-next").addEventListener("click", () => {
      if (wizardStep === 0 && !document.getElementById("garmin_key").value.trim()) {
        alert("A Garmin API key is required to continue (everything after this step is optional).");
        return;
      }
      if (wizardStep < WIZARD_STEPS - 1) { wizardStep++; showWizardStep(wizardStep); }
      else finishWizard();
    });
  }

  // ---------- dashboard: tiles ----------
  function statTile(label, value, detail, methodText) {
    const labelNode = el("div", { class: "label" }, [label]);
    if (methodText) {
      const m = el("span", { class: "method" }, ["?", el("span", { class: "tooltip" }, [methodText])]);
      labelNode.appendChild(m);
    }
    return el("div", { class: "card stat-tile" }, [
      labelNode,
      el("div", { class: "value" }, [value]),
      detail ? el("div", { class: "detail" }, [detail]) : "",
    ]);
  }

  // Charts are re-created on every range change, so always destroy the
  // previous instance on a canvas before creating a new one.
  const chartInstances = {};
  function makeChart(canvasId, config) {
    if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    chartInstances[canvasId] = new Chart(canvas, config);
    return chartInstances[canvasId];
  }

  // The canvas for a chart is always the direct child of its ".chart-wrap"
  // container (see index.html), so the wrap is the canvas's own closest
  // ancestor with that class -- not, as an earlier version of this file
  // assumed, a *sibling* of the canvas reached via parentElement once more.
  function chartWrap(canvasId) {
    const canvas = document.getElementById(canvasId);
    return canvas ? canvas.closest(".chart-wrap") : null;
  }

  // Every render*() function below is wired up through one of these two
  // wrappers so that a bug or missing-data surprise in one section can
  // never take down sections rendered after it: the error is caught,
  // logged, and shown as a small card in that section's own place instead
  // of propagating out of boot()/refreshProgress() and aborting everything
  // still queued after it.
  function errorCardInto(target, label, err) {
    console.error(`[render: ${label}]`, err);
    if (!target) return;
    target.innerHTML = `<div class="card render-error">Couldn't render "${escapeHtml(label)}": ${escapeHtml((err && err.message) || String(err))}</div>`;
  }
  function safeRenderChart(label, canvasId, fn) {
    try {
      fn();
    } catch (e) {
      errorCardInto(chartWrap(canvasId), label, e);
    }
  }
  function safeRender(label, containerId, fn) {
    try {
      fn();
    } catch (e) {
      errorCardInto(document.getElementById(containerId), label, e);
    }
  }

  // Shared dashboard state, read by functions outside boot()'s own scope
  // (e.g. the race-tag checkbox handler triggers a progress refresh).
  const dashboardState = { range: "4w", stats: null, recs: null };

  async function refreshProgress() {
    const progress = await api.progress(dashboardState.range);
    safeRender("Progress tiles", "progress-tiles", () => renderProgressTiles(progress));
    safeRenderChart("Weekly distance chart", "chart-weekly-distance", () => renderWeeklyDistanceChart(progress));
    safeRenderChart("Pace trend chart", "chart-pace-trend", () => renderPaceTrendChart(progress));
    safeRenderChart("Aerobic efficiency chart", "chart-efficiency", () => renderEfficiencyTrendChart(progress));
    safeRenderChart("Personal-bests timeline", "chart-pb-timeline", () => renderPbTimelineChart(progress));
    safeRender("Race time estimates", "race-predictions-table", () => renderRacePredictionsTable(progress));
    if (dashboardState.stats) {
      safeRender("At a glance", "glance-grid", () => renderGlance(dashboardState.stats, progress, dashboardState.recs));
    }
    return progress;
  }

  function deltaSpan(value, { lowerIsBetter = false, suffix = "" } = {}) {
    if (value == null) return el("span", { class: "delta flat" }, ["—"]);
    const isUp = lowerIsBetter ? value < 0 : value > 0;
    const isFlat = value === 0;
    const cls = isFlat ? "flat" : isUp ? "up" : "down";
    const sign = value > 0 ? "+" : "";
    return el("span", { class: `delta ${cls}` }, [`${sign}${value}${suffix} vs. previous period`]);
  }

  // ---------- Q1: progress (range-aware) ----------
  function renderProgressTiles(progress) {
    const { current, delta } = progress.range_progress;
    const tiles = document.getElementById("progress-tiles");
    tiles.innerHTML = "";
    tiles.appendChild(
      el("div", { class: "card stat-tile" }, [
        el("div", { class: "label" }, ["Distance"]),
        el("div", { class: "value" }, [fmtKm(current.distance_km)]),
        delta ? deltaSpan(delta.distance_km, { suffix: " km" }) : "",
      ])
    );
    tiles.appendChild(
      el("div", { class: "card stat-tile" }, [
        el("div", { class: "label" }, ["Runs"]),
        el("div", { class: "value" }, [String(current.runs)]),
        delta ? deltaSpan(delta.runs) : "",
      ])
    );
    tiles.appendChild(
      el("div", { class: "card stat-tile" }, [
        el("div", { class: "label" }, ["Avg pace"]),
        el("div", { class: "value" }, [fmtPaceSec(current.avg_pace_s_per_km)]),
        delta ? deltaSpan(delta.avg_pace_s_per_km, { lowerIsBetter: true, suffix: " s/km" }) : "",
      ])
    );
    tiles.appendChild(
      el("div", { class: "card stat-tile" }, [
        el("div", { class: "label" }, ["Longest run"]),
        el("div", { class: "value" }, [fmtKm(current.longest_run_km)]),
        delta ? deltaSpan(delta.longest_run_km, { suffix: " km" }) : "",
      ])
    );
  }

  function raceOverlayDataset(weekLabels, raceMarkers, valueByWeek) {
    const raceWeeks = new Map(raceMarkers.map((r) => [isoWeekKey(r.date), r]));
    const data = weekLabels.map((w, i) => (raceWeeks.has(w) ? valueByWeek[i] : null));
    if (data.every((v) => v == null)) return null;
    // Carried on the dataset (not part of the Chart.js data contract) so
    // the shared tooltip's afterLabel callback can show which race this
    // point is, by index -- without having to give every chart its own
    // custom tooltip formatting.
    const raceNames = weekLabels.map((w) => (raceWeeks.has(w) ? raceWeeks.get(w).name : null));
    return {
      type: "line",
      label: "Race",
      data,
      raceNames,
      showLine: false,
      pointStyle: "star",
      pointRadius: 9,
      pointBackgroundColor: css("--s2"),
      pointBorderColor: css("--s2"),
    };
  }

  function renderWeeklyDistanceChart(progress) {
    const weeks = progress.weekly_distance;
    const labels = weeks.map((w) => w.week);
    const values = weeks.map((w) => w.distance_km);
    const datasets = [{ label: "Distance (km)", data: values, backgroundColor: css("--s1"), borderRadius: 4, maxBarThickness: 28 }];
    const overlay = raceOverlayDataset(labels, progress.race_markers, values);
    if (overlay) datasets.push(overlay);
    makeChart("chart-weekly-distance", {
      type: "bar",
      data: { labels, datasets },
      options: baseChartOptions({ legend: !!overlay }),
    });
  }

  function renderPaceTrendChart(progress) {
    const weeks = progress.pace_trend;
    if (weeks.length === 0) {
      const wrap = chartWrap("chart-pace-trend");
      if (wrap) wrap.innerHTML = '<div class="not-enough-data">not enough data yet</div>';
      return;
    }
    const labels = weeks.map((w) => w.week);
    const values = weeks.map((w) => w.avg_pace_s_per_km);
    const datasets = [
      { label: "Weekly avg pace", data: values, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 2, tension: 0.2, spanGaps: true },
      { label: "4-week rolling avg", data: weeks.map((w) => w.rolling_avg_pace_s_per_km), borderColor: css("--ink-muted"), backgroundColor: css("--ink-muted"), borderWidth: 2, borderDash: [4, 3], pointRadius: 0, tension: 0.2, spanGaps: true },
    ];
    const overlay = raceOverlayDataset(labels, progress.race_markers, values);
    if (overlay) datasets.push(overlay);
    makeChart("chart-pace-trend", {
      type: "line",
      data: { labels, datasets },
      options: baseChartOptions({ legend: true, paceAxis: true }),
    });
  }

  function renderEfficiencyTrendChart(progress) {
    const rows = progress.pace_at_hr_trend;
    const withData = rows.filter((r) => r.pace_at_reference_hr_s_per_km != null);
    const wrap = chartWrap("chart-efficiency");
    if (withData.length === 0) {
      const c = progress.hr_coverage || {};
      const detail =
        c.total_runs != null
          ? `needs 8+ runs with heart-rate data in the trailing window -- currently ${c.runs_with_hr} of ${c.total_runs} runs have it` +
            (c.strava_total ? ` (${c.strava_with_hr} of ${c.strava_total} Strava runs)` : "")
          : "needs 8+ runs with heart-rate data in the trailing window";
      if (wrap) wrap.innerHTML = `<div class="not-enough-data">not enough data yet (${escapeHtml(detail)})</div>`;
      return;
    }
    makeChart("chart-efficiency", {
      type: "line",
      data: {
        labels: rows.map((r) => r.week),
        datasets: [{
          label: "Pace at reference HR",
          data: rows.map((r) => r.pace_at_reference_hr_s_per_km),
          borderColor: css("--s1"), backgroundColor: css("--s1"),
          borderWidth: 2, pointRadius: 2, tension: 0.25, spanGaps: true,
        }],
      },
      options: baseChartOptions({ legend: false, paceAxis: true }),
    });
  }

  function renderPbTimelineChart(progress) {
    const events = progress.personal_bests_timeline;
    const wrap = chartWrap("chart-pb-timeline");
    if (events.length === 0) {
      if (wrap) wrap.innerHTML = '<div class="not-enough-data">not enough data yet (needs a 5K/10K/half-marathon-length run on record)</div>';
      return;
    }
    // A shared category axis (no date-scale adapter is vendored), one
    // label per distinct event date across all distances.
    const labels = [...new Set(events.map((e) => e.date))].sort();
    const byLabel = { "5k": [], "10k": [], half_marathon: [] };
    for (const e of events) if (byLabel[e.distance_label]) byLabel[e.distance_label].push(e);
    const colors = { "5k": css("--s1"), "10k": css("--s2"), half_marathon: css("--s3") };
    const names = { "5k": "5K", "10k": "10K", half_marathon: "Half marathon" };
    const datasets = Object.entries(byLabel)
      .filter(([, evs]) => evs.length > 0)
      .map(([label, evs]) => {
        const byDate = new Map(evs.map((e) => [e.date, e.pace_s_per_km]));
        return {
          label: names[label],
          data: labels.map((d) => (byDate.has(d) ? byDate.get(d) : null)),
          borderColor: colors[label], backgroundColor: colors[label],
          showLine: false, pointRadius: 5, spanGaps: false,
        };
      });
    makeChart("chart-pb-timeline", {
      type: "line",
      data: { labels, datasets },
      options: baseChartOptions({ legend: true, paceAxis: true }),
    });
  }

  function renderRacePredictionsTable(progress) {
    const table = document.getElementById("race-predictions-table");
    const labelOrder = [["5k", "5K"], ["10k", "10K"], ["half_marathon", "Half marathon"], ["marathon", "Marathon"]];
    table.innerHTML = "<tr><th>Distance</th><th>Estimate</th><th>Source</th></tr>" +
      labelOrder.map(([key, label]) => {
        const p = progress.race_predictions[key];
        if (!p) return `<tr><td>${label}</td><td colspan="2" class="not-enough-data">not enough data yet</td></tr>`;
        return `<tr><td>${label}</td><td>${fmtTime(p.seconds)}${p.is_measured ? " (measured)" : ""}</td><td>${p.is_measured ? "—" : "from " + p.source + " PB"}</td></tr>`;
      }).join("");
  }

  const RACE_TAG_LIST_SIZE = 20;
  // The user's own known race date -- pinned to the top of the list below
  // regardless of sort order, so it's never scrolled past.
  const KNOWN_RACE_DATE = "2026-11-08";

  async function renderRaceTagList() {
    const box = document.getElementById("race-tag-list");
    box.innerHTML = '<div class="not-enough-data">loading…</div>';
    let activities;
    try {
      // Always the most recent activities overall, independent of the
      // dashboard's range switcher above -- tagging a race from months
      // ago shouldn't require first switching the whole page to "all time".
      ({ activities } = await api.activities("all"));
    } catch (e) {
      box.innerHTML = `<div class="not-enough-data">couldn't load activities: ${escapeHtml(e.message)}</div>`;
      return;
    }
    if (activities.length === 0) {
      box.innerHTML = '<div class="not-enough-data">no activities yet</div>';
      return;
    }

    let shortlist = activities.slice(0, RACE_TAG_LIST_SIZE);
    const knownRace = activities.find((a) => a.date === KNOWN_RACE_DATE);
    if (knownRace) {
      shortlist = [knownRace, ...shortlist.filter((a) => a.id !== knownRace.id)].slice(0, RACE_TAG_LIST_SIZE);
    }

    box.innerHTML = "";
    for (const a of shortlist) {
      const checkbox = el("input", { type: "checkbox" });
      const nameInput = el("input", { type: "text", class: "race-name-input", placeholder: "Race name" });
      nameInput.value = a.race_name || "";
      nameInput.disabled = !a.is_race;
      if (a.is_race) checkbox.setAttribute("checked", "checked");

      const commit = async () => {
        checkbox.disabled = true;
        nameInput.disabled = true;
        try {
          await api.setRace(a.id, checkbox.checked, checkbox.checked ? nameInput.value.trim() : null);
          a.is_race = checkbox.checked;
          a.race_name = checkbox.checked ? nameInput.value.trim() : null;
          await refreshProgress();
        } catch (e) {
          alert("Could not update race tag: " + e.message);
          checkbox.checked = !checkbox.checked;
        } finally {
          checkbox.disabled = false;
          nameInput.disabled = !checkbox.checked;
        }
      };

      checkbox.addEventListener("change", () => {
        nameInput.disabled = !checkbox.checked;
        commit();
      });
      nameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") nameInput.blur();
      });
      nameInput.addEventListener("blur", () => {
        if (checkbox.checked && nameInput.value.trim() !== (a.race_name || "")) commit();
      });

      const label = a.date === KNOWN_RACE_DATE ? `${a.date} 🏁 · ${a.activity_type || "activity"}` : `${a.date} · ${a.activity_type || "activity"}`;
      box.appendChild(
        el("div", { class: "race-tag-row" }, [
          el("span", {}, [label]),
          el("span", { class: "race-tag-meta" }, [`${a.distance_km} km`]),
          el("span", { class: "race-tag-meta" }, [fmtTime(a.time_s)]),
          checkbox,
          nameInput,
        ])
      );
    }
  }

  // ---------- Q2: where am I (standing) ----------
  function renderStanding(stats) {
    const standing = stats.standing;

    const statusBox = document.getElementById("standing-status");
    const statusLabels = { ahead: "Ahead", on_track: "On track", behind: "Behind", no_goal_set: "No goal set" };
    statusBox.innerHTML = "";
    statusBox.appendChild(el("span", { class: `status-badge ${standing.status.status}` }, [statusLabels[standing.status.status] || standing.status.status]));
    if (standing.follows_watch_plan) {
      statusBox.appendChild(el("div", { class: "status-rule", style: "margin-top:10px;" }, ["You follow your watch's training plan, so this describes where the numbers sit -- it's not a plan change."]));
    }
    statusBox.appendChild(el("div", { class: "status-rule" }, [standing.status.rule]));
    if (standing.status.avg_runs_per_week_last_4w != null) {
      statusBox.appendChild(el("div", { class: "status-rule" }, [`Last 4 weeks: ${standing.status.avg_runs_per_week_last_4w} runs/week average${standing.status.avg_pace_s_per_km_last_4w != null ? `, ${fmtPaceSec(standing.status.avg_pace_s_per_km_last_4w)} average pace` : ""}.`]));
    }

    const tiles = document.getElementById("standing-tiles");
    tiles.innerHTML = "";
    const form = standing.current_form_estimates;
    const half = form.predictions.half_marathon;
    tiles.appendChild(
      statTile(
        "Current half-marathon estimate",
        half ? fmtTime(half.seconds) : "—",
        half ? `${half.is_measured ? "measured" : "estimate from " + half.source} · last ${form.window_weeks} weeks` : "not enough recent data",
        `Riegel extrapolation from your best qualifying effort in the last ${form.window_weeks} weeks -- current fitness, not an all-time best.`
      )
    );
    const gap = standing.gap_to_target_pace;
    tiles.appendChild(
      gap
        ? statTile(
            "Gap to target pace",
            gap.gap_s_per_km == null ? "—" : `${gap.gap_s_per_km > 0 ? "+" : ""}${gap.gap_s_per_km} s/km`,
            gap.avg_pace_s_per_km_last_4w != null ? `${fmtPaceSec(gap.avg_pace_s_per_km_last_4w)} avg vs. ${fmtPaceSec(gap.target_pace_s_per_km)} target` : "no recent runs",
            "Last 4 weeks' average pace minus your target pace from setup. Positive means slower than target."
          )
        : statTile("Gap to target pace", "—", "no target pace set in setup")
    );
    const weeksUntil = standing.weeks_until_race;
    tiles.appendChild(
      weeksUntil != null
        ? statTile("Weeks until race", String(weeksUntil), "from your race date in setup")
        : statTile("Weeks until race", "—", "no race date set in setup")
    );

    const volumeBox = document.getElementById("standing-volume");
    const v = standing.weekly_volume_vs_average;
    volumeBox.innerHTML = "";
    volumeBox.appendChild(el("div", { class: "label", style: "font-size:12px; color:var(--ink-muted); margin-bottom:8px;" }, ["Weekly volume vs. your own average"]));
    volumeBox.appendChild(el("div", { class: "value", style: "font-size:22px; font-weight:600;" }, [fmtKm(v.this_week_km)]));
    volumeBox.appendChild(el("div", { class: "detail", style: "font-size:13px; color:var(--ink-secondary); margin-top:4px;" }, [`this week vs. ${fmtKm(v.avg_4w_km)} (4-week avg), ${fmtKm(v.avg_12w_km)} (12-week avg)`]));
    if (v.is_spike) {
      volumeBox.appendChild(el("div", { class: "spike-flag", style: "margin-top:8px; font-size:13px;" }, [`⚠ more than ${v.spike_threshold}x your 4-week average`]));
    }

    const consistencyBox = document.getElementById("standing-consistency");
    const c = standing.consistency;
    consistencyBox.innerHTML = "";
    consistencyBox.appendChild(el("div", { class: "label", style: "font-size:12px; color:var(--ink-muted); margin-bottom:8px;" }, ["Consistency"]));
    consistencyBox.appendChild(el("div", { class: "value", style: "font-size:22px; font-weight:600;" }, [`${c.avg_runs_per_week} runs/week`]));
    consistencyBox.appendChild(el("div", { class: "detail", style: "font-size:13px; color:var(--ink-secondary); margin-top:4px;" }, [`avg over last ${c.window_weeks} weeks · ${c.weeks_with_no_runs} week${c.weeks_with_no_runs === 1 ? "" : "s"} with no runs`]));

    const longRun = standing.long_run_progression;
    if (longRun.length === 0) {
      const wrap = chartWrap("chart-long-run");
      if (wrap) wrap.innerHTML = '<div class="not-enough-data">not enough data yet (no runs in the last 12 weeks)</div>';
    } else {
      makeChart("chart-long-run", {
        type: "line",
        data: {
          labels: longRun.map((r) => r.week),
          datasets: [{ label: "Longest run (km)", data: longRun.map((r) => r.longest_run_km), borderColor: css("--s3"), backgroundColor: css("--s3"), borderWidth: 2, pointRadius: 3, tension: 0.2 }],
        },
        options: baseChartOptions({ legend: false }),
      });
    }

    const recTiles = document.getElementById("standing-recovery");
    recTiles.innerHTML = "";
    const recDefs = [
      ["sleep_duration_s", "Sleep", (v) => fmtTime(v)],
      ["hrv_ms", "HRV", (v) => `${v} ms`],
      ["resting_hr", "Resting HR", (v) => `${v} bpm`],
      ["sleep_score", "Sleep score", (v) => `${v}`],
    ];
    for (const [key, label, fmt] of recDefs) {
      const r = standing.recovery[key];
      if (!r || r.recent_avg == null) {
        recTiles.appendChild(statTile(label, "—", "not enough data yet"));
        continue;
      }
      const delta = r.delta;
      const deltaStr = delta == null ? "" : `${delta > 0 ? "+" : ""}${delta} vs. baseline`;
      recTiles.appendChild(statTile(label, fmt(r.recent_avg), `${deltaStr} (n=${r.n_recent}/${r.n_baseline})`));
    }
  }

  // ---------- at-a-glance (top of page) ----------
  function renderGlance(stats, progress, recsData) {
    const grid = document.getElementById("glance-grid");
    grid.innerHTML = "";

    const p = progress.range_progress;
    grid.appendChild(
      el("div", { class: "card glance-card" }, [
        el("div", { class: "glance-title" }, ["How am I progressing?"]),
        el("div", { class: "glance-headline" }, [fmtKm(p.current.distance_km)]),
        el("div", { class: "glance-detail" }, [`${p.current.runs} runs at ${fmtPaceSec(p.current.avg_pace_s_per_km)} avg pace`]),
        p.delta ? deltaSpan(p.delta.distance_km, { suffix: " km" }) : "",
      ])
    );

    const statusLabels = { ahead: "Ahead", on_track: "On track", behind: "Behind", no_goal_set: "No goal set" };
    const status = stats.standing.status;
    grid.appendChild(
      el("div", { class: "card glance-card" }, [
        el("div", { class: "glance-title" }, ["Where am I in my training?"]),
        el("div", { class: "glance-headline" }, [el("span", { class: `status-badge ${status.status}` }, [statusLabels[status.status] || status.status])]),
        el("div", { class: "glance-detail" }, [
          status.avg_runs_per_week_last_4w != null ? `${status.avg_runs_per_week_last_4w} runs/week, last 4 weeks` : "set a goal in setup to see this",
        ]),
      ])
    );

    const recs = (recsData && recsData.recommendations) || [];
    grid.appendChild(
      el("div", { class: "card glance-card" }, [
        el("div", { class: "glance-title" }, ["What should I do next?"]),
        el("div", { class: "glance-headline" }, [recs.length ? `${recs.length} recommendation${recs.length === 1 ? "" : "s"}` : "—"]),
        el("div", { class: "glance-detail" }, [recs[0] ? recs[0].text.slice(0, 90) + (recs[0].text.length > 90 ? "…" : "") : "none generated yet"]),
      ])
    );
  }

  function renderLoad(stats) {
    const hz = stats.load.hr_zone_distribution;
    const wrap = document.getElementById("hr-zone-wrap");
    if (!hz.available) {
      wrap.innerHTML = `<div class="not-enough-data">needs per-zone heart-rate minutes from Garmin -- 0 of ${hz.n_running_activities ?? 0} running activities have it yet (Strava's export doesn't carry this field)</div>`;
      return;
    }
    wrap.innerHTML = '<canvas id="chart-hr-zones"></canvas>';
    const zoneColors = [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")];
    const labels = Object.keys(hz.zones).map((z) => `Zone ${z}`);
    makeChart("chart-hr-zones", {
      type: "bar",
      data: { labels, datasets: [{ label: "% of running time", data: Object.values(hz.zones), backgroundColor: labels.map((_, i) => zoneColors[i % zoneColors.length]), borderRadius: 4 }] },
      options: baseChartOptions({ legend: false }),
    });
  }

  function renderPatterns(stats) {
    const cyclePane = document.getElementById("patterns-cycle");
    const cp = stats.patterns.cycle_phase;
    if (!cp.available) {
      cyclePane.innerHTML = `<div class="card not-enough-data">${cp.reason || "no cycle data logged"}</div>`;
    } else {
      const grid = el("div", { class: "grid pattern-grid" });
      for (const [phase, data] of Object.entries(cp.phases)) {
        const label = phase.charAt(0).toUpperCase() + phase.slice(1);
        if (data.reason) {
          grid.appendChild(statTile(label, "—", `n=${data.n}: ${data.reason}`));
        } else {
          grid.appendChild(statTile(label, fmtPaceSec(data.avg_pace_s_per_km), `avg HR ${data.avg_hr ?? "—"} · n=${data.n}`));
        }
      }
      cyclePane.innerHTML = "";
      cyclePane.appendChild(grid);
    }

    const conditionsPane = document.getElementById("patterns-conditions");
    const text = stats.patterns.special_conditions;
    conditionsPane.innerHTML = text
      ? `<div class="label" style="font-size:12px; color:var(--ink-muted); margin-bottom:6px;">Logged condition (context only, not statistically correlated)</div><div>${escapeHtml(text)}</div>`
      : '<div class="not-enough-data">no special conditions logged</div>';
  }

  // Human-readable evidence tags and the one-line plain explanation shown
  // in each tag's tooltip (same hover pattern as statTile's "method" icon).
  const EVIDENCE_LABELS = { strong: "Well supported", moderate: "Some evidence", hypothesis: "Worth testing" };
  const EVIDENCE_TOOLTIPS = {
    strong: "Backed by well-established training science, applied to your own numbers.",
    moderate: "A reasonable read of your data, with some uncertainty.",
    hypothesis: "A pattern worth testing, not yet a strong signal -- often from a small amount of data.",
  };

  function renderRecommendations(data) {
    const list = document.getElementById("recs-list");
    const genAt = document.getElementById("recs-generated-at");
    genAt.textContent = data.generated_at ? `generated ${new Date(data.generated_at).toLocaleString()}` : "not generated yet";
    if (!data.recommendations || data.recommendations.length === 0) {
      list.innerHTML = '<div class="card not-enough-data">No recommendations yet. Click Regenerate (needs ANTHROPIC_API_KEY configured).</div>';
      return;
    }
    list.innerHTML = "";
    for (const rec of data.recommendations) {
      const evidenceTag = el("div", { class: `evidence ${rec.evidence}` }, [
        EVIDENCE_LABELS[rec.evidence] || rec.evidence,
        el("span", { class: "method" }, ["?", el("span", { class: "tooltip" }, [EVIDENCE_TOOLTIPS[rec.evidence] || ""])]),
      ]);
      const children = [evidenceTag, el("div", {}, [rec.text])];
      if (rec.why_it_matters) {
        children.push(el("div", { class: "why-it-matters" }, [rec.why_it_matters]));
      }
      if (rec.rationale) {
        children.push(
          el("details", { class: "show-numbers" }, [
            el("summary", {}, ["Show the numbers"]),
            el("div", { class: "show-numbers-detail" }, [rec.rationale]),
          ])
        );
      }
      list.appendChild(el("div", { class: "card rec-card" }, children));
    }
  }

  function renderGaps(stats) {
    const list = document.getElementById("gaps-list");
    if (!stats.data_gaps || stats.data_gaps.length === 0) {
      list.innerHTML = '<div class="not-enough-data">none recorded</div>';
      return;
    }
    list.innerHTML = stats.data_gaps.map((g) => `<div>${escapeHtml(g)}</div>`).join("");
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // Single switch controlling every "pace is on the y-axis" chart: it
  // reverses the scale (so faster/lower seconds-per-km draws higher),
  // formats ticks and tooltips as min:sec/km, and labels the axis --
  // all three together, so a future edit can't flip the direction on one
  // chart without also updating its ticks/label (there's only one flag to
  // set). See tests/frontend/pace_axis.test.js for the check that every
  // pace chart actually sets it.
  function baseChartOptions({ legend = true, yTickFormatter = null, paceAxis = false } = {}) {
    const tickFormatter = paceAxis ? fmtPaceSec : yTickFormatter;
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: legend, labels: { color: css("--ink-secondary"), font: { size: 11 } } },
        tooltip: {
          backgroundColor: css("--ink"), titleColor: css("--page"), bodyColor: css("--page"), padding: 10, cornerRadius: 6,
          callbacks: {
            label: paceAxis
              ? (context) => {
                  const label = context.dataset.label || "";
                  const formatted = fmtPaceSec(context.parsed.y);
                  return label ? `${label}: ${formatted}` : formatted;
                }
              : undefined,
            // Adds a line rather than replacing the default one, so every
            // other dataset's tooltip (distance, pace, ...) is untouched;
            // only a "Race" point carrying `raceNames` gets the extra line.
            afterLabel: (context) => {
              const names = context.dataset.raceNames;
              const name = names && names[context.dataIndex];
              return name ? `Race: ${name}` : undefined;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: css("--ink-muted"), font: { size: 11 } } },
        y: {
          reverse: paceAxis,
          grid: { color: css("--hairline") },
          title: paceAxis ? { display: true, text: "faster ↑", color: css("--ink-muted"), font: { size: 11 } } : undefined,
          ticks: {
            color: css("--ink-muted"),
            font: { size: 11 },
            callback: tickFormatter ? (v) => tickFormatter(v) : undefined,
          },
        },
      },
    };
  }

  // ---------- settings: strava import ----------
  function relativeTime(iso) {
    if (!iso) return "never";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return iso;
    const seconds = Math.round((Date.now() - then) / 1000);
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  async function renderSyncStatus() {
    const table = document.getElementById("sync-status-table");
    if (!table) return;
    let status;
    try {
      status = await api.syncStatus();
    } catch (e) {
      table.innerHTML = `<tr><td class="not-enough-data">couldn't load sync status: ${escapeHtml(e.message)}</td></tr>`;
      return;
    }
    const rows = [
      ["garmin", "Garmin"],
      ["strava", "Strava"],
    ].map(([key, label]) => {
      const s = status[key] || {};
      let state;
      if (s.running) state = "running…";
      else if (s.last_synced_at == null) state = '<span class="not-enough-data">never synced</span>';
      else if (s.last_ok === false) state = `<span class="test-fail">error: ${escapeHtml(s.last_error || "unknown")}</span>`;
      else state = '<span class="test-ok">ok</span>';
      return `<tr><td>${label}</td><td>${escapeHtml(relativeTime(s.last_synced_at))}</td><td>${state}</td></tr>`;
    });
    table.innerHTML = "<tr><th>Source</th><th>Last synced</th><th>Status</th></tr>" + rows.join("");
  }

  function renderStravaImportReport(report) {
    const box = document.getElementById("strava-import-report");
    if (!report) {
      box.innerHTML = '<div class="not-enough-data">no import yet</div>';
      return;
    }
    const c = report.counts || {};
    const range = report.date_range ? `${report.date_range.start} to ${report.date_range.end}` : "—";
    const rows = [
      ["Rows read", c.rows_read],
      ["Runs imported", c.runs_imported],
      ["Other activities imported", c.other_imported],
      ["Duplicates of Garmin (skipped)", c.skipped_duplicate_of_garmin],
      ["Skipped (missing id/date)", c.skipped_missing_fields],
      ["Skipped (unparseable date)", c.skipped_unparseable_date],
      ["Date range covered", range],
    ];
    let html = '<table class="data-table">' + rows.map(([label, v]) => `<tr><td>${label}</td><td>${v == null ? "—" : v}</td></tr>`).join("") + "</table>";
    if (report.columns_not_found && report.columns_not_found.length) {
      html += `<div class="hint" style="margin-top:8px;">Columns not found: ${report.columns_not_found.map(escapeHtml).join(", ")}</div>`;
    }
    if (report.data_gaps && report.data_gaps.length) {
      html += '<div class="hint" style="margin-top:8px;">' + report.data_gaps.map((g) => escapeHtml(g)).join("<br/>") + "</div>";
    }
    box.innerHTML = html;
  }

  function renderMappingUi(info, onSubmit) {
    const box = document.getElementById("strava-mapping-ui");
    box.classList.remove("hidden");
    box.innerHTML = "";
    box.appendChild(el("p", { class: "hint" }, [
      `Couldn't automatically match these required columns: ${info.missing_required_fields.join(", ")}. ` +
      "Pick the matching column from your file's actual header row below.",
    ]));
    const selects = {};
    for (const field of info.missing_required_fields) {
      const select = el("select", {}, [
        el("option", { value: "" }, ["— not present —"]),
        ...info.available_headers.map((h) => el("option", { value: h }, [h])),
      ]);
      selects[field] = select;
      box.appendChild(el("div", { class: "field" }, [el("label", {}, [field]), select]));
    }
    const submitBtn = el("button", { class: "primary" }, ["Import with this mapping"]);
    submitBtn.addEventListener("click", () => {
      const mapping = {};
      for (const [field, select] of Object.entries(selects)) mapping[field] = select.value;
      onSubmit(mapping);
    });
    box.appendChild(submitBtn);
  }

  function initClaudeTestButton() {
    const btn = document.getElementById("test-claude-btn");
    const resultEl = document.getElementById("test-claude-result");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      resultEl.textContent = "Testing…";
      resultEl.className = "";
      try {
        const result = await api.testClaude();
        resultEl.textContent = result.message;
        resultEl.className = result.ok ? "test-ok" : "test-fail";
      } catch (e) {
        resultEl.textContent = e.message;
        resultEl.className = "test-fail";
      } finally {
        btn.disabled = false;
      }
    });
  }

  // Shared wiring for the Claude/Garmin "Save and test" buttons in
  // Settings: write the key, test it with a real call, and show only the
  // last 4 characters of what's saved -- never the key itself.
  function initApiKeySaveButton(inputId, buttonId, resultId, currentLabelId, saveFn) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(buttonId);
    const resultEl = document.getElementById(resultId);
    const currentLabel = document.getElementById(currentLabelId);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      resultEl.textContent = "Saving and testing…";
      resultEl.className = "";
      try {
        const result = await saveFn(input.value);
        resultEl.textContent = result.message;
        resultEl.className = result.ok ? "test-ok" : "test-fail";
        if (result.masked_key) {
          currentLabel.textContent = `Saved key ends in ${result.masked_key}.`;
          input.value = "";
        }
      } catch (e) {
        resultEl.textContent = e.message;
        resultEl.className = "test-fail";
      } finally {
        btn.disabled = false;
      }
    });
  }

  function initStravaSettings() {
    const fileInput = document.getElementById("settings_strava_file");
    const importBtn = document.getElementById("settings-strava-import-btn");

    api.lastStravaImport().then((r) => renderStravaImportReport(r.report)).catch(() => renderStravaImportReport(null));

    importBtn.addEventListener("click", async () => {
      const file = fileInput.files[0];
      if (!file) { alert("Choose a CSV file first."); return; }
      importBtn.disabled = true;
      importBtn.textContent = "Importing…";
      document.getElementById("strava-mapping-ui").classList.add("hidden");
      try {
        const result = await api.importStrava(file);
        if (result.needs_mapping) {
          renderMappingUi(result, async (mapping) => {
            importBtn.disabled = true;
            try {
              const final = await api.importStravaWithMapping(mapping);
              renderStravaImportReport(final);
              document.getElementById("strava-mapping-ui").classList.add("hidden");
            } catch (e) {
              alert("Import with mapping failed: " + e.message);
            } finally {
              importBtn.disabled = false;
              importBtn.textContent = "Import";
            }
          });
        } else {
          renderStravaImportReport(result);
        }
      } catch (e) {
        alert("Strava import failed: " + e.message);
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = "Import";
        renderSyncStatus();
      }
    });
  }

  // ---------- boot ----------
  async function boot() {
    const status = await api.status();
    document.getElementById("app-title").textContent = status.app_name;
    const actions = document.getElementById("header-actions");
    actions.appendChild(initThemeToggle());
    if (status.demo) actions.appendChild(el("span", { class: "badge demo" }, ["demo data"]));

    if (!status.setup_complete) {
      document.getElementById("wizard-view").classList.remove("hidden");
      initWizard();
      return;
    }

    if (!status.demo) {
      const syncBtn = el("button", {}, ["Sync now"]);
      syncBtn.addEventListener("click", async () => {
        syncBtn.disabled = true;
        syncBtn.textContent = "Syncing…";
        try {
          await api.sync();
          location.reload();
        } catch (e) {
          syncBtn.disabled = false;
          const timedOut = e.name === "AbortError" || /abort/i.test(e.message || "");
          syncBtn.textContent = timedOut ? "Sync timed out" : "Sync failed";
          alert(
            timedOut
              ? `Sync didn't respond within ${SYNC_TIMEOUT_MS / 1000}s. It may still be running on the server -- check Sync status in Settings in a moment.`
              : "Sync failed: " + e.message
          );
          renderSyncStatus();
        }
      });
      actions.appendChild(syncBtn);

      const logoutBtn = el("button", { class: "danger", title: "Forget stored keys and all synced data, and return to setup" }, ["Log out"]);
      logoutBtn.addEventListener("click", async () => {
        const confirmed = confirm(
          "Log out of run-coach?\n\nThis deletes your stored Garmin/Claude/Telegram keys and all synced data on this machine, then returns you to setup. This can't be undone."
        );
        if (!confirmed) return;
        logoutBtn.disabled = true;
        logoutBtn.textContent = "Logging out…";
        try {
          await api.reset();
          location.reload();
        } catch (e) {
          logoutBtn.disabled = false;
          logoutBtn.textContent = "Log out";
          alert("Could not log out: " + e);
        }
      });
      actions.appendChild(logoutBtn);
      initStravaSettings();
      initClaudeTestButton();
      initApiKeySaveButton("settings_claude_key", "save-claude-key-btn", "save-claude-key-result", "claude-key-current", api.saveClaudeKey);
      initApiKeySaveButton("settings_garmin_key", "save-garmin-key-btn", "save-garmin-key-result", "garmin-key-current", api.saveGarminKey);
      renderSyncStatus();
    } else {
      document.getElementById("section-settings").classList.add("hidden");
    }

    document.getElementById("dashboard-view").classList.remove("hidden");

    function setActiveRangeButton() {
      document.querySelectorAll("#range-switcher button").forEach((b) => b.classList.toggle("active", b.dataset.range === dashboardState.range));
    }

    document.querySelectorAll("#range-switcher button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        dashboardState.range = btn.dataset.range;
        setActiveRangeButton();
        try {
          await refreshProgress();
          await renderRaceTagList();
        } catch (e) {
          alert("Could not load that range: " + e.message);
        }
      });
    });
    setActiveRangeButton();

    // Each of these three calls feeds different sections. One failing (a
    // bad Claude key doesn't affect this, but a DB error or a future bug
    // in any one endpoint could) must not blank out the sections fed by
    // the other two, so they're fetched independently via allSettled
    // rather than Promise.all.
    const [statsResult, recsResult, progressResult] = await Promise.allSettled([
      api.stats(),
      api.recommendations(),
      api.progress(dashboardState.range),
    ]);
    const stats = statsResult.status === "fulfilled" ? statsResult.value : null;
    const recs = recsResult.status === "fulfilled" ? recsResult.value : null;
    const progress = progressResult.status === "fulfilled" ? progressResult.value : null;
    dashboardState.stats = stats;
    dashboardState.recs = recs;

    if (progress) {
      safeRender("Progress tiles", "progress-tiles", () => renderProgressTiles(progress));
      safeRenderChart("Weekly distance chart", "chart-weekly-distance", () => renderWeeklyDistanceChart(progress));
      safeRenderChart("Pace trend chart", "chart-pace-trend", () => renderPaceTrendChart(progress));
      safeRenderChart("Aerobic efficiency chart", "chart-efficiency", () => renderEfficiencyTrendChart(progress));
      safeRenderChart("Personal-bests timeline", "chart-pb-timeline", () => renderPbTimelineChart(progress));
      safeRender("Race time estimates", "race-predictions-table", () => renderRacePredictionsTable(progress));
    } else {
      errorCardInto(document.getElementById("progress-tiles"), "Progress", progressResult.reason);
    }
    if (stats) {
      safeRender("Where am I in my training?", "section-standing", () => renderStanding(stats));
      safeRender("Effort distribution", "hr-zone-wrap", () => renderLoad(stats));
      safeRender("Your patterns", "section-patterns", () => renderPatterns(stats));
      safeRender("Data gaps", "gaps-list", () => renderGaps(stats));
    } else {
      errorCardInto(document.getElementById("section-standing"), "Where am I in my training?", statsResult.reason);
      errorCardInto(document.getElementById("gaps-list"), "Data gaps", statsResult.reason);
    }
    if (stats && progress) {
      safeRender("At a glance", "glance-grid", () => renderGlance(stats, progress, recs));
    }
    if (recs) {
      safeRender("What should I do next?", "recs-list", () => renderRecommendations(recs));
    } else {
      errorCardInto(document.getElementById("recs-list"), "What should I do next?", recsResult.reason);
    }
    if (!status.demo) renderRaceTagList();
    else document.getElementById("race-tag-list").innerHTML = '<div class="not-enough-data">read-only in demo mode</div>';

    if (status.demo) document.getElementById("generate-recs-btn").classList.add("hidden");
    document.getElementById("generate-recs-btn").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "Generating…";
      try {
        const result = await api.generateRecommendations();
        dashboardState.recs = result;
        safeRender("What should I do next?", "recs-list", () => renderRecommendations(result));
        if (dashboardState.stats) {
          const freshProgress = await api.progress(dashboardState.range);
          safeRender("At a glance", "glance-grid", () => renderGlance(dashboardState.stats, freshProgress, result));
        }
      } catch (err) {
        alert("Could not generate recommendations: " + err.message);
      } finally {
        e.target.disabled = false;
        e.target.textContent = "Regenerate";
      }
    });
  }

  boot().catch((e) => {
    console.error("[boot]", e);
    document.body.appendChild(
      el("div", { class: "card render-error", style: "margin:16px;" }, [`Couldn't load run-coach: ${e.message}`])
    );
  });
})();
