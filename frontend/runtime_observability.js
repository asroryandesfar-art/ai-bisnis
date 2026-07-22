/* Runtime Operations — operator panel for the durable runtime (P0-D) + Evaluation
 * scores (P1-D), surfacing GET /api/runtime/health & /evaluations (P2-C).
 * Self-contained + dependency-injected like web_intelligence.js: createRuntime-
 * Observability(ctx) returns a { route: renderFn } map app.js spreads in.
 *
 * Scope = ONLY what the API returns (queue/backlog/in-flight/stalled/DLQ/throughput/
 * workers + per-agent eval scores). No mock data. Read-only; auto-refreshes while
 * the route is active.
 */
import { t } from "/ui/i18n.js?v=20260723-rt-1";
import { esc, icon, pageHeader, metricCard, emptyState, skeletonCards, relativeTime, formatNumber } from "/ui/components.js?v=20260723-rt-1";

const RT = { windowHours: 24, jobStatus: "dead_letter", timer: null, busy: false };

// Aksi yang boleh dilakukan per status job (selaras jobs_router).
const JOB_ACTIONS = {
  dead_letter: [["retry", "Retry", "refresh"]],
  queued:      [["cancel", "Cancel", "security"]],
  running:     [["pause", "Pause", "operations"], ["cancel", "Cancel", "security"]],
  paused:      [["resume", "Resume", "chat"], ["cancel", "Cancel", "security"]],
  pausing:     [["cancel", "Cancel", "security"]],
};
const JOB_FILTERS = ["dead_letter", "failed", "queued", "running", "paused", "completed", "all"];

export const RUNTIME_ROUTES = ["runtime"];

