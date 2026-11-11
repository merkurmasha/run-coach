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
    sync: () => asJson(fetch("/api/sync", { method: "POST" })),
    reset: () => asJson(fetch("/api/reset", { method: "POST" })),
    testClaude: () => asJson(fetch("/api/claude/test", { method: "POST" })),
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
    setRace: (activityId, isRace) =>
      asJson(fetch(`/api/activities/${encodeURIComponent(activityId)}/race`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_race: isRace }) })),
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

  // Shared dashboard state, read by functions outside boot()'s own scope
  // (e.g. the race-tag checkbox handler triggers a progress refresh).
  const dashboardState = { range: "4w", stats: null, recs: null };

  async function refreshProgress() {
    const progress = await api.progress(dashboardState.range);
    renderProgressTiles(progress);
    renderWeeklyDistanceChart(progress);
    renderPaceTrendChart(progress);
    renderEfficiencyTrendChart(progress);
    renderPbTimelineChart(progress);
    renderRacePredictionsTable(progress);
    if (dashboardState.stats) renderGlance(dashboardState.stats, progress, dashboardState.recs);
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
    return {
      type: "line",
      label: "Race",
      data,
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
      document.getElementById("chart-pace-trend").parentElement.querySelector(".chart-wrap").innerHTML = '<div class="not-enough-data">not enough data yet</div>';
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
      options: baseChartOptions({ legend: true, yTickFormatter: fmtPaceSec }),
    });
  }

  function renderEfficiencyTrendChart(progress) {
    const rows = progress.pace_at_hr_trend;
    const withData = rows.filter((r) => r.pace_at_reference_hr_s_per_km != null);
    const wrap = document.getElementById("chart-efficiency").parentElement.querySelector(".chart-wrap");
    if (withData.length === 0) {
      wrap.innerHTML = '<div class="not-enough-data">not enough data yet (needs 8+ runs with heart-rate data in the trailing window)</div>';
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
      options: baseChartOptions({ legend: false, yTickFormatter: fmtPaceSec }),
    });
  }

  function renderPbTimelineChart(progress) {
    const events = progress.personal_bests_timeline;
    const wrap = document.getElementById("chart-pb-timeline").parentElement.querySelector(".chart-wrap");
    if (events.length === 0) {
      wrap.innerHTML = '<div class="not-enough-data">not enough data yet</div>';
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
      options: baseChartOptions({ legend: true, yTickFormatter: fmtPaceSec }),
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

  async function renderRaceTagList(range) {
    const box = document.getElementById("race-tag-list");
    box.innerHTML = '<div class="not-enough-data">loading…</div>';
    let activities;
    try {
      ({ activities } = await api.activities(range));
    } catch (e) {
      box.innerHTML = `<div class="not-enough-data">couldn't load activities: ${escapeHtml(e.message)}</div>`;
      return;
    }
    if (activities.length === 0) {
      box.innerHTML = '<div class="not-enough-data">no activities in this range</div>';
      return;
    }
    box.innerHTML = "";
    for (const a of activities.slice(0, 60)) {
      const checkbox = el("input", { type: "checkbox" });
      if (a.is_race) checkbox.setAttribute("checked", "checked");
      checkbox.addEventListener("change", async () => {
        checkbox.disabled = true;
        try {
          await api.setRace(a.id, checkbox.checked);
          await refreshProgress();
        } catch (e) {
          alert("Could not update race tag: " + e.message);
          checkbox.checked = !checkbox.checked;
        } finally {
          checkbox.disabled = false;
        }
      });
      box.appendChild(
        el("div", { class: "race-tag-row" }, [
          el("span", {}, [`${a.date} · ${a.activity_type || "activity"}`]),
          el("span", { class: "race-tag-meta" }, [`${a.distance_km} km`]),
          checkbox,
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
      document.getElementById("chart-long-run").parentElement.querySelector(".chart-wrap").innerHTML = '<div class="not-enough-data">not enough data yet</div>';
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
      wrap.innerHTML = '<div class="not-enough-data">not available from Garmin for your activities yet</div>';
      return;
    }
    const zoneColors = [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")];
    const labels = Object.keys(hz.zones).map((z) => `Zone ${z}`);
    new Chart(document.getElementById("chart-hr-zones"), {
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
      list.appendChild(
        el("div", { class: "card rec-card" }, [
          el("div", { class: `evidence ${rec.evidence}` }, [rec.evidence]),
          el("div", {}, [rec.text]),
          el("div", { class: "rationale" }, [rec.rationale]),
        ])
      );
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

  function baseChartOptions({ legend = true, yTickFormatter = null } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: legend, labels: { color: css("--ink-secondary"), font: { size: 11 } } },
        tooltip: { backgroundColor: css("--ink"), titleColor: css("--page"), bodyColor: css("--page"), padding: 10, cornerRadius: 6 },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: css("--ink-muted"), font: { size: 11 } } },
        y: {
          grid: { color: css("--hairline") },
          ticks: {
            color: css("--ink-muted"),
            font: { size: 11 },
            callback: yTickFormatter ? (v) => yTickFormatter(v) : undefined,
          },
        },
      },
    };
  }

  // ---------- settings: strava import ----------
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
      ["Imported", c.imported],
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
          syncBtn.textContent = "Sync failed";
          alert("Sync failed: " + e.message);
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
          await renderRaceTagList(dashboardState.range);
        } catch (e) {
          alert("Could not load that range: " + e.message);
        }
      });
    });
    setActiveRangeButton();

    const [stats, recs, progress] = await Promise.all([api.stats(), api.recommendations(), api.progress(dashboardState.range)]);
    dashboardState.stats = stats;
    dashboardState.recs = recs;

    renderProgressTiles(progress);
    renderWeeklyDistanceChart(progress);
    renderPaceTrendChart(progress);
    renderEfficiencyTrendChart(progress);
    renderPbTimelineChart(progress);
    renderRacePredictionsTable(progress);
    renderStanding(stats);
    renderGlance(stats, progress, recs);
    renderLoad(stats);
    renderPatterns(stats);
    renderRecommendations(recs);
    renderGaps(stats);
    if (!status.demo) renderRaceTagList(dashboardState.range);
    else document.getElementById("race-tag-list").innerHTML = '<div class="not-enough-data">read-only in demo mode</div>';

    if (status.demo) document.getElementById("generate-recs-btn").classList.add("hidden");
    document.getElementById("generate-recs-btn").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "Generating…";
      try {
        const result = await api.generateRecommendations();
        dashboardState.recs = result;
        renderRecommendations(result);
        renderGlance(dashboardState.stats, await api.progress(dashboardState.range), result);
      } catch (err) {
        alert("Could not generate recommendations: " + err.message);
      } finally {
        e.target.disabled = false;
        e.target.textContent = "Regenerate";
      }
    });
  }

  boot();
})();
