/* Web Intelligence — enterprise workspace for the backend/modules/web_intelligence
 * module. Self-contained + dependency-injected: the app shell passes in its local
 * primitives (el/setPage/toast/state/api) via createWebIntelligence(ctx); view
 * helpers come from components.js/i18n.js. Returns a { route: renderFn } map that
 * app.js spreads into its renderers table.
 *
 * Scope = ONLY what the real API supports (status/read/crawl/screenshot/ingest/
 * cache-clear). No mock data. Tabs without a backend (Search, Scheduler, Browser
 * Automation actions, Job History/Queue) are intentionally not shipped.
 */
import { t } from "/ui/i18n.js?v=20260721-wi-1";
import { esc, icon, pageHeader, metricCard, statusBadge, skeletonCards, relativeTime } from "/ui/components.js?v=20260721-wi-1";

// Module-scoped UI state (client-side only; no fake persistence).
const wiState = {
  status: null,            // cached GET /status payload
  statusTs: 0,
  prefillUrl: "",          // cross-tab hand-off (e.g. "Add to Knowledge")
  lastScreenshotUrl: null, // object URL to revoke
  abort: null,             // in-flight AbortController
  cancelled: false,
};

const WI_ROUTES = [
  "web-intelligence", "wi-scraper", "wi-crawl", "wi-extract",
  "wi-knowledge", "wi-verify", "wi-screenshot", "wi-settings",
];