export function createRuntimeObservability(ctx) {
  const { el, setPage, toast, state, api } = ctx;

  const pct = (v) => `${Number(v || 0).toFixed(1)}%`;
  const score = (v) => (v == null ? "—" : Number(v).toFixed(3));

  function stopTimer() { if (RT.timer) { clearInterval(RT.timer); RT.timer = null; } }

  function queueChips(queue = {}) {
    const order = ["queued", "running", "paused", "completed", "failed", "dead_letter", "cancelled"];
    const chips = order
      .filter((k) => (queue[k] || 0) > 0)
      .map((k) => `<span class="status-badge ${k === "failed" || k === "dead_letter" ? "handoff" : k}">${esc(k.replace("_", " "))} · ${formatNumber(queue[k])}</span>`)
      .join(" ");
    return chips || `<span class="subtle">${t("common.status") || "No jobs"}</span>`;
  }

  function workersTable(workers = []) {
    if (!workers.length) return emptyState("No active workers", "No leased jobs are running right now.", "", "operations");
    const rows = workers.map((w) => `<tr>
      <td><span class="table-title mono">${esc(w.lease_owner || "—")}</span></td>
      <td>${formatNumber(w.active_jobs)}</td>
      <td>${w.lease_until ? relativeTime(w.lease_until) : "—"}</td></tr>`).join("");
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Worker (lease)</th><th>Active jobs</th><th>Lease expires</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function evalTable(rows = []) {
    if (!rows.length) return emptyState("No evaluations yet", "Scores appear after tasks complete with the Evaluation flag on.", "", "analytics");
    const body = rows.map((r) => `<tr>
      <td><span class="table-title">${esc(r.agent_name || "—")}</span></td>
      <td>${formatNumber(r.n)}</td>
      <td><strong>${score(r.avg_overall)}</strong></td>
      <td class="subtle">${score(r.min_overall)} – ${score(r.max_overall)}</td>
      <td>${pct(r.judged_pct)}</td>
      <td>${r.last_at ? relativeTime(r.last_at) : "—"}</td></tr>`).join("");
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Runs</th><th>Avg score</th><th>Min–Max</th><th>Judged</th><th>Last</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function jobsTable(jobs = []) {
    const filterSel = `<select class="select" data-job-filter aria-label="Job status filter">
      ${JOB_FILTERS.map((s) => `<option value="${s}" ${RT.jobStatus === s ? "selected" : ""}>${esc(s.replace("_", " "))}</option>`).join("")}</select>`;
    let table;
    if (!jobs.length) {
      table = emptyState("No jobs", `No ${RT.jobStatus === "all" ? "" : RT.jobStatus.replace("_", " ") + " "}jobs in this org.`, "", "workflow-builder");
    } else {
      const rows = jobs.map((j) => {
        const acts = (JOB_ACTIONS[j.status] || []).map(([a, label, ic]) =>
          `<button class="button button-sm" data-job-action="${a}" data-job-id="${esc(j.id)}">${icon(ic, 12)} ${label}</button>`).join(" ") || "—";
        const note = j.dlq_reason || j.last_error || "";
        return `<tr>
          <td><span class="table-title">${esc(j.agent_name || "—")}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(String(j.id).slice(0, 8))}</div></td>
          <td><span class="status-badge ${j.status === "failed" || j.status === "dead_letter" ? "handoff" : j.status}">${esc(String(j.status).replace("_", " "))}</span></td>
          <td>${esc(String(j.attempts ?? 0))}/${esc(String(j.max_attempts ?? "—"))}</td>
          <td class="subtle" title="${esc(note)}">${esc(note.slice(0, 60)) || "—"}</td>
          <td>${j.updated_at ? relativeTime(j.updated_at) : "—"}</td>
          <td><div style="display:flex;gap:6px;flex-wrap:wrap">${acts}</div></td></tr>`;
      }).join("");
      table = `<div class="table-wrap"><table class="data-table"><thead><tr><th>Job</th><th>Status</th><th>Attempts</th><th>Reason</th><th>Updated</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    }
    return `<div class="card"><div class="card-head"><div><h3>Jobs</h3><span class="subtle">Inspect & control durable jobs</span></div>${filterSel}</div>${table}</div>`;
  }

  function bodyHtml(health, evals, jobs) {
    const th = health.throughput || {};
    const ev = health.evaluation || {};
    const stalled = Number(health.stalled || 0);
    const dlq = Number(health.dead_letter || 0);
    const cards = [
      metricCard("Backlog", formatNumber(health.backlog), "Queued, waiting to run", "workflow-builder"),
      metricCard("In-flight", formatNumber(health.in_flight), "Running with a live lease", "operations"),
      metricCard("Stalled", formatNumber(stalled), "Lease expired — recovery due", "observability", stalled ? "trend-down" : "trend-up"),
      metricCard("Dead-letter", formatNumber(dlq), "Exhausted retries", "security", dlq ? "trend-down" : "trend-up"),
      metricCard("Success rate", pct(th.success_rate), `${formatNumber(th.completed_window)} done · ${formatNumber(th.failed_window)} failed`, "analytics", (th.success_rate || 0) >= 90 ? "trend-up" : "trend-down"),
      metricCard("Avg eval score", score(ev.avg_overall), `${formatNumber(ev.count)} scored · ${pct(ev.judged_pct)} judged`, "learning", (ev.avg_overall || 0) >= 0.8 ? "trend-up" : ""),
    ].join("");
    return `
      <div class="grid grid-3" style="margin-bottom:16px">${cards}</div>
      <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Queue</h3><span class="subtle">Jobs by status · last ${formatNumber(th.completed_1h)} completed in 1h</span></div></div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 2px">${queueChips(health.queue)}</div></div>
      <div class="grid grid-2" style="margin-bottom:16px">
        <div class="card"><div class="card-head"><div><h3>Workers</h3><span class="subtle">Active leases (durable runtime)</span></div></div>${workersTable(health.workers)}</div>
        <div class="card"><div class="card-head"><div><h3>Evaluation by agent</h3><span class="subtle">Quality scores, ${RT.windowHours}h window</span></div></div>${evalTable(evals)}</div>
      </div>
      ${jobsTable(jobs)}`;
  }

  async function refreshData({ silent = false } = {}) {
    if (RT.busy) return;
    RT.busy = true;
    try {
      const jobParams = RT.jobStatus === "all" ? { limit: 50 } : { status: RT.jobStatus, limit: 50 };
      const [health, evals, jobs] = await Promise.all([
        api.runtimeHealth(RT.windowHours),
        api.runtimeEvaluations(RT.windowHours),
        api.jobsList(jobParams).catch(() => []),
      ]);
      const body = el("#runtime-body");
      if (body) body.innerHTML = bodyHtml(health || {}, Array.isArray(evals) ? evals : [], Array.isArray(jobs) ? jobs : []);
      const dot = el("#runtime-live");
      if (dot) { dot.textContent = `Updated ${new Date().toLocaleTimeString("id-ID")}`; }
    } catch (e) {
      if (!silent) toast(e?.message || "Gagal memuat runtime ops", "error");
      const body = el("#runtime-body");
      if (body && !body.dataset.loaded) body.innerHTML = emptyState("Runtime data unavailable", esc(e?.message || "Endpoint /api/runtime tidak dapat diakses."), "", "observability");
    } finally {
      const body = el("#runtime-body");
      if (body) body.dataset.loaded = "1";
      RT.busy = false;
    }
  }

  async function runJobAction(action, id) {
    const fn = { retry: api.jobRetry, cancel: api.jobCancel, pause: api.jobPause, resume: api.jobResume }[action];
    if (!fn) return;
    if (action === "cancel" && !window.confirm("Batalkan job ini? Aksi tidak bisa dibatalkan.")) return;
    try {
      const res = await fn(id);
      toast(`Job ${action} → ${res?.status || "ok"}`, "success");
      await refreshData({ silent: true });
    } catch (e) {
      toast(e?.message || `Gagal ${action} job`, "error");
    }
  }

  function bind() {
    el("[data-rt-refresh]")?.addEventListener("click", () => refreshData());
    el("[data-rt-window]")?.addEventListener("change", (e) => {
      RT.windowHours = Number(e.target.value) || 24;
      refreshData();
    });
    // Delegasi pada #runtime-body (innerHTML-nya diganti tiap refresh, node tetap).
    const bodyEl = el("#runtime-body");
    bodyEl?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-job-action]");
      if (btn) runJobAction(btn.getAttribute("data-job-action"), btn.getAttribute("data-job-id"));
    });
    bodyEl?.addEventListener("change", (e) => {
      const sel = e.target.closest("[data-job-filter]");
      if (sel) { RT.jobStatus = sel.value; refreshData(); }
    });
    stopTimer();
    // Auto-refresh tiap 5s selama route aktif; berhenti otomatis saat pindah route.
    RT.timer = setInterval(() => {
      if (state.route !== "runtime" || !el("#runtime-body")) { stopTimer(); return; }
      refreshData({ silent: true });
    }, 5000);
  }

  async function renderRuntime() {
    const windowSel = `<select class="select" data-rt-window aria-label="Time window">
      ${[[1, "1 hour"], [24, "24 hours"], [168, "7 days"], [720, "30 days"]]
        .map(([v, l]) => `<option value="${v}" ${RT.windowHours === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    const actions = `<span id="runtime-live" class="subtle" style="align-self:center"></span>${windowSel}<button class="button" data-rt-refresh>${icon("refresh", 14)} Refresh</button>`;
    setPage(`${pageHeader(t("route.runtime.title"), t("route.runtime.desc"), actions)}
      <div id="runtime-body">${skeletonCards(6)}</div>`);
    bind();
    await refreshData();
  }

  return { runtime: renderRuntime };
}
