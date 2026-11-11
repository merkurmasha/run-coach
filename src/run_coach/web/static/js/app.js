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
  };

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

  function renderProgress(stats) {
    const monthly = stats.progress.monthly;
    const lastMonth = monthly[monthly.length - 1];
    const tiles = document.getElementById("progress-tiles");
    tiles.innerHTML = "";
    tiles.appendChild(statTile("This month", lastMonth ? fmtKm(lastMonth.distance_km) : "—", lastMonth ? `${lastMonth.runs} runs` : "No runs yet", "Sum of distance for all activities this calendar month whose type contains \"run\"."));
    tiles.appendChild(statTile("Avg pace", lastMonth ? fmtPaceSec(lastMonth.avg_pace_s_per_km) : "—", "this month", "Total distance this month ÷ total moving time this month (not an average of per-run paces)."));
    tiles.appendChild(statTile("Total runs", String(stats.n_running_activities), "all time", "Count of every synced activity whose type contains \"run\", Garmin and Strava combined after deduplication."));

    new Chart(document.getElementById("chart-monthly-distance"), {
      type: "bar",
      data: {
        labels: monthly.map((m) => m.month),
        datasets: [{ label: "Distance (km)", data: monthly.map((m) => m.distance_km), backgroundColor: css("--s1"), borderRadius: 4, maxBarThickness: 28 }],
      },
      options: baseChartOptions({ legend: false }),
    });

    const pbTiles = document.getElementById("pb-tiles");
    pbTiles.innerHTML = "";
    const pbLabels = { "5k": "5K", "10k": "10K", half_marathon: "Half marathon" };
    for (const [key, label] of Object.entries(pbLabels)) {
      const pb = stats.progress.personal_bests[key];
      pbTiles.appendChild(
        statTile(
          `${label} PB`,
          pb ? fmtTime(pb.moving_time_s) : "—",
          pb ? `${fmtPaceSec(pb.pace_s_per_km)} · ${pb.date}` : "no qualifying activity yet",
          "Counts only whole activities within ~2-5% of the target distance — never a split pulled from a longer run."
        )
      );
    }

    const table = document.getElementById("race-predictions-table");
    const labelOrder = [["5k", "5K"], ["10k", "10K"], ["half_marathon", "Half marathon"], ["marathon", "Marathon"]];
    table.innerHTML = "<tr><th>Distance</th><th>Estimate</th><th>Source</th></tr>" +
      labelOrder.map(([key, label]) => {
        const p = stats.progress.race_predictions[key];
        if (!p) return `<tr><td>${label}</td><td colspan="2" class="not-enough-data">not enough data yet</td></tr>`;
        return `<tr><td>${label}</td><td>${fmtTime(p.seconds)}${p.is_measured ? " (measured)" : ""}</td><td>${p.is_measured ? "—" : "from " + p.source + " PB"}</td></tr>`;
      }).join("");
  }

  function renderEfficiency(stats) {
    const rows = stats.aerobic_efficiency.monthly_pace_at_reference_hr;
    const withData = rows.filter((r) => r.pace_at_reference_hr_s_per_km != null);
    if (withData.length === 0) {
      document.getElementById("chart-efficiency").parentElement.innerHTML = '<div class="not-enough-data">not enough data yet (needs 8+ runs with heart-rate data in a month)</div>';
      return;
    }
    new Chart(document.getElementById("chart-efficiency"), {
      type: "line",
      data: {
        labels: rows.map((r) => r.month),
        datasets: [{
          label: "Pace at reference HR",
          data: rows.map((r) => r.pace_at_reference_hr_s_per_km),
          borderColor: css("--s1"), backgroundColor: css("--s1"),
          borderWidth: 2, pointRadius: 3, tension: 0.25, spanGaps: true,
        }],
      },
      options: baseChartOptions({ legend: false, yTickFormatter: fmtPaceSec }),
    });
  }

  function renderLoad(stats) {
    const weeks = stats.load.weekly_volume;
    new Chart(document.getElementById("chart-weekly-volume"), {
      type: "bar",
      data: { labels: weeks.map((w) => w.week.replace(/^\d{4}-/, "")), datasets: [{ label: "km", data: weeks.map((w) => w.distance_km), backgroundColor: css("--s1"), borderRadius: 4, maxBarThickness: 18 }] },
      options: baseChartOptions({ legend: false }),
    });

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

  function renderRecovery(stats) {
    const tiles = document.getElementById("recovery-tiles");
    tiles.innerHTML = "";
    const defs = [
      ["sleep_duration_s", "Sleep", (v) => fmtTime(v)],
      ["hrv_ms", "HRV", (v) => `${v} ms`],
      ["resting_hr", "Resting HR", (v) => `${v} bpm`],
      ["sleep_score", "Sleep score", (v) => `${v}`],
    ];
    for (const [key, label, fmt] of defs) {
      const r = stats.recovery[key];
      if (!r || r.recent_avg == null) {
        tiles.appendChild(statTile(label, "—", "not enough data yet"));
        continue;
      }
      const delta = r.delta;
      const deltaStr = delta == null ? "" : `${delta > 0 ? "+" : ""}${delta} vs. baseline`;
      tiles.appendChild(statTile(label, fmt(r.recent_avg), `${deltaStr} (n=${r.n_recent}/${r.n_baseline})`));
    }
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
    } else {
      document.getElementById("section-settings").classList.add("hidden");
    }

    document.getElementById("dashboard-view").classList.remove("hidden");
    const [stats, recs] = await Promise.all([api.stats(), api.recommendations()]);
    renderProgress(stats);
    renderEfficiency(stats);
    renderLoad(stats);
    renderRecovery(stats);
    renderPatterns(stats);
    renderRecommendations(recs);
    renderGaps(stats);

    if (status.demo) document.getElementById("generate-recs-btn").classList.add("hidden");
    document.getElementById("generate-recs-btn").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "Generating…";
      try {
        const result = await api.generateRecommendations();
        renderRecommendations(result);
      } catch (err) {
        alert("Could not generate recommendations: " + err);
      } finally {
        e.target.disabled = false;
        e.target.textContent = "Regenerate";
      }
    });
  }

  boot();
})();