export function createWebIntelligence(ctx) {
  const { el, setPage, toast, state, api } = ctx;

  // ── small shared helpers ────────────────────────────────────────────────
  const takePrefill = () => { const u = wiState.prefillUrl; wiState.prefillUrl = ""; return u; };
  const go = (route, url) => { if (url) wiState.prefillUrl = url; location.hash = `#${route}`; };

  function cancelInflight() {
    if (wiState.abort) { wiState.cancelled = true; try { wiState.abort.abort(); } catch (_) {} wiState.abort = null; }
  }
  function newAbort() { cancelInflight(); wiState.cancelled = false; wiState.abort = new AbortController(); return wiState.abort.signal; }

  async function getStatus(force = false) {
    if (!force && wiState.status && Date.now() - wiState.statusTs < 30000) return wiState.status;
    const s = await api.webIntelStatus();
    wiState.status = s; wiState.statusTs = Date.now();
    return s;
  }

  // A read/extract result → HTML. `formats` picks which output panes to show.
  function readResultHtml(res, { formats } = {}) {
    if (!res || res.success === false) {
      return emptyState("alert", t('wi.result_failed'), esc(res?.error || t('wi.result_failed_desc')));
    }
    const conf = res.confidence || {};
    const cite = res.citation || {};
    const mon = res.monitoring || {};
    const meta = res.metadata || {};
    const showAll = !formats;
    const has = (k) => showAll || formats.includes(k);
    const panes = [];
    if (has("markdown") && res.markdown) panes.push(pane(t('wi.fmt_markdown'), preBlock(res.markdown)));
    if (has("text") && res.text) panes.push(pane(t('wi.fmt_text'), preBlock(res.text)));
    if (has("json")) panes.push(pane(t('wi.fmt_json'), preBlock(JSON.stringify(res, null, 2))));
    if (has("tables") && (res.tables || []).length) panes.push(pane(`${t('wi.fmt_tables')} (${res.tables.length})`, preBlock(JSON.stringify(res.tables, null, 2))));
    if (has("metadata") && Object.keys(meta).length) panes.push(pane(t('wi.fmt_metadata'), kvGrid(meta)));
    if (has("images") && (res.images || []).length) panes.push(pane(`${t('wi.fmt_images')} (${res.images.length})`, imageStrip(res.images)));

    const confBadge = conf.level
      ? `<span class="status-badge ${confLevelKind(conf.level)}">${t('wi.confidence')}: ${Math.round((conf.score || 0) * 100)}% · ${esc(conf.level)}</span>` : "";
    return `<div class="card" style="margin-top:14px"><div class="card-head">
        <div><h3 style="word-break:break-word">${esc(res.title || res.final_url || res.url)}</h3>
          <span class="subtle mono" style="font-size:11px;word-break:break-all">${esc(res.final_url || res.url)}</span></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${confBadge}
          <span class="status-badge default">${esc(res.method || "—")}</span>
          ${res.rendered ? `<span class="status-badge pending">JS</span>` : ""}</div></div>
      <div class="card-body" style="display:grid;gap:14px">
        <div class="grid grid-4">
          ${miniStat(t('wi.mon_status'), esc(mon.status || "ok"))}
          ${miniStat(t('wi.mon_chars'), Number(mon.content_chars || (res.text || "").length).toLocaleString("id-ID"))}
          ${miniStat(t('wi.mon_bytes'), fmtBytes(mon.bytes))}
          ${miniStat(t('wi.mon_duration'), `${mon.duration_ms ?? "—"} ms`)}
        </div>
        ${panes.join("")}
        <div style="display:flex;gap:8px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:12px">
          <a class="button button-sm" href="${esc(res.final_url || res.url)}" target="_blank" rel="noopener">${icon('arrow',13)} ${t('wi.action_open')}</a>
          <button class="button button-sm" data-wi-nav="wi-extract" data-wi-url="${esc(res.url)}">${icon('improvement',13)} ${t('wi.action_extract')}</button>
          <button class="button button-sm" data-wi-nav="wi-verify" data-wi-url="${esc(res.url)}">${icon('security',13)} ${t('wi.action_verify')}</button>
          <button class="button button-primary button-sm" data-wi-nav="wi-knowledge" data-wi-url="${esc(res.url)}">${icon('knowledge',13)} ${t('wi.action_to_kb')}</button>
        </div>
      </div></div>`;
  }

  function wireResultNav(root) {
    (root || document).querySelectorAll("[data-wi-nav]").forEach((b) => {
      if (b._wiBound) return; b._wiBound = true;
      b.addEventListener("click", () => go(b.getAttribute("data-wi-nav"), b.getAttribute("data-wi-url") || ""));
    });
  }

  // ── 1 · DASHBOARD ───────────────────────────────────────────────────────
  async function renderWiDashboard() {
    setPage(`${pageHeader(t('route.web-intelligence.title'), t('route.web-intelligence.desc'), refreshBtn())}
      <div id="wi-dash">${skeletonCards(4)}</div>`);
    bindRefresh(renderWiDashboard);
    let s;
    try { s = await getStatus(true); }
    catch (e) { el("#wi-dash").innerHTML = emptyState("alert", t('wi.status_unreachable'), esc(e.message)); return; }
    const caps = s.capabilities || {};
    const capKeys = Object.keys(caps);
    const active = capKeys.filter((k) => caps[k]).length;
    const cache = s.cache || {};
    const cards = [
      metricCard(t('wi.card_engines'), `${active}<span class="subtle" style="font-size:14px">/${capKeys.length}</span>`, t('wi.card_engines_meta'), "observability"),
      metricCard(t('wi.card_js'), caps.js_render_playwright ? t('wi.on') : t('wi.off'), t('wi.card_js_meta'), "multimedia", caps.js_render_playwright ? "up" : ""),
      metricCard(t('wi.card_cache_entries'), Number(cache.entries || 0).toLocaleString("id-ID"), `${t('wi.card_cache_meta')} ${cache.max_entries || 0}`, "knowledge"),
      metricCard(t('wi.card_hitrate'), `${Math.round((cache.hit_rate || 0) * 100)}%`, `${cache.hits || 0} hit · ${cache.misses || 0} miss`, "analytics"),
    ].join("");
    const capRows = capKeys.map((k) => `<div class="wi-cap"><span class="wi-cap-dot ${caps[k] ? 'on' : 'off'}"></span><span>${esc(capLabel(k))}</span>${statusBadge(caps[k] ? 'active' : 'default', caps[k] ? t('wi.on') : t('wi.off'))}</div>`).join("");
    const launch = [
      ["wi-scraper", "improvement", t('nav.item.wi-scraper'), t('wi.launch_scraper')],
      ["wi-crawl", "workflow-builder", t('nav.item.wi-crawl'), t('wi.launch_crawl')],
      ["wi-knowledge", "knowledge", t('nav.item.wi-knowledge'), t('wi.launch_knowledge')],
      ["wi-verify", "security", t('nav.item.wi-verify'), t('wi.launch_verify')],
      ["wi-screenshot", "multimedia", t('nav.item.wi-screenshot'), t('wi.launch_screenshot')],
      ["wi-extract", "kb-builder", t('nav.item.wi-extract'), t('wi.launch_extract')],
    ].map(([r, ic, title, desc]) => `<button class="card card-hover wi-launch" data-wi-nav="${r}" style="text-align:left;cursor:pointer">
        <span class="metric-icon">${icon(ic, 18)}</span>
        <strong style="display:block;margin-top:8px">${esc(title)}</strong>
        <span class="subtle" style="font-size:12px">${esc(desc)}</span></button>`).join("");
    el("#wi-dash").innerHTML = `
      <div class="grid grid-4">${cards}</div>
      <div class="grid grid-2" style="margin-top:16px;gap:16px">
        <div class="card"><div class="card-head"><h3>${t('wi.system_health')}</h3><span class="subtle">${active}/${capKeys.length} ${t('wi.engines_active')}</span></div>
          <div class="card-body"><div class="wi-cap-grid">${capRows}</div></div></div>
        <div class="card"><div class="card-head"><h3>${t('wi.cache_title')}</h3></div>
          <div class="card-body"><div class="wi-cap-grid">
            ${infoRow(t('wi.cache_entries'), `${cache.entries || 0} / ${cache.max_entries || 0}`)}
            ${infoRow(t('wi.cache_ttl'), `${cache.ttl_seconds || 0}s`)}
            ${infoRow(t('wi.cache_hitrate'), `${Math.round((cache.hit_rate || 0) * 100)}%`)}
          </div><div style="margin-top:12px"><button class="button button-sm" data-wi-nav="wi-settings">${icon('settings',13)} ${t('wi.manage_cache')}</button></div></div></div>
      </div>
      <div style="margin-top:20px"><div class="page-section-label">${t('wi.quick_launch')}</div>
        <div class="wi-launch-grid">${launch}</div></div>`;
    wireResultNav(el("#wi-dash"));
  }

  // ── 2 · WEB SCRAPER ─────────────────────────────────────────────────────
  async function renderWiScraper() {
    const prefill = takePrefill();
    setPage(`${pageHeader(t('route.wi-scraper.title'), t('route.wi-scraper.desc'))}
      <div class="card"><div class="card-body"><form id="wi-scraper-form" style="display:grid;gap:14px">
        <label class="field full"><span>${t('wi.urls_label')} <span class="subtle">(${t('wi.urls_hint')})</span></span>
          <textarea name="urls" rows="3" required placeholder="https://example.com&#10;https://example.org/artikel">${esc(prefill)}</textarea></label>
        <div class="wi-opts">
          ${selectField("output", t('wi.output_format'), [["markdown","Markdown"],["json","JSON"],["text","Text"]])}
          ${checkField("include_tables", t('wi.opt_tables'), true)}
          ${checkField("include_images", t('wi.opt_images'), false)}
          ${checkField("include_links", t('wi.opt_links'), false)}
          ${checkField("render_js", t('wi.opt_js'), false)}
          ${checkField("use_cache", t('wi.opt_cache'), true)}
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="button" type="button" data-wi-cancel disabled>${t('wi.cancel')}</button>
          <button class="button button-primary" type="submit">${icon('search',14)} ${t('wi.start_scrape')}</button>
        </div>
      </form></div></div>
      <div id="wi-scraper-progress"></div>
      <div id="wi-scraper-out"></div>`);

    const form = el("#wi-scraper-form");
    const cancelBtn = el("[data-wi-cancel]");
    cancelBtn?.addEventListener("click", () => { cancelInflight(); });
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const urls = String(fd.get("urls") || "").split(/\r?\n/).map((u) => u.trim()).filter(Boolean);
      if (!urls.length) return;
      const opts = {
        output: fd.get("output") || "markdown",
        include_tables: fd.get("include_tables") === "on",
        include_images: fd.get("include_images") === "on",
        include_links: fd.get("include_links") === "on",
        render_js: fd.get("render_js") === "on",
        use_cache: fd.get("use_cache") === "on",
      };
      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true; cancelBtn.disabled = false;
      const out = el("#wi-scraper-out"); out.innerHTML = "";
      const prog = el("#wi-scraper-progress");
      const signal = newAbort();
      let done = 0;
      try {
        for (const url of urls) {
          prog.innerHTML = progressBar(done, urls.length, url);
          let res;
          try { res = await api.webIntelRead({ url, ...opts }, signal); }
          catch (err) {
            if (wiState.cancelled) break;
            res = { success: false, url, error: err.message };
          }
          out.insertAdjacentHTML("beforeend", readResultHtml(res, { formats: [opts.output === "json" ? "json" : opts.output, "metadata", ...(opts.include_tables ? ["tables"] : []), ...(opts.include_images ? ["images"] : [])] }));
          wireResultNav(out);
          done += 1;
          if (wiState.cancelled) break;
        }
        prog.innerHTML = wiState.cancelled
          ? `<div class="wi-note">${t('wi.cancelled')} (${done}/${urls.length})</div>`
          : progressBar(done, urls.length, "", true);
        if (!wiState.cancelled) toast(`${done} URL ${t('wi.scrape_done')}`, "success");
      } finally {
        submitBtn.disabled = false; cancelBtn.disabled = true; wiState.abort = null;
      }
    });
  }

  // ── 3 · WEBSITE CRAWL ───────────────────────────────────────────────────
  async function renderWiCrawl() {
    const prefill = takePrefill();
    setPage(`${pageHeader(t('route.wi-crawl.title'), t('route.wi-crawl.desc'))}
      <div class="card"><div class="card-body"><form id="wi-crawl-form" style="display:grid;gap:14px">
        <label class="field full"><span>${t('wi.seed_url')}</span>
          <input class="input" name="url" required placeholder="https://example.com" value="${esc(prefill)}"></label>
        <div class="wi-opts">
          ${numField("max_depth", t('wi.max_depth'), 1, 0, 4)}
          ${numField("max_pages", t('wi.max_pages'), 10, 1, 100)}
          ${numField("rate_limit_seconds", t('wi.rate_limit'), 1, 0, 10, 0.5)}
          ${checkField("same_site_only", t('wi.same_site'), true)}
          ${checkField("respect_robots", t('wi.respect_robots'), true)}
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="button" type="button" data-wi-cancel disabled>${t('wi.cancel')}</button>
          <button class="button button-primary" type="submit">${icon('workflow-builder',14)} ${t('wi.start_crawl')}</button>
        </div>
      </form></div></div>
      <div id="wi-crawl-out"></div>`);
    const form = el("#wi-crawl-form");
    const cancelBtn = el("[data-wi-cancel]");
    cancelBtn?.addEventListener("click", () => cancelInflight());
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const body = {
        url: String(fd.get("url") || "").trim(),
        max_depth: Number(fd.get("max_depth")) || 1,
        max_pages: Number(fd.get("max_pages")) || 10,
        rate_limit_seconds: Number(fd.get("rate_limit_seconds")) || 1,
        same_site_only: fd.get("same_site_only") === "on",
        respect_robots: fd.get("respect_robots") === "on",
      };
      if (!body.url) return;
      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true; cancelBtn.disabled = false;
      const out = el("#wi-crawl-out");
      out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-body">${busy(t('wi.crawling'))}<div class="subtle" style="font-size:12px;margin-top:6px">${t('wi.crawl_no_stream')}</div></div></div>`;
      const signal = newAbort();
      try {
        const res = await api.webIntelCrawl(body, signal);
        const docs = res.documents || [];
        const stats = res.stats || {};
        if (!docs.length) { out.innerHTML = emptyState("search", t('wi.crawl_empty'), t('wi.crawl_empty_desc')); return; }
        const rows = docs.map((d) => `<tr>
            <td style="max-width:340px"><strong>${esc((d.title || "—").slice(0, 90))}</strong><br><span class="subtle mono" style="font-size:10px;word-break:break-all">${esc(d.url)}</span></td>
            <td><span class="status-badge default">${esc(d.method || "—")}</span></td>
            <td>${d.confidence ? Math.round((d.confidence.score || 0) * 100) + "%" : "—"}</td>
            <td>${Number((d.text || "").length).toLocaleString("id-ID")}</td>
            <td><button class="button button-sm" data-wi-nav="wi-knowledge" data-wi-url="${esc(d.url)}">${t('wi.action_to_kb')}</button></td>
          </tr>`).join("");
        out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-head"><h3>${t('wi.crawl_result')}</h3>
            <span class="subtle">${docs.length} ${t('wi.pages')}</span></div>
          <div class="card-body">
            <div class="grid grid-4">
              ${miniStat(t('wi.pages_fetched'), stats.fetched ?? docs.length)}
              ${miniStat(t('wi.pages_visited'), stats.visited ?? "—")}
              ${miniStat(t('wi.crawl_errors'), stats.errors ?? 0)}
              ${miniStat(t('wi.mon_duration'), stats.duration_ms != null ? `${stats.duration_ms} ms` : "—")}
            </div>
            <div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr>
              <th>${t('wi.col_page')}</th><th>${t('wi.col_method')}</th><th>${t('wi.confidence')}</th><th>${t('wi.col_chars')}</th><th></th>
            </tr></thead><tbody>${rows}</tbody></table></div>
          </div></div>`;
        wireResultNav(out);
        toast(`${docs.length} ${t('wi.crawl_toast')}`, "success");
      } catch (err) {
        if (wiState.cancelled) { out.innerHTML = `<div class="wi-note" style="margin-top:14px">${t('wi.cancelled')}</div>`; }
        else { out.innerHTML = emptyState("alert", t('wi.crawl_failed'), esc(err.message)); toast(err.message, "error"); }
      } finally {
        submitBtn.disabled = false; cancelBtn.disabled = true; wiState.abort = null;
      }
    });
  }

  // ── 4 · CONTENT EXTRACTION ──────────────────────────────────────────────
  async function renderWiExtract() {
    const prefill = takePrefill();
    setPage(`${pageHeader(t('route.wi-extract.title'), t('route.wi-extract.desc'))}
      <div class="card"><div class="card-body"><form id="wi-extract-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
        <label class="field" style="flex:1;min-width:260px"><span>${t('wi.url')}</span>
          <input class="input" name="url" required placeholder="https://example.com/artikel" value="${esc(prefill)}"></label>
        ${checkField("render_js", t('wi.opt_js'), false)}
        <button class="button button-primary" type="submit">${icon('improvement',14)} ${t('wi.extract_now')}</button>
      </form></div></div>
      <div class="subtle" style="font-size:12px;margin:8px 2px">${t('wi.extract_note')}</div>
      <div id="wi-extract-out"></div>`);
    const form = el("#wi-extract-form");
    if (prefill) form?.requestSubmit?.();
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const url = String(fd.get("url") || "").trim(); if (!url) return;
      const submitBtn = form.querySelector('button[type="submit"]'); submitBtn.disabled = true;
      const out = el("#wi-extract-out"); out.innerHTML = skeletonCards(2);
      try {
        const res = await api.webIntelRead({ url, output: "markdown", include_tables: true, include_images: true, include_links: true, render_js: fd.get("render_js") === "on" });
        out.innerHTML = readResultHtml(res); // all formats
        wireResultNav(out);
      } catch (err) { out.innerHTML = emptyState("alert", t('wi.result_failed'), esc(err.message)); toast(err.message, "error"); }
      finally { submitBtn.disabled = false; }
    });
  }

  // ── 5 · KNOWLEDGE BUILDER ───────────────────────────────────────────────
  async function renderWiKnowledge() {
    const prefill = takePrefill();
    const bots = state.bots || [];
    if (!bots.length) {
      setPage(`${pageHeader(t('route.wi-knowledge.title'), t('route.wi-knowledge.desc'))}
        ${emptyState("agents", t('wi.kb_no_bot'), t('wi.kb_no_bot_desc'))}`);
      return;
    }
    const botOpts = bots.map((b) => `<option value="${esc(b.id)}" ${b.id === (state.selectedBotId || bots[0].id) ? "selected" : ""}>${esc(b.name)}</option>`).join("");
    setPage(`${pageHeader(t('route.wi-knowledge.title'), t('route.wi-knowledge.desc'))}
      <div class="card"><div class="card-body"><form id="wi-kb-form" style="display:grid;gap:14px">
        <div class="wi-opts">
          <label class="field"><span>${t('wi.target_bot')}</span><select class="input" name="bot_id">${botOpts}</select></label>
          <label class="field"><span>${t('wi.category')}</span><input class="input" name="category" value="web_intelligence" maxlength="80"></label>
        </div>
        <label class="field full"><span>${t('wi.seed_url')}</span>
          <input class="input" name="url" required placeholder="https://example.com" value="${esc(prefill)}"></label>
        <div class="wi-opts">
          ${numField("max_depth", t('wi.max_depth'), 1, 0, 4)}
          ${numField("max_pages", t('wi.max_pages'), 5, 1, 100)}
          ${checkField("respect_robots", t('wi.respect_robots'), true)}
        </div>
        <div class="wi-note">${icon('security',13)} ${t('wi.kb_auto_note')}</div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="button" type="button" data-wi-preview>${icon('search',14)} ${t('wi.preview')}</button>
          <button class="button button-primary" type="submit">${icon('knowledge',14)} ${t('wi.save_to_kb')}</button>
        </div>
      </form></div></div>
      <div id="wi-kb-out"></div>`);
    const form = el("#wi-kb-form");
    const readBody = () => {
      const fd = new FormData(form);
      return {
        bot_id: fd.get("bot_id"),
        url: String(fd.get("url") || "").trim(),
        category: String(fd.get("category") || "web_intelligence"),
        max_depth: Number(fd.get("max_depth")) || 1,
        max_pages: Number(fd.get("max_pages")) || 5,
        respect_robots: fd.get("respect_robots") === "on",
      };
    };
    el("[data-wi-preview]")?.addEventListener("click", async () => {
      const b = readBody(); if (!b.url) return toast(t('wi.need_url'), "error");
      const out = el("#wi-kb-out"); out.innerHTML = skeletonCards(2);
      try {
        const res = await api.webIntelRead({ url: b.url, output: "markdown", include_tables: true });
        out.innerHTML = `<div class="wi-note" style="margin-top:14px">${t('wi.kb_preview_note')}</div>` + readResultHtml(res, { formats: ["markdown", "metadata"] });
        wireResultNav(out);
      } catch (err) { out.innerHTML = emptyState("alert", t('wi.result_failed'), esc(err.message)); }
    });
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const b = readBody(); if (!b.url) return;
      const submitBtn = form.querySelector('button[type="submit"]'); submitBtn.disabled = true;
      const out = el("#wi-kb-out"); out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-body">${busy(t('wi.ingesting'))}</div></div>`;
      try {
        const { bot_id, ...body } = b;
        const res = await api.webIntelIngest(bot_id, body);
        out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-head"><h3>${t('wi.kb_saved')}</h3>
            ${statusBadge('active', `${res.documents_saved || 0} ${t('wi.docs')}`)}</div>
          <div class="card-body"><div class="grid grid-4">
            ${miniStat(t('wi.kb_extracted'), res.documents_extracted ?? 0)}
            ${miniStat(t('wi.kb_saved_docs'), res.documents_saved ?? 0)}
            ${miniStat(t('wi.kb_chunks'), res.total_chunks ?? 0)}
            ${miniStat(t('wi.mon_duration'), res.monitoring?.total_duration_ms != null ? `${res.monitoring.total_duration_ms} ms` : "—")}
          </div></div></div>`;
        toast(`${res.documents_saved || 0} ${t('wi.kb_toast')}`, "success");
      } catch (err) { out.innerHTML = emptyState("alert", t('wi.kb_failed'), esc(err.message)); toast(err.message, "error"); }
      finally { submitBtn.disabled = false; }
    });
  }

  // ── 6 · SOURCE VERIFICATION ─────────────────────────────────────────────
  async function renderWiVerify() {
    const prefill = takePrefill();
    setPage(`${pageHeader(t('route.wi-verify.title'), t('route.wi-verify.desc'))}
      <div class="card"><div class="card-body"><form id="wi-verify-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
        <label class="field" style="flex:1;min-width:260px"><span>${t('wi.url')}</span>
          <input class="input" name="url" required placeholder="https://example.com/artikel" value="${esc(prefill)}"></label>
        <button class="button button-primary" type="submit">${icon('security',14)} ${t('wi.verify_now')}</button>
      </form></div></div>
      <div id="wi-verify-out"></div>`);
    const form = el("#wi-verify-form");
    if (prefill) form?.requestSubmit?.();
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = String(new FormData(form).get("url") || "").trim(); if (!url) return;
      const submitBtn = form.querySelector('button[type="submit"]'); submitBtn.disabled = true;
      const out = el("#wi-verify-out"); out.innerHTML = skeletonCards(2);
      try {
        const res = await api.webIntelRead({ url, output: "text" });
        if (res.success === false) { out.innerHTML = emptyState("alert", t('wi.result_failed'), esc(res.error || "")); return; }
        const conf = res.confidence || {}; const cite = res.citation || {}; const sig = conf.signals || {};
        const sigRows = Object.keys(sig).map((k) => {
          const v = sig[k]; const pct = Math.round(Math.abs(v) / 0.25 * 100);
          const neg = v < 0;
          return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="width:180px;font-size:12px;color:var(--text-2)">${esc(signalLabel(k))}</span>
            <div style="flex:1;height:6px;background:var(--surface-2);border-radius:3px;overflow:hidden"><div style="width:${Math.min(100, pct)}%;height:100%;background:${neg ? 'var(--red)' : 'var(--green)'}"></div></div>
            <span class="mono" style="font-size:11px;width:48px;text-align:right">${v > 0 ? "+" : ""}${v}</span></div>`;
        }).join("");
        out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-head">
            <div><h3>${esc(cite.domain || res.final_url)}</h3><span class="subtle mono" style="font-size:11px;word-break:break-all">${esc(res.final_url || url)}</span></div>
            <span class="status-badge ${confLevelKind(conf.level)}" style="font-size:13px">${t('wi.trust')}: ${Math.round((conf.score || 0) * 100)}%</span></div>
          <div class="card-body" style="display:grid;gap:16px">
            <div class="grid grid-4">
              ${miniStat(t('wi.trust_level'), esc(conf.level || "—"))}
              ${miniStat(t('wi.domain'), esc(cite.domain || "—"))}
              ${miniStat("HTTPS", (res.final_url || url).startsWith("https") ? "✓" : "✗")}
              ${miniStat(t('wi.mon_chars'), Number(res.monitoring?.content_chars || 0).toLocaleString("id-ID"))}
            </div>
            <div><div class="page-section-label">${t('wi.trust_signals')}</div>${sigRows || '<span class="subtle">—</span>'}</div>
            <div><div class="page-section-label">${t('wi.citation')}</div>${citationBlock(cite)}</div>
          </div></div>`;
      } catch (err) { out.innerHTML = emptyState("alert", t('wi.result_failed'), esc(err.message)); toast(err.message, "error"); }
      finally { submitBtn.disabled = false; }
    });
  }

  // ── 7 · SCREENSHOT ──────────────────────────────────────────────────────
  async function renderWiScreenshot() {
    const prefill = takePrefill();
    setPage(`${pageHeader(t('route.wi-screenshot.title'), t('route.wi-screenshot.desc'))}
      <div class="card"><div class="card-body"><form id="wi-shot-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
        <label class="field" style="flex:1;min-width:260px"><span>${t('wi.url')}</span>
          <input class="input" name="url" required placeholder="https://example.com" value="${esc(prefill)}"></label>
        <button class="button button-primary" type="submit">${icon('multimedia',14)} ${t('wi.capture')}</button>
      </form></div></div>
      <div id="wi-shot-out"></div>`);
    const form = el("#wi-shot-form");
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = String(new FormData(form).get("url") || "").trim(); if (!url) return;
      const submitBtn = form.querySelector('button[type="submit"]'); submitBtn.disabled = true;
      const out = el("#wi-shot-out"); out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-body">${busy(t('wi.capturing'))}</div></div>`;
      try {
        const blob = await api.webIntelScreenshot({ url });
        if (wiState.lastScreenshotUrl) URL.revokeObjectURL(wiState.lastScreenshotUrl);
        wiState.lastScreenshotUrl = URL.createObjectURL(blob);
        out.innerHTML = `<div class="card" style="margin-top:14px"><div class="card-head"><h3>${t('wi.screenshot')}</h3>
            <a class="button button-sm" href="${wiState.lastScreenshotUrl}" download="screenshot.png">${icon('upload',13)} ${t('wi.download')}</a></div>
          <div class="card-body"><img src="${wiState.lastScreenshotUrl}" alt="Screenshot ${esc(url)}" style="max-width:100%;border:1px solid var(--line);border-radius:8px"></div></div>`;
      } catch (err) {
        const msg = err.status === 501 ? t('wi.shot_unavailable') : err.message;
        out.innerHTML = emptyState("alert", t('wi.shot_failed'), esc(msg)); toast(msg, "error");
      } finally { submitBtn.disabled = false; }
    });
  }

  // ── 8 · SETTINGS ────────────────────────────────────────────────────────
  async function renderWiSettings() {
    setPage(`${pageHeader(t('route.wi-settings.title'), t('route.wi-settings.desc'))}
      <div id="wi-settings">${skeletonCards(2)}</div>`);
    let s;
    try { s = await getStatus(true); }
    catch (e) { el("#wi-settings").innerHTML = emptyState("alert", t('wi.status_unreachable'), esc(e.message)); return; }
    const caps = s.capabilities || {}; const cache = s.cache || {};
    const capRows = Object.keys(caps).map((k) => infoRow(capLabel(k), caps[k] ? `<span class="status-badge active">${t('wi.on')}</span>` : `<span class="status-badge default">${t('wi.off')}</span>`)).join("");
    el("#wi-settings").innerHTML = `
      <div class="grid grid-2" style="gap:16px">
        <div class="card"><div class="card-head"><h3>${t('wi.cache_title')}</h3></div><div class="card-body">
          <div class="wi-cap-grid">
            ${infoRow(t('wi.cache_entries'), `${cache.entries || 0} / ${cache.max_entries || 0}`)}
            ${infoRow(t('wi.cache_ttl'), `${cache.ttl_seconds || 0}s`)}
            ${infoRow(t('wi.cache_hitrate'), `${Math.round((cache.hit_rate || 0) * 100)}% (${cache.hits || 0}/${(cache.hits || 0) + (cache.misses || 0)})`)}
          </div>
          <div style="margin-top:14px"><button class="button" data-wi-clear>${icon('refresh',14)} ${t('wi.clear_cache')}</button></div>
        </div></div>
        <div class="card"><div class="card-head"><h3>${t('wi.capabilities')}</h3><span class="subtle">${t('wi.server_managed')}</span></div>
          <div class="card-body"><div class="wi-cap-grid">${capRows}</div></div></div>
      </div>
      <div class="wi-note" style="margin-top:16px">${icon('about',13)} ${t('wi.settings_note')}</div>`;
    el("[data-wi-clear]")?.addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      try { await api.webIntelClearCache(); toast(t('wi.cache_cleared'), "success"); wiState.statusTs = 0; renderWiSettings(); }
      catch (err) { toast(err.message, "error"); ev.target.disabled = false; }
    });
  }

  // ── refresh button plumbing (dashboard/settings) ─────────────────────────
  function refreshBtn() { return `<button class="button button-sm" data-wi-refresh>${icon('refresh',14)} ${t('wi.refresh')}</button>`; }
  function bindRefresh(fn) { el("[data-wi-refresh]")?.addEventListener("click", () => { wiState.statusTs = 0; fn(); }); }

  return {
    "web-intelligence": renderWiDashboard,
    "wi-scraper": renderWiScraper,
    "wi-crawl": renderWiCrawl,
    "wi-extract": renderWiExtract,
    "wi-knowledge": renderWiKnowledge,
    "wi-verify": renderWiVerify,
    "wi-screenshot": renderWiScreenshot,
    "wi-settings": renderWiSettings,
  };
}

