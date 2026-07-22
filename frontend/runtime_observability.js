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

const RT = { windowHours: 24, timer: null, busy: false };

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

  function bodyHtml(health, evals) {
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
      <div class="grid grid-2">
        <div class="card"><div class="card-head"><div><h3>Workers</h3><span class="subtle">Active leases (durable runtime)</span></div></div>${workersTable(health.workers)}</div>
        <div class="card"><div class="card-head"><div><h3>Evaluation by agent</h3><span class="subtle">Quality scores, ${RT.windowHours}h window</span></div></div>${evalTable(evals)}</div>
      </div>`;
  }

  async function refreshData({ silent = false } = {}) {
    if (RT.busy) return;
    RT.busy = true;
    try {
      const [health, evals] = await Promise.all([
        api.runtimeHealth(RT.windowHours),
        api.runtimeEvaluations(RT.windowHours),
      ]);
      const body = el("#runtime-body");
      if (body) body.innerHTML = bodyHtml(health || {}, Array.isArray(evals) ? evals : []);
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

  function bind() {
    el("[data-rt-refresh]")?.addEventListener("click", () => refreshData());
    el("[data-rt-window]")?.addEventListener("change", (e) => {
      RT.windowHours = Number(e.target.value) || 24;
      refreshData();
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
