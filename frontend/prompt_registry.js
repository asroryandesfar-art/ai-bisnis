/* Prompt Registry — operator panel for the P2-B prompt management API
 * (/api/prompts). Self-contained + dependency-injected like web_intelligence.js:
 * createPromptRegistry(ctx) returns a { route: renderFn } map app.js spreads in.
 *
 * Manage agent prompt versions per tenant: list names, list versions, create a
 * version, activate (rollback = exclusive) or A/B (non-exclusive), deactivate, and
 * preview which version resolves. Scope = exactly what the API supports; no mock.
 */
import { t } from "/ui/i18n.js?v=20260723-pr-1";
import { esc, icon, pageHeader, emptyState, skeletonCards, relativeTime, statusBadge } from "/ui/components.js?v=20260723-pr-1";

const PR = { name: "", names: [], versions: [], busy: false };

export const PROMPT_ROUTES = ["prompts"];

export function createPromptRegistry(ctx) {
  const { el, setPage, toast, state, api } = ctx;

  const short = (s, n = 90) => { const x = String(s || ""); return x.length > n ? x.slice(0, n) + "…" : x; };

  function namesList() {
    if (!PR.names.length) {
      return emptyState("No prompt overrides", "Agents use their built-in prompts. Create a version below to override one (e.g. name \"cs_agent.system\").", "", "prompts");
    }
    return PR.names.map((r) => `
      <button class="card card-hover" data-pr-pick="${esc(r.name)}" style="text-align:left;cursor:pointer;display:block;width:100%;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <strong class="mono">${esc(r.name)}</strong>
          ${r.active_versions ? statusBadge("active", `${r.active_versions} active`) : statusBadge("paused", "none active")}
        </div>
        <div class="subtle" style="margin-top:4px">${r.versions} version${r.versions === 1 ? "" : "s"} · ${r.variants} variant${r.variants === 1 ? "" : "s"} · ${r.updated_at ? relativeTime(r.updated_at) : "—"}</div>
      </button>`).join("");
  }

  function versionsTable() {
    if (!PR.name) return emptyState("Select a prompt", "Pick a prompt on the left, or create one below.", "", "prompts");
    if (!PR.versions.length) return emptyState("No versions", `"${PR.name}" has no versions yet.`, "", "prompts");
    const rows = PR.versions.map((v) => {
      const acts = [
        `<button class="button button-sm" data-pr-act="rollback" data-pr-ver="${v.version}" data-pr-variant="${esc(v.variant)}" title="Activate exclusively (rollback)">${icon("refresh", 12)} Activate</button>`,
        `<button class="button button-sm" data-pr-act="ab" data-pr-ver="${v.version}" data-pr-variant="${esc(v.variant)}" title="Activate alongside others (A/B)">${icon("analytics", 12)} A/B</button>`,
        v.active ? `<button class="button button-sm" data-pr-act="deactivate" data-pr-variant="${esc(v.variant)}">${icon("security", 12)} Off</button>` : "",
      ].filter(Boolean).join(" ");
      return `<tr>
        <td>${esc(v.variant)}</td>
        <td>v${v.version}</td>
        <td>${v.active ? statusBadge("active", "active") : `<span class="subtle">—</span>`}</td>
        <td>${esc(String(v.weight))}</td>
        <td class="subtle" title="${esc(v.content)}">${esc(short(v.content))}</td>
        <td>${v.created_at ? relativeTime(v.created_at) : "—"}</td>
        <td><div style="display:flex;gap:6px;flex-wrap:wrap">${acts}</div></td></tr>`;
    }).join("");
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Variant</th><th>Version</th><th>State</th><th>Weight</th><th>Content</th><th>Created</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function bodyHtml() {
    return `
      <div class="grid grid-2" style="align-items:start">
        <div class="card"><div class="card-head"><div><h3>Prompts</h3><span class="subtle">Overrides in this tenant</span></div><button class="button button-sm" data-pr-refresh>${icon("refresh", 12)} Refresh</button></div>
          <div id="pr-names">${namesList()}</div></div>
        <div class="card"><div class="card-head"><div><h3>${PR.name ? esc(PR.name) : "Versions"}</h3><span class="subtle">${PR.name ? "Rollback = exclusive · A/B = keep others" : "Select a prompt"}</span></div>${PR.name ? `<button class="button button-sm" data-pr-resolve>${icon("chat", 12)} Resolve</button>` : ""}</div>
          <div id="pr-versions">${versionsTable()}</div></div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Create version</h3><span class="subtle">New version for a prompt name (creates the name if new)</span></div></div>
        <form id="pr-create" style="display:grid;gap:10px;max-width:760px">
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <input class="input mono" name="name" placeholder="prompt name e.g. cs_agent.system" list="pr-name-list" value="${esc(PR.name)}" required style="flex:2;min-width:220px">
            <input class="input" name="variant" placeholder="variant (default)" value="default" style="flex:1;min-width:120px">
            <input class="input" name="weight" type="number" min="1" value="100" title="A/B weight" style="width:110px">
          </div>
          <datalist id="pr-name-list">${PR.names.map((r) => `<option value="${esc(r.name)}"></option>`).join("")}</datalist>
          <textarea class="input" name="content" rows="6" placeholder="Prompt content…" required></textarea>
          <label style="display:flex;align-items:center;gap:8px"><input type="checkbox" name="activate"> Activate immediately (rollback to this version)</label>
          <div><button class="button button-primary" type="submit">${icon("prompts", 14)} Create version</button></div>
        </form></div>`;
  }

  async function loadNames() {
    try { PR.names = await api.promptNames() || []; } catch (_) { PR.names = []; }
  }
  async function loadVersions() {
    if (!PR.name) { PR.versions = []; return; }
    try { PR.versions = await api.promptVersions(PR.name) || []; } catch (_) { PR.versions = []; }
  }

  function repaint() {
    const namesEl = el("#pr-names"); if (namesEl) namesEl.innerHTML = namesList();
    const versEl = el("#pr-versions"); if (versEl) versEl.innerHTML = versionsTable();
    const head = el("#pr-versions")?.closest(".card")?.querySelector(".card-head h3");
    if (head) head.textContent = PR.name || "Versions";
  }

  async function pick(name) { PR.name = name; await loadVersions(); repaint(); }

  async function doAction(act, ver, variant) {
    try {
      if (act === "rollback") await api.promptActivate(PR.name, { version: Number(ver), variant, exclusive: true });
      else if (act === "ab") await api.promptActivate(PR.name, { version: Number(ver), variant, exclusive: false });
      else if (act === "deactivate") await api.promptDeactivate(PR.name, variant);
      toast(`Prompt ${act} ok`, "success");
      await Promise.all([loadVersions(), loadNames()]);
      repaint();
    } catch (e) { toast(e?.message || `Gagal ${act}`, "error"); }
  }

  async function resolvePreview() {
    try {
      const r = await api.promptResolve(PR.name, "");
      toast(`Resolves → ${r.source === "default" ? "built-in default" : `v${r.version} (${r.variant})`}`, "success");
    } catch (e) { toast(e?.message || "Resolve gagal", "error"); }
  }

  function bind() {
    const root = el("#prompts-body");
    root?.addEventListener("click", (e) => {
      const pickBtn = e.target.closest("[data-pr-pick]");
      if (pickBtn) return pick(pickBtn.getAttribute("data-pr-pick"));
      const actBtn = e.target.closest("[data-pr-act]");
      if (actBtn) return doAction(actBtn.getAttribute("data-pr-act"), actBtn.getAttribute("data-pr-ver"), actBtn.getAttribute("data-pr-variant"));
      if (e.target.closest("[data-pr-refresh]")) return refreshAll();
      if (e.target.closest("[data-pr-resolve]")) return resolvePreview();
    });
    root?.addEventListener("submit", async (e) => {
      const form = e.target.closest("#pr-create");
      if (!form) return;
      e.preventDefault();
      const fd = new FormData(form);
      const name = String(fd.get("name") || "").trim();
      const content = String(fd.get("content") || "").trim();
      if (!name || !content) { toast("Nama & konten wajib", "error"); return; }
      try {
        await api.promptCreateVersion(name, {
          content, variant: String(fd.get("variant") || "default").trim() || "default",
          weight: Number(fd.get("weight")) || 100, activate: !!fd.get("activate"),
        });
        toast("Versi dibuat", "success");
        PR.name = name;
        await Promise.all([loadNames(), loadVersions()]);
        repaint();
        form.querySelector('[name="content"]').value = "";
      } catch (err) { toast(err?.message || "Gagal membuat versi", "error"); }
    });
  }

  async function refreshAll() {
    await Promise.all([loadNames(), loadVersions()]);
    const b = el("#prompts-body"); if (b) b.innerHTML = bodyHtml();
  }

  async function renderPrompts() {
    setPage(`${pageHeader(t("route.prompts.title"), t("route.prompts.desc"),
      `<button class="button" data-pr-refresh>${icon("refresh", 14)} Refresh</button>`)}
      <div id="prompts-body">${skeletonCards(2)}</div>`);
    // header refresh button is outside #prompts-body → bind directly
    el("[data-pr-refresh]")?.addEventListener("click", () => refreshAll());
    await loadNames();
    await loadVersions();
    const b = el("#prompts-body"); if (b) b.innerHTML = bodyHtml();
    bind();
  }

  return { prompts: renderPrompts };
}