export const WEB_INTELLIGENCE_ROUTES = WI_ROUTES;

// ── pure presentational helpers (no ctx needed) ────────────────────────────
function pane(label, body) { return `<div><div class="page-section-label">${esc(label)}</div>${body}</div>`; }
function preBlock(text) { return `<pre class="wi-pre mono">${esc(text)}</pre>`; }
function miniStat(label, value) { return `<div class="card" style="padding:12px 14px"><div class="subtle" style="font-size:10px;text-transform:uppercase;letter-spacing:.04em">${esc(label)}</div><div style="font-size:18px;font-weight:700;margin-top:2px">${value}</div></div>`; }
function infoRow(label, value) { return `<div class="wi-cap" style="justify-content:space-between"><span style="color:var(--text-2)">${esc(label)}</span><span>${value}</span></div>`; }
function kvGrid(obj) { const rows = Object.keys(obj).filter((k) => obj[k] != null && obj[k] !== "").map((k) => infoRow(k, `<span class="mono" style="font-size:12px">${esc(String(obj[k]).slice(0, 200))}</span>`)).join(""); return `<div class="wi-cap-grid">${rows || '<span class="subtle">—</span>'}</div>`; }
function imageStrip(images) { const items = images.slice(0, 24).map((im) => { const src = typeof im === "string" ? im : (im.src || im.url || ""); return src ? `<a href="${esc(src)}" target="_blank" rel="noopener"><img src="${esc(src)}" alt="" loading="lazy" style="height:88px;width:auto;border:1px solid var(--line);border-radius:6px"></a>` : ""; }).join(""); return `<div style="display:flex;gap:8px;flex-wrap:wrap">${items || '<span class="subtle">—</span>'}</div>`; }
function citationBlock(c) { if (!c || !c.source_url) return '<span class="subtle">—</span>'; const bits = [["Source", c.source_url], ["Domain", c.domain], ["Title", c.title], ["Author", c.author], ["Published", c.published_at], ["Accessed", c.accessed_at]].filter(([, v]) => v); return `<div class="wi-cap-grid">${bits.map(([k, v]) => infoRow(k, `<span class="mono" style="font-size:11px;word-break:break-all">${esc(v)}</span>`)).join("")}</div>`; }
function progressBar(done, total, current, complete) { const pct = total ? Math.round(done / total * 100) : 0; return `<div class="card" style="margin-top:14px"><div class="card-body"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px"><span>${complete ? t('wi.done') : t('wi.processing')} ${done}/${total}</span><span class="subtle mono" style="max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(current || "")}</span></div><div style="height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:var(--accent, #3d6791);transition:width .2s"></div></div></div></div>`; }
function busy(label) { return `<div style="display:flex;align-items:center;gap:10px"><span class="wi-spinner"></span><span>${esc(label)}</span></div>`; }
function emptyState(ic, title, desc) { return `<div class="card" style="margin-top:14px"><div class="card-body" style="text-align:center;padding:36px 20px"><div style="opacity:.5;margin-bottom:8px">${icon(ic, 30)}</div><strong>${esc(title)}</strong><p class="subtle" style="font-size:13px;margin-top:4px">${desc || ""}</p></div></div>`; }
function selectField(name, label, opts) { return `<label class="field"><span>${esc(label)}</span><select class="input" name="${name}">${opts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></label>`; }
function checkField(name, label, checked) { return `<label class="wi-check"><input type="checkbox" name="${name}" ${checked ? "checked" : ""}><span>${esc(label)}</span></label>`; }
function numField(name, label, val, min, max, step) { return `<label class="field"><span>${esc(label)}</span><input class="input" type="number" name="${name}" value="${val}" min="${min}" max="${max}" step="${step || 1}"></label>`; }
function fmtBytes(n) { n = Number(n || 0); if (n < 1024) return `${n} B`; if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`; return `${(n / 1048576).toFixed(1)} MB`; }
function confLevelKind(level) { return level === "high" ? "active" : level === "medium" ? "pending" : "default"; }
function capLabel(k) { const v = t(`wi.cap.${k}`); return v === `wi.cap.${k}` ? k.replace(/_/g, " ") : v; }
function signalLabel(k) { const v = t(`wi.sig.${k}`); return v === `wi.sig.${k}` ? k.replace(/_/g, " ") : v; }
