import { api, tokenStore, settle } from "/ui/api-client.js?v=20260720-casper-engineer-1";
import {
  icon, esc, initials, formatNumber, formatDate, relativeTime, idr, renderMarkdown,
  sidebar, topbar, pageHeader, statusBadge, metricCard, skeletonCards,
  emptyState, errorState, agentCard, activityItem, modal, agentDrawer, toast,
  planBadge, lockCard, upgradeDialog, upgradeBanner, settingSection, settingRow, readonlyField,
} from "/ui/components.js?v=20260720-casper-engineer-1";
import { t, setLang, getLang } from "/ui/i18n.js?v=20260720-casper-engineer-2";
import { bufferSpeechSentences, segmentPauseMs } from "/ui/voice-engine.js?v=20260701-local-agent-8";

window.laToolChange = function(tool) {
  const container = document.getElementById("la-fields");
  if (!container) return;
  const inp = (id, label, val, ph) =>
    `<label style="font-size:12px;color:var(--text-muted);display:grid;gap:3px">${label}<input id="${id}" value="${val}" placeholder="${ph}" style="padding:6px 10px;border-radius:6px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-size:13px"></label>`;
  const hint = (msg) =>
    `<p style="font-size:11px;color:var(--text-muted);margin:0;line-height:1.5">${msg}</p>`;
  const fields = {
    get_info:    "",
    list_dir:
      inp("la-path","Path folder yang ingin dibuka","~/","/home/asrory/Downloads") +
      hint("Isi dengan alamat folder asli, bukan pertanyaan. Kalau ingin bertanya ke AI, gunakan kotak <strong>Tanya Agent</strong> di bagian atas.<br>Contoh: <code>/home/asrory</code> &nbsp;·&nbsp; <code>/home/asrory/Downloads</code> &nbsp;·&nbsp; <code>/home/asrory/Documents</code>"),
    read_file:
      inp("la-path","Path file yang ingin dibaca","","~/contoh.txt") +
      hint("Contoh: <code>/home/asrory/.bashrc</code> &nbsp;·&nbsp; <code>~/Documents/catatan.txt</code>"),
    run_command:
      inp("la-cmd","Perintah shell","","ls -la ~/") +
      hint("Perintah yang aman dijalankan langsung. Perintah berisiko akan meminta approval terlebih dulu."),
    find_files:
      inp("la-pat","Pattern nama file","*.py","*.txt") +
      inp("la-dir","Folder pencarian","~/","~/Documents") +
      hint("Contoh pattern: <code>*.py</code> &nbsp;·&nbsp; <code>*.txt</code> &nbsp;·&nbsp; <code>*.log</code>"),
  };
  container.innerHTML = fields[tool] || "";
};

window.onAgentSelectChange = function(agent) {
  const hint = document.getElementById("agent-hint");
  const goalInput = document.getElementById("agent-goal");
  if (!hint || !goalInput) return;
  const COMPUTER_AGENT_TYPES_LOCAL = new Set(["computer", "local_computer", "project_debugger"]);
  if (COMPUTER_AGENT_TYPES_LOCAL.has(agent)) {
    hint.style.display = "block";
    hint.innerHTML = `💻 Agent ini menggunakan <strong>Local Agent</strong> untuk mengakses file, folder, dan terminal komputer Anda secara langsung.<br>Contoh: <em>"Lihat isi /home/asrory"</em> · <em>"Scan project BotNesia"</em> · <em>"Cari file package.json"</em>`;
    goalInput.placeholder = "Contoh: Cari folder BotNesia dan scan project-nya";
  } else {
    hint.style.display = "none";
    goalInput.placeholder = "Tulis pertanyaan atau tugas untuk agent, contoh: Cek invoice yang belum lunas";
  }
};

const state = {
  route: "dashboard", health: null, org: null, user: null, bots: [], overview: null, founder: null, founderAccess: false,
  inboxSummary: null, team: [], roles: [], rbac: null, subscription: null,
  usage: null, plans: [], invoices: [], selectedBotId: null, selectedConversationId: null,
  conversations: [], messages: [], analytics: null, costIntelligence: null, documents: [], knowledgeSources: [], knowledgeStats: null, knowledgeFilters: { status:"", category:"", search:"" }, channels: [], channelAnalytics: null, integrations: null,
  kbOverview: null, kbFaqs: [], kbSops: [], security: null, securityScan: null,
  improvement: null, improvementDays: 30,
  wfNodeCatalog: null, wfWorkflows: [], wfWorkflow: null, wfExecutions: [], wfExecution: null,
  wfSelectedNodeId: null, wfLinkFrom: null, wfDrag: null,
  chatSession: null, charts: {}, loading: false,
  multimedia: { generating: false, analyzing: false, generatingDoc: false, lastImage: null, lastAnalysis: null, lastDocument: null, history: [] },
  agentTaskRun: { running: false, lastResult: null, lastError: null },
  analyticsDays: 30, observabilityDays: 7, recorder: null, recordingStream: null, recordingChunks: [], speakReplies: true, speechRunId: 0, speechAudio: null,
  speechContext: null, speechSources: new Set(),
  navOpenSections: new Set(),
};

const el = (selector) => document.querySelector(selector);
const els = (selector) => [...document.querySelectorAll(selector)];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pageRoot = () => el("#page-root");

// ── Client-side TTL cache ──────────────────────────────────────
const _cache = new Map();
async function cachedSettle(label, promiseFn, ttlSeconds = 60) {
  const hit = _cache.get(label);
  if (hit && Date.now() - hit.ts < ttlSeconds * 1000) return { ok: true, label, data: hit.data };
  const result = await settle(label, promiseFn());
  if (result.ok) _cache.set(label, { data: result.data, ts: Date.now() });
  return result;
}
function bustCache(...keys) {
  if (!keys.length) { _cache.clear(); return; }
  keys.forEach((k) => _cache.delete(k));
}

function parseJwt() {
  try { return JSON.parse(atob(tokenStore.get().split(".")[1].replace(/-/g,"+").replace(/_/g,"/"))); }
  catch { return {}; }
}

function currentRoute() {
  const route = location.hash.replace(/^#\/?/, "").split("/")[0];
  return ["founder","dashboard","agents","chat","conversations","handoffs","analytics","routing-logs","learning","improvement","observability","costs","channels","marketplace","knowledge","kb-builder","workflow-builder","finance","marketing","hr","operations","executive","workforce","self-learning","workforce-overview","agent-center","communication-center","multimedia","team","billing","security","settings","about","founder-story","investor-demo","casper-engineer"].includes(route) ? route : "dashboard";
}

function showAuth() { el("#auth-view").classList.remove("hidden"); el("#app-shell").classList.add("hidden"); }
function showApp() { el("#auth-view").classList.add("hidden"); el("#app-shell").classList.remove("hidden"); }
function closeMobileNav() { el("#sidebar").classList.remove("open"); el("#mobile-scrim").classList.remove("open"); }

function renderChrome() {
  const counts = { agents: state.bots.length, conversations: state.inboxSummary?.by_state?.unread ?? 0, team: state.team.length };
  el("#sidebar").innerHTML = sidebar({ route:state.route, org:state.org, user:state.user, counts, founderAccess:state.founderAccess, openSections:state.navOpenSections });
  el("#topbar").innerHTML = topbar({ route:state.route, health:state.health });
}

async function loadCore() {
  state.loading = true;
  const results = await Promise.all([
    settle("health", api.health()), settle("org", api.org()), settle("bots", api.bots()),
    settle("overview", api.dashboardOverview()), settle("inboxSummary", api.inboxSummary()),
    settle("rbac", api.rbacMe()), settle("team", api.team()), settle("subscription", api.subscription()),
    settle("founderAccess", api.founderAccess()),
  ]);
  for (const result of results) if (result.ok) state[result.label] = result.data;
  state.bots = state.bots || [];
  state.team = state.team?.team || state.team || [];
  state.subscription = state.subscription || null;
  const founderAccessResult = results.find((result) => result.label === "founderAccess");
  state.founderAccess = Boolean(founderAccessResult?.ok && founderAccessResult.data?.founder);
  state.selectedBotId ||= state.bots[0]?.id || null;
  const jwt = parseJwt();
  state.user = state.team.find((member) => String(member.id) === String(jwt.sub)) || { id:jwt.sub, email:"", full_name:"Workspace Admin" };
  state.loading = false;
  renderChrome();
}

function setPage(content) { pageRoot().innerHTML = `<section class="page-enter">${content}</section>`; pageRoot().focus({preventScroll:true}); }
function loadingPage(title, description, skeletonCount = 4) {
  setPage(`${pageHeader(title, description)}<div style="margin-top:8px">${skeletonCards(skeletonCount)}</div><div class="grid grid-2" style="margin-top:16px"><div class="skeleton" style="height:260px"></div><div class="skeleton" style="height:260px"></div></div>`);
}

async function renderDashboard() {
  loadingPage(t('route.dashboard.title'), t('route.dashboard.desc'));
  const bot = state.bots.find((item) => item.id === state.selectedBotId) || state.bots[0];
  const results = await Promise.all([
    bot ? settle("analytics", api.botAnalytics(bot.id, 30)) : Promise.resolve({ok:false}),
    settle("queue", api.handoffQueue({limit:8})),
    settle("finance", api.financeDashboard()),
    settle("marketing", api.marketingDashboard()),
    settle("hr", api.hrDashboard()),
    settle("operations", api.opsDashboard()),
    settle("security", api.securityDashboard()),
    settle("executive", api.executiveDashboard()),
    settle("workforce", api.workforceDashboard()),
  ]);
  const [analyticsResult, queueResult, financeResult, marketingResult, hrResult, opsResult, securityResult, executiveResult, workforceResult] = results;
  const analytics = analyticsResult.ok ? analyticsResult.data : null;
  const queue = queueResult.ok ? queueResult.data.queue || [] : [];
  const finance = financeResult.ok ? financeResult.data : {};
  const marketing = marketingResult.ok ? marketingResult.data : {};
  const hr = hrResult.ok ? hrResult.data : {};
  const ops = opsResult.ok ? opsResult.data : {};
  const security = securityResult.ok ? securityResult.data : {};
  const executive = executiveResult.ok ? executiveResult.data : {};
  const workforceData = workforceResult.ok ? workforceResult.data : {};
  const overview = state.overview || {};
  const summary = analytics?.summary || {};
  const health = executive.health || {};
  const opsHealth = ops.health || {};
  const openOpsAlerts = Object.values(ops.open_alerts_by_severity || {}).reduce((sum, n) => sum + Number(n || 0), 0);
  const openSecurityAlerts = Object.values(security.open_security_alerts_by_severity || {}).reduce((sum, n) => sum + Number(n || 0), 0);
  const overdueInvoices = finance.overdue_invoices_count || 0;
  const pendingInvoices = finance.pending_invoices_count || 0;
  const contentDueNow = marketing.content_due_now || 0;
  const pendingTraining = hr.pending_training_recommendations || 0;
  const pendingApproval = workforceData.pending_approval_count || 0;

  const opportunities = [
    overdueInvoices ? ["Invoice overdue", `${formatNumber(overdueInvoices)} invoice melewati jatuh tempo, total ${idr(finance.pending_invoices_amount_idr || 0)}`, "Finance Agent", "critical"] : null,
    contentDueNow ? ["Konten terlambat publish", `${formatNumber(contentDueNow)} konten terjadwal sudah lewat waktu publish`, "Marketing Agent", "warning"] : null,
    openOpsAlerts ? ["Alert operasional terbuka", `${formatNumber(openOpsAlerts)} alert operations perlu ditindaklanjuti`, "Operations Agent", "warning"] : null,
    openSecurityAlerts ? ["Sinyal risiko keamanan", `${formatNumber(openSecurityAlerts)} alert security terbuka`, "Security Agent", "critical"] : null,
    pendingTraining ? ["Rekomendasi training tertunda", `${formatNumber(pendingTraining)} rekomendasi training menunggu review`, "HR Agent", "info"] : null,
    pendingApproval ? ["Task menunggu approval", `${formatNumber(pendingApproval)} workforce task butuh human approval`, "Workforce Orchestrator", "info"] : null,
  ].filter(Boolean);
  const opportunityHtml = opportunities.length
    ? opportunities.map(([title,detail,owner,severity]) => `<li class="${severity||'warning'}"><span></span><div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div><em>${esc(owner)}</em></li>`).join("")
    : `<li class="info"><span></span><div><strong>${t('page.dashboard.no_attention')}</strong><p>${t('page.dashboard.all_normal')}</p></div></li>`;

  const workforce = [
    ["Finance Agent", overdueInvoices ? "Needs Attention" : "Healthy", `${formatNumber(pendingInvoices)} invoice pending`, idr(finance.revenue_30d_idr || 0) + " revenue 30 hari", overdueInvoices ? `${formatNumber(overdueInvoices)} invoice overdue perlu reminder` : "Tidak ada invoice overdue", "finance"],
    ["Marketing Agent", contentDueNow ? "Needs Attention" : "Healthy", `${formatNumber(marketing.active_campaigns || 0)} campaign aktif`, `${formatNumber(marketing.content_published || 0)} konten published`, contentDueNow ? `${formatNumber(contentDueNow)} konten terlambat publish` : "Semua konten on schedule", "marketing"],
    ["HR Agent", pendingTraining ? "Needs Attention" : "Healthy", `${formatNumber(Object.values(hr.candidates_by_status || {}).reduce((s,n)=>s+Number(n||0),0))} kandidat aktif`, `${formatNumber(pendingTraining)} rekomendasi training`, hr.avg_evaluation_score_90d != null ? `Avg evaluasi karyawan: ${hr.avg_evaluation_score_90d}` : "Belum ada data evaluasi", "hr"],
    ["Executive Agent", health.label || "—", `Company health ${health.overall ?? "—"}/100`, `${formatNumber(Object.keys(health.by_domain || {}).length)} domain dipantau`, "Health score lintas Finance/Marketing/HR/Operations/Security/Sales", "executive"],
    ["Security Agent", security.risk_level || "—", `Risk level: ${security.risk_level || "—"}`, `${formatNumber(security.suspicious_sessions_count || 0)} sesi mencurigakan`, openSecurityAlerts ? `${formatNumber(openSecurityAlerts)} alert terbuka` : "Tidak ada alert terbuka", "security"],
  ].map(([name,status,current,weekly,last,iconName]) => `<article class="workforce-employee" data-route="${iconName}"><div class="employee-head"><span class="employee-avatar">${initials(name)}</span><div><h3>${esc(name)}</h3><span class="employee-status${status==='Needs Attention'?' needs-attention':''}"><i></i>${esc(status)}</span></div></div><dl><div><dt>${t('common.status')}</dt><dd>${esc(current)}</dd></div><div><dt>${t('page.dashboard.domain_30d')}</dt><dd>${esc(weekly)}</dd></div><div><dt>${t('page.dashboard.domain_attention')}</dt><dd>${esc(last)}</dd></div></dl></article>`).join("");

  const healthDescriptionParts = [];
  if (overdueInvoices) healthDescriptionParts.push(`${formatNumber(overdueInvoices)} invoice overdue`);
  if (openOpsAlerts) healthDescriptionParts.push(`${formatNumber(openOpsAlerts)} alert operasional`);
  if (openSecurityAlerts) healthDescriptionParts.push(`${formatNumber(openSecurityAlerts)} sinyal security`);
  const healthDescription = healthDescriptionParts.length
    ? `Perlu perhatian: ${healthDescriptionParts.join(", ")}.`
    : "Tidak ada sinyal kritis lintas domain saat ini.";

  setPage(`<section class="business-command">
    <section class="business-hero">
      <div class="business-hero-copy">
        <img class="business-hero-logo" src="/assets/brand/botnesia-clean-logo.png" alt="BotNesia logo">
        <span class="eyebrow">${t('page.dashboard.hero_eyebrow')}</span>
        <h2>${t('page.dashboard.hero_title')}</h2>
        <p>${t('page.dashboard.hero_desc')}</p>
        <div class="business-quick-actions">
          <button class="button button-primary" data-route="chat">${icon('chat',14)} ${t('page.dashboard.open_ai_chat')}</button>
          <button class="button" data-route="conversations">${icon('conversations',14)} ${t('page.dashboard.open_inbox')}</button>
        </div>
      </div>
      <div class="business-health-card" data-route="executive">
        <span>${t('page.dashboard.business_health')}</span>
        <strong>${health.overall ?? "—"}<small>/100</small></strong>
        <p>${esc(healthDescription)}</p>
      </div>
    </section>
    <section class="business-kpis">
      <article data-route="finance"><span>${t('page.dashboard.revenue_30d')}</span><strong>${idr(finance.revenue_30d_idr || 0)}</strong><small>${formatNumber(pendingInvoices)} invoice pending</small></article>
      <article data-route="conversations"><span>${t('page.dashboard.active_convs')}</span><strong>${formatNumber(overview.conversations_30d ?? summary.total_convs ?? 0)}</strong><small>${t('page.dashboard.last_30d')}</small></article>
      <article data-route="handoffs"><span>${t('page.dashboard.human_handoff')}</span><strong>${formatNumber(queue.length)}</strong><small>${t('page.dashboard.waiting_queue')}</small></article>
      <article data-route="operations"><span>${t('page.dashboard.ops_health')}</span><strong>${opsHealth.score ?? "—"}</strong><small>${esc(opsHealth.label || "—")}</small></article>
    </section>
    <section class="business-main-grid">
      <div class="business-panel workforce-panel"><div class="business-section-head"><div><span class="eyebrow">${t('page.dashboard.workforce_eyebrow')}</span><h3>${t('page.dashboard.workforce_heading')}</h3></div><button class="button button-ghost" data-route="workforce-overview">${t('page.dashboard.view_all')}</button></div><div class="workforce-grid">${workforce}</div></div>
      <aside class="business-panel opportunities-panel"><div class="business-section-head"><div><span class="eyebrow">${t('page.dashboard.opps_eyebrow')}</span><h3>${t('page.dashboard.opps_heading')}</h3></div></div><ul class="opportunity-list">${opportunityHtml}</ul></aside>
    </section>
  </section>`);
}

function founderInsightClass(type) {
  if (type === "critical" || type === "warning") return type;
  if (type === "positive") return "positive";
  return "neutral";
}

async function renderFounder() {
  loadingPage("Founder Operating System", "Monitor the company, not a tenant: revenue, growth, retention, AI economics, and risk.");
  try { state.founder = await api.founderOverview(); }
  catch (error) { setPage(`${pageHeader("Founder Operating System","Platform-wide metrics are restricted to BotNesia founders and platform operators.")}${errorState(error.message)}`); return; }
  const data = state.founder || {};
  const metrics = data.metrics || {};
  const health = data.health_score || {};
  const trend = data.trend || [];
  const insightRows = (data.insights || []).map((item) => `<div class="founder-insight ${founderInsightClass(item.type)}"><span></span><div><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></div></div>`).join("");
  const agentRows = (data.top_agents || []).map((row) => `<tr><td><span class="table-title mono">${esc(row.agent_name)}</span></td><td>${formatNumber(row.executions)}</td><td>${formatNumber(row.tokens)}</td><td>${Number(row.failure_rate||0).toFixed(1)}%</td></tr>`).join("");
  const channelRows = (data.top_channels || []).map((row) => `<tr><td><span class="table-title">${esc(row.channel)}</span></td><td>${formatNumber(row.conversations)}</td><td><div class="progress" style="min-width:110px"><span style="width:${Math.max(5,Math.round(Number(row.conversations||0)/Math.max(1,Number(data.top_channels?.[0]?.conversations||1))*100))}%"></span></div></td></tr>`).join("");
  const tenantRows = (data.high_cost_tenants || []).map((row) => `<tr><td><span class="table-title">${esc(row.name)}</span><div class="subtle mono" style="font-size:8px">${esc(row.tenant_id)}</div></td><td>${usd(row.ai_cost_usd,4)}</td><td>${formatNumber(row.tokens)}</td></tr>`).join("");
  const componentRows = Object.entries(health.components || {}).map(([key,value]) => `<div class="usage-row"><div class="usage-row-head"><span>${esc(key)}</span><b>${Number(value).toFixed(0)}</b></div><div class="progress"><span style="width:${Math.min(100,Number(value||0))}%"></span></div></div>`).join("");
  const businessCards = [
    metricCard("MRR",idr(metrics.mrr_idr),"Active recurring revenue","billing",metrics.growth_rate>=0?"trend-up":"trend-down"),
    metricCard("ARR",idr(metrics.arr_idr),"MRR × 12","analytics"),
    metricCard("Revenue",idr(metrics.monthly_revenue_idr),`${idr(metrics.revenue_idr)} lifetime`,"dashboard",metrics.revenue_growth_rate>=0?"trend-up":"trend-down"),
    metricCard("Profit",idr(metrics.profit_idr),"Revenue minus operating cost","dashboard",metrics.profit_idr>=0?"trend-up":"trend-down"),
    metricCard("Cost",idr(metrics.cost_idr),`${idr(metrics.ai_cost_idr)} AI cost`,"costs",metrics.cost_idr>metrics.monthly_revenue_idr?"trend-down":""),
    metricCard("Active Tenants",formatNumber(metrics.active_tenants),`${formatNumber(metrics.total_tenants)} total tenants`,"team"),
    metricCard("New Tenants",formatNumber(metrics.new_tenants),`${Number(metrics.tenant_growth_rate||0).toFixed(1)}% growth`,"founder",metrics.tenant_growth_rate>=0?"trend-up":"trend-down"),
    metricCard("Churn Rate",`${Number(metrics.churn_rate||0).toFixed(1)}%`,`${Number(metrics.retention_rate||0).toFixed(1)}% retention`,"handoffs",metrics.churn_rate<=5?"trend-up":"trend-down"),
    metricCard("Growth Rate",`${Number(metrics.growth_rate||0).toFixed(1)}%`,"Monthly revenue growth","analytics",metrics.growth_rate>=0?"trend-up":"trend-down"),
  ].join("");
  const aiCards = [
    metricCard("Conversations",formatNumber(metrics.total_conversations),`${formatNumber(metrics.conversations_30d)} in 30 days`,"chat"),
    metricCard("Token Usage",formatNumber(metrics.total_token_usage),`${formatNumber(metrics.tokens_30d)} in 30 days`,"observability"),
    metricCard("AI Cost",usd(metrics.ai_cost_usd,4),`${idr(metrics.ai_cost_idr)} converted`,"costs"),
    metricCard("Cost / Tenant",usd(metrics.cost_per_tenant_usd,4),"Active tenant average","team"),
  ].join("");
  setPage(`${pageHeader("Founder Operating System","Company-wide command center for SaaS economics, tenant growth, AI usage, and business risk.",`<span class="status-badge active">Founder only</span><button class="button" data-action="refresh">${icon('refresh',14)} Refresh</button>`)}
    <div class="page-section-label">SaaS economics</div>
    <div class="grid grid-4" style="margin-bottom:16px">${businessCards}</div>
    <div class="page-section-label">Business health</div>
    <div class="grid dashboard-grid founder-primary" style="margin-bottom:16px">
      <div class="card"><div class="card-head"><div><h3>Revenue Trend</h3><span class="subtle">Paid invoice revenue, last 30 days</span></div><span class="status-badge active">Platform-wide</span></div><div class="card-body"><div style="height:290px"><canvas id="founder-revenue-chart"></canvas></div></div></div>
      <div class="card founder-health"><div class="card-head"><div><h3>Business Health Score</h3><span class="subtle">Growth · revenue · churn · usage · retention</span></div></div><div class="card-body"><div class="health-score ${esc(health.label||'watch')}"><strong>${formatNumber(health.score)}</strong><span>/ 100</span><small>${esc(health.label||'watch')}</small></div>${componentRows}</div></div>
    </div>
    <div class="page-section-label">Founder insights</div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Founder Insights</h3><span class="subtle">Automated signals from revenue, churn, usage, tenant cost, and agent reliability</span></div></div><div class="card-body founder-insights">${insightRows || '<span class="subtle">No material founder insights detected.</span>'}</div></div>
    <div class="page-section-label">AI economics</div>
    <div class="grid grid-4" style="margin-bottom:16px">${aiCards}</div>
    <div class="page-section-label">Usage distribution</div>
    <div class="grid grid-2" style="margin-bottom:16px">
      <div class="card"><div class="card-head"><div><h3>Top Agents</h3><span class="subtle">30-day executions and reliability</span></div></div>${agentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Executions</th><th>Tokens</th><th>Failure</th></tr></thead><tbody>${agentRows}</tbody></table></div>`:emptyState("No agent usage","Agent metrics appear after AI executions.")}</div>
      <div class="card"><div class="card-head"><div><h3>Top Channels</h3><span class="subtle">Conversation demand by channel</span></div></div>${channelRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Conversations</th><th>Share</th></tr></thead><tbody>${channelRows}</tbody></table></div>`:emptyState("No channel usage","Channel metrics appear after conversations.")}</div>
    </div>
    <div class="card"><div class="card-head"><div><h3>High-Cost Tenants</h3><span class="subtle">Current-month AI cost concentration</span></div></div>${tenantRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tenant</th><th>AI Cost</th><th>Tokens</th></tr></thead><tbody>${tenantRows}</tbody></table></div>`:emptyState("No tenant cost","AI cost will appear after model usage.")}</div>
  `);
  drawChart("founder-revenue","#founder-revenue-chart",trend.map((row)=>({date:row.date,value:row.revenue||0})),"line");
}

async function renderAgents() {
  const total = state.bots.length;
  const active = state.bots.filter((b) => b.status === 'active').length;
  const inactive = total - active;
  const statsHtml = total ? `<div class="agent-page-stats">
    <div class="agent-stat-chip">${icon('agents',12)}<span>${total} agent${total !== 1 ? 's' : ''}</span></div>
    <div class="agent-stat-chip"><span class="dot dot-active"></span><span>${active} ${t('page.agents.stat_active')}</span></div>
    ${inactive ? `<div class="agent-stat-chip"><span class="dot dot-inactive"></span><span>${inactive} ${t('page.agents.stat_inactive')}</span></div>` : ''}
  </div>` : '';
  setPage(`${pageHeader(t('page.agents.title'), t('page.agents.subtitle'), `<button class="button button-primary" data-action="create-agent">${icon('plus',14)} ${t('page.agents.new_btn')}</button>`)}${statsHtml}${total ? `<div class="grid grid-3">${state.bots.map(agentCard).join('')}</div>` : emptyState(t('page.agents.empty_title'), t('page.agents.empty_desc'), `<button class="button button-primary" data-action="create-agent">${t('page.agents.deploy_btn')}</button>`)}`);
}

async function renderChat() {
  if (!state.bots.length) {
    setPage(`${pageHeader(t('page.chat.title'), t('page.chat.subtitle'))}${emptyState(t('page.chat.no_agent_title'), t('page.chat.no_agent_desc'), `<button class="button button-primary" data-action="create-agent">${t('page.chat.deploy_btn')}</button>`)}`);
    return;
  }
  const bot = state.bots.find((item) => item.id === state.selectedBotId) || state.bots[0];
  state.selectedBotId = bot.id;
  const options = state.bots.map((item) => `<option value="${esc(item.id)}" ${item.id===bot.id?"selected":""}>${esc(item.name)}</option>`).join("");
  const body = `<div class="card chat-page"><div class="card-head"><div><h3>${esc(bot.name)}</h3></div><div class="chat-agent-select"><select class="select" data-chat-page-bot aria-label="Switch agent">${options}</select><button class="button" data-action="new-chat" aria-label="${t('page.chat.new_chat')}">${icon('plus',14)} ${t('page.chat.new_chat')}</button></div></div><div id="playground-messages" class="messages chat-page-messages"><div class="message"><div class="message-bubble">${esc(bot.greeting||"Halo! Ada yang bisa saya bantu?")}</div></div></div><div class="chat-page-footer"><form data-playground-form class="chat-composer" data-bot-id="${esc(bot.id)}"><label class="icon-button" title="Upload &amp; analyze image" aria-label="Upload image">${icon("upload",17)}<input type="file" data-chat-image-upload accept="image/png,image/jpeg,image/webp,image/gif" hidden></label><button class="icon-button record-button" type="button" data-action="toggle-recording" title="Record voice" aria-label="Record voice message">${icon("mic",17)}</button><textarea name="message" placeholder="${t('page.chat.message_placeholder')}" required aria-label="Message input"></textarea><button class="icon-button" type="button" data-action="toggle-speech" title="Read AI replies aloud" aria-label="Toggle speech">${icon("speaker",17)}</button><button class="button button-primary" type="submit" data-action="send-chat">${icon("send",14)} ${t('page.chat.send')}</button></form><div class="voice-status" data-voice-status aria-live="polite">${t('page.chat.voice_ready')}</div></div></div>`;
  setPage(`${pageHeader(t('page.chat.title'), t('page.chat.subtitle'))}${body}`);
}

async function loadConversationData(botId = state.selectedBotId) {
  if (botId) state.selectedBotId = botId;
  try {
    const result = await api.inbox({limit:50});
    state.conversations = (result.inbox || []).filter((item) => !botId || item.bot_id === botId).map((item) => ({...item, id:item.conversation_id, msg_count:item.unread_count || 0}));
  } catch (error) {
    if (!botId) throw error;
    state.conversations = await api.botConversations(botId, {limit:50});
  }
}

function feedbackControls(messageId, conversationId, selected = "") {
  if (!messageId || !conversationId) return "";
  return `<div class="feedback-controls" data-feedback-group="${esc(messageId)}"><span>Helpful?</span><button class="feedback-button ${selected==='helpful'?'selected':''}" data-feedback-rating="helpful" data-feedback-message="${esc(messageId)}" data-feedback-conversation="${esc(conversationId)}" title="Helpful">👍 Helpful</button><button class="feedback-button ${selected==='not_helpful'?'selected negative':''}" data-feedback-rating="not_helpful" data-feedback-message="${esc(messageId)}" data-feedback-conversation="${esc(conversationId)}" title="Not Helpful">👎 Not Helpful</button></div>`;
}

async function renderFeedbackLearning() {
  loadingPage(t('page.learning.title'), t('page.learning.subtitle'));
  let data, queueData;
  try { [data, queueData] = await Promise.all([api.feedbackSummary(30), api.feedbackQueue()]); }
  catch (error) { setPage(errorState(error.message)); return; }
  const listCard = (title, rows, empty, negative = false) => `<div class="card"><div class="card-head"><h3>${esc(title)}</h3></div>${rows.length?`<div class="feedback-list">${rows.map((row)=>`<div class="feedback-list-item"><strong>${esc(row.question || 'No question recorded')}</strong><p>${esc(row.comment || row.failure_reason || row.answer || '')}</p><span class="subtle">${formatNumber(row.feedback_count || row.failure_count || row.occurrence_count || 1)} ${negative?'failures':'signals'}</span></div>`).join('')}</div>`:emptyState(empty,"Feedback will appear after users rate AI answers.")}</div>`;
  const queueRows = (queueData.queue || []).map((item) => `<tr><td><span class="table-title">${esc(item.question)}</span><div class="subtle" style="margin-top:4px">${esc(item.failure_reason || '')}</div></td><td>${statusBadge(item.action_type,item.action_type)}</td><td>${formatNumber(item.occurrence_count)}</td><td>${statusBadge(item.status,item.status)}</td><td><div style="display:flex;gap:6px">${item.status==='pending'?`<button class="button" data-learning-action="in_progress" data-learning-id="${esc(item.id)}">Start</button>`:''}${item.status!=='resolved'&&item.status!=='dismissed'?`<button class="button button-primary" data-learning-action="resolved" data-learning-id="${esc(item.id)}">Resolve</button>`:''}</div></td></tr>`).join('');
  setPage(`${pageHeader(t('page.learning.title'), t('page.learning.subtitle'),`<span class="status-badge active">30-day feedback window</span>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Total Feedback",formatNumber(data.total_feedback),`${formatNumber(data.helpful)} helpful`,`learning`)}${metricCard("Helpful Rate",`${Number(data.helpful_rate||0).toFixed(1)}%`,"Positive user ratings","dashboard","trend-up")}${metricCard("Not Helpful",formatNumber(data.not_helpful),"Answers requiring review","observability",data.not_helpful?'trend-down':'trend-up')}${metricCard("Learning Queue",formatNumber(data.queue?.pending),`${formatNumber(data.queue?.in_progress)} in progress`,`knowledge`)}</div>
  <div class="page-section-label">${t('page.learning.top_signals')}</div>
  <div class="grid grid-2" style="margin-bottom:16px">${listCard(t('page.learning.top_positive'),data.top_positive_feedback||[],"No positive feedback")}${listCard(t('page.learning.top_negative'),data.top_negative_feedback||[],"No negative feedback",true)}${listCard(t('page.learning.failed_qs'),data.most_failed_questions||[],"No failed questions",true)}${listCard(t('page.learning.knowledge_gaps'),data.knowledge_gaps||[],"No knowledge gaps",true)}</div>
  <div class="page-section-label">${t('page.learning.queue_label')}</div>
  <div class="card"><div class="card-head"><div><h3>${t('page.learning.queue_title')}</h3><span class="subtle">${t('page.learning.queue_sub')}</span></div>${data.queue?.pending ? `<span class="approval-count-badge">${formatNumber(data.queue.pending)}</span>` : ''}</div>${queueRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('page.learning.col_question')}</th><th>${t('page.learning.col_action')}</th><th>${t('page.learning.col_signals')}</th><th>${t('page.learning.col_status')}</th><th></th></tr></thead><tbody>${queueRows}</tbody></table></div>`:emptyState(t('page.learning.empty_queue'),t('page.learning.empty_queue_desc'))}</div>`);
}

function improvementSeverityStatus(severity) {
  if (severity === "critical" || severity === "high") return "error";
  if (severity === "medium") return "pending";
  return "ready";
}

function improvementRecStatus(status) {
  if (status === "applied") return "resolved";
  if (status === "dismissed") return "inactive";
  if (status === "reviewed") return "active";
  return "pending";
}

function improvementRecRow(rec) {
  const actions = [
    rec.status === "new" ? `<button class="button" data-improvement-action="reviewed" data-improvement-id="${esc(rec.id)}">Mark reviewed</button>` : "",
    rec.status !== "applied" ? `<button class="button button-primary" data-improvement-action="applied" data-improvement-id="${esc(rec.id)}">Mark applied</button>` : "",
    rec.status !== "dismissed" ? `<button class="button button-danger" data-improvement-action="dismissed" data-improvement-id="${esc(rec.id)}">Dismiss</button>` : "",
  ].join("");
  return `<tr><td><span class="status-badge ${improvementSeverityStatus(rec.severity)}">${esc(rec.severity)}</span></td><td><span class="status-badge ready">${esc(rec.category.replace(/_/g," "))}</span></td><td><span class="table-title">${esc(rec.title)}</span><div class="subtle" style="margin-top:4px;font-size:10px">${esc(rec.description)}</div>${rec.resolution_note?`<div class="subtle" style="margin-top:4px;font-size:10px">Catatan: ${esc(rec.resolution_note)}</div>`:''}</td><td>${formatNumber(rec.occurrence_count)}</td><td>${statusBadge(improvementRecStatus(rec.status),rec.status)}</td><td style="display:flex;gap:6px;flex-wrap:wrap">${actions}</td></tr>`;
}

async function renderImprovement() {
  loadingPage("AI Improvement Center", "BotNesia evaluasi diri: deteksi masalah otomatis dan rekomendasi perbaikan untuk admin.");
  const days = state.improvementDays || 30;
  const result = await settle("improvement", api.improvementDashboard(days));
  if (!result.ok) { setPage(`${pageHeader("AI Improvement Center","BotNesia evaluasi diri: deteksi masalah otomatis dan rekomendasi perbaikan untuk admin.")}${errorState(result.error.message)}`); return; }
  state.improvement = result.data;
  const data = state.improvement;
  const summary = data.summary || {};

  const topIssueRows = (data.top_issues || []).map((issue) => `<tr><td><span class="status-badge ready">${esc(issue.type.replace(/_/g," "))}</span></td><td class="table-title">${esc(issue.title)}</td><td>${formatNumber(issue.count)}</td></tr>`).join("");

  const weaknessRows = (data.agent_weaknesses || []).map((row) => `<tr><td><span class="table-title">${esc(row.bot_name)}</span></td><td>${formatNumber(row.conversations)}</td><td>${row.avg_quality_score ?? '—'}</td><td>${row.avg_confidence ?? '—'}</td><td>${formatNumber(row.failed_verifications)}</td><td>${formatNumber(row.bad_outcomes)}</td></tr>`).join("");

  const knowledgeGapRows = (data.knowledge_gaps || []).map(improvementRecRow).join("");
  const suggestedRows = (data.suggested_improvements || []).map(improvementRecRow).join("");

  setPage(`${pageHeader("AI Improvement Center","Self-evaluation: top issues, knowledge gaps, agent weaknesses, dan rekomendasi perbaikan. AI hanya mendeteksi — admin yang memutuskan.",`<button class="button button-primary" data-action="improvement-scan">${icon('refresh',14)} Run scan</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Failed Answers",formatNumber(summary.failed_answers),`${days}-day window`,"observability",summary.failed_answers?'trend-down':'trend-up')}${metricCard("Low Confidence",formatNumber(summary.low_confidence),"Pro mode confidence < 60","analytics")}${metricCard("Negative Feedback",formatNumber(summary.negative_feedback),"Not helpful ratings","learning")}${metricCard("Handoffs",formatNumber(summary.handoffs),"Escalated to human","handoffs")}</div>
  <div class="page-section-label">Issue analysis</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Top Issues</h3><span class="subtle">Failed answers, low confidence, negative feedback, repeated questions, and handoffs</span></div>${data.last_scan_at?`<span class="subtle mono" style="font-size:9px">Last scan: ${relativeTime(data.last_scan_at)}</span>`:''}</div>${topIssueRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Issue</th><th>Count</th></tr></thead><tbody>${topIssueRows}</tbody></table></div>`:emptyState("No issues detected","Run a scan to analyze recent conversations.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Agent Weaknesses</h3><span class="subtle">Quality & verification rollup per agent</span></div></div>${weaknessRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Conversations</th><th>Avg quality</th><th>Avg confidence</th><th>Failed verifications</th><th>Bad outcomes</th></tr></thead><tbody>${weaknessRows}</tbody></table></div>`:emptyState("No data yet","Agent performance rollups appear once conversations are analyzed.")}</div>
  <div class="page-section-label">Recommended improvements</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Knowledge Gaps</h3><span class="subtle">Konten yang perlu ditambahkan ke knowledge base</span></div></div>${knowledgeGapRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Recommendation</th><th>Occurrences</th><th>Status</th><th></th></tr></thead><tbody>${knowledgeGapRows}</tbody></table></div>`:emptyState("No knowledge gaps detected","Run a scan to detect knowledge gaps from low-confidence answers and negative feedback.")}</div>
  <div class="card"><div class="card-head"><div><h3>Suggested Improvements</h3><span class="subtle">Prompt, workflow & agent — admin yang memutuskan</span></div></div>${suggestedRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Recommendation</th><th>Occurrences</th><th>Status</th><th></th></tr></thead><tbody>${suggestedRows}</tbody></table></div>`:emptyState("No suggestions yet","AI tidak mengubah dirinya sendiri — jalankan scan untuk mendapatkan rekomendasi.")}</div>`);
}

async function renderHumanHandoff() {
  loadingPage(t('page.handoff.title'), t('page.handoff.subtitle'));
  let data, stats;
  try {
    [data, stats] = await Promise.all([api.handoffQueue({limit:100}), api.handoffStats()]);
  } catch (error) { setPage(errorState(error.message)); return; }
  const items = data.queue || [];
  const summary = stats.stats || {};
  const rows = items.map((item) => {
    const pending = item.status === "waiting";
    const assigned = item.status === "assigned";
    const mine = String(item.assigned_agent_id || "") === String(state.user?.id || "");
    const status = pending ? "pending" : item.status;
    const actions = pending
      ? `<button class="button button-primary" data-claim-handoff="${esc(item.id)}">${t('page.handoff.claim')}</button>`
      : assigned && mine
        ? `<button class="button" data-reply-handoff="${esc(item.id)}">${t('page.handoff.reply')}</button><button class="button button-primary" data-resolve-handoff="${esc(item.id)}">${t('page.handoff.resolve')}</button>`
        : assigned ? `<span class="subtle">${t('page.handoff.owned_by')} ${esc(item.assigned_agent_name || "another agent")}</span>` : "";
    const slaBreached = item.sla_due_at && new Date(item.sla_due_at) < new Date() && item.status !== "resolved";
    return `<tr><td><span class="table-title">${esc(item.end_user_name || item.end_user_id || t('page.handoff.anonymous'))}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(String(item.conversation_id).slice(0,8))}</div></td><td>${esc(item.reason || "manual")}</td><td>${statusBadge(status,status)}</td><td>${statusBadge(item.priority || "medium")}</td><td>${esc(item.assigned_agent_name || t('page.handoff.unassigned'))}</td><td class="${slaBreached?'trend-down':''}">${item.sla_due_at ? relativeTime(item.sla_due_at) : "—"}${slaBreached?` ${t('page.handoff.breached')}`:''}</td><td><div style="display:flex;gap:6px;align-items:center">${actions}</div></td></tr>`;
  }).join("");
  setPage(`${pageHeader(t('page.handoff.title'), t('page.handoff.subtitle'),`<button class="button" data-action="refresh">${icon('refresh',14)} ${t('common.refresh')}</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Pending",formatNumber(summary.waiting),`${formatNumber(summary.urgent_waiting)} urgent`,`handoffs`,summary.waiting?'trend-down':'trend-up')}${metricCard("Assigned",formatNumber(summary.assigned),"Currently owned by agents","team")}${metricCard("Resolved",formatNumber(summary.resolved_24h),"Last 24 hours","dashboard","trend-up")}${metricCard("SLA Breached",formatNumber(summary.sla_breached),summary.avg_resolution_minutes_7d?`${summary.avg_resolution_minutes_7d}m avg resolution`:"No resolution data","analytics",summary.sla_breached?'trend-down':'trend-up')}</div>
  ${summary.sla_breached ? `<div class="page-section-label" style="color:var(--red)">${t('page.handoff.queue_label')} — ${summary.sla_breached} SLA breached</div>` : `<div class="page-section-label">${t('page.handoff.queue_label')}</div>`}
  <div class="card"><div class="card-head"><div><h3>${t('page.handoff.queue_label')}</h3><span class="subtle">Pending, assigned, and resolved conversations</span></div><span class="status-badge active">Tenant isolated</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('page.handoff.col_customer')}</th><th>${t('page.handoff.col_reason')}</th><th>${t('page.handoff.col_status')}</th><th>${t('page.handoff.col_priority')}</th><th>${t('page.handoff.col_assigned')}</th><th>${t('page.handoff.col_sla')}</th><th>${t('page.handoff.col_action')}</th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState(t('page.handoff.empty_title'),t('page.handoff.empty_desc'))}</div>`);
}

async function renderConversations() {
  loadingPage(t('page.conv.title'), t('page.conv.subtitle'));
  if (!state.selectedBotId) { setPage(pageHeader(t('page.conv.title'), t('page.conv.subtitle')) + emptyState(t('page.conv.no_agent_title'), t('page.conv.no_agent_desc'))); return; }
  try { await loadConversationData(); } catch (error) { setPage(errorState(error.message)); return; }
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const handoffCount = state.conversations.filter((c) => c.handoff_needed).length;
  const rows = state.conversations.map((conv) => {
    const name = conv.end_user_name || conv.end_user_email || t('page.conv.anonymous');
    const channelLabel = esc(conv.channel || 'website');
    const channelClass = String(conv.channel || 'website').toLowerCase().replace(/[^a-z]/g,'');
    const stateLabel = conv.handoff_needed ? `<span style="color:var(--amber)">${t('page.conv.needs_handoff')}</span>` : esc(conv.inbox_state || t('page.conv.ai_handled'));
    const unread = conv.msg_count > 0 ? `<span class="conv-unread">${formatNumber(conv.msg_count)}</span>` : '';
    return `<div class="conversation-row ${conv.id===state.selectedConversationId?'active':''}" data-conversation-id="${esc(conv.id)}" role="button" tabindex="0" aria-label="Conversation with ${esc(name)}"><span class="avatar">${initials(name)}</span><div class="truncate"><strong class="truncate">${esc(name)}</strong><p class="truncate"><span class="channel-dot ${channelClass}"></span>${channelLabel} · ${stateLabel}</p></div>${unread}<span class="activity-time">${relativeTime(conv.last_msg_at || conv.started_at)}</span></div>`;
  }).join("");
  const chat = state.selectedConversationId ? renderMessagePanel() : `<div class="conv-select-prompt">${icon('chat',30)}<h3>${t('page.conv.select_title')}</h3><p>${t('page.conv.select_desc')}</p></div>`;
  const tabsHtml = `<div class="conv-status-tabs" role="tablist"><button class="conv-tab active" role="tab" aria-selected="true">${t('page.conv.all_tab')} <span class="mono" style="margin-left:4px;font-size:9px">${state.conversations.length}</span></button>${handoffCount ? `<button class="conv-tab" role="tab" aria-selected="false" style="color:var(--amber)">${t('page.conv.handoff_tab')} <span class="mono" style="margin-left:4px;font-size:9px">${handoffCount}</span></button>` : ''}</div>`;
  setPage(`${pageHeader(t('page.conv.title'), t('page.conv.subtitle'), `<select class="select" data-conversation-bot aria-label="Switch agent">${options}</select>`)}<div class="conversation-layout"><aside class="conversation-list"><div class="conversation-list-head"><input class="input" style="width:100%;min-width:0" data-conversation-search placeholder="${t('page.conv.search')}" aria-label="${t('page.conv.search')}"></div>${tabsHtml}<div data-conversation-rows>${rows || emptyState(t('page.conv.empty_title'), t('page.conv.empty_desc'))}</div></aside><section class="chat-window" id="conversation-chat" aria-live="polite">${chat}</section></div>`);
}

function renderMessagePanel() {
  const conv = state.conversations.find((item) => item.id === state.selectedConversationId);
  const isAdmin = (state.rbac?.permissions || []).includes("analytics.read");
  const messages = state.messages.map((message) => {
    const isAssistant = message.role==='assistant' && !String(message.model||'').startsWith('human:') && !String(message.model||'').includes('human-handoff');
    const sourcesCount = Array.isArray(message.source_chunks) ? message.source_chunks.length : 0;
    const sourcesButton = isAssistant && sourcesCount ? `<button type="button" class="button" style="margin-top:6px" data-view-sources="${esc(message.id)}">${icon('knowledge',14)} Lihat sumber (${sourcesCount})</button>` : '';
    const intentBadges = (isAdmin && isAssistant && message.intent) ? `<div class="message-routing-badges" style="display:flex;flex-wrap:wrap;gap:4px;margin-top:6px">${statusBadge('default',`Intent: ${message.intent}`)}${statusBadge('default',`Agent: ${message.selected_agent||'—'}`)}${message.routing_confidence!=null?statusBadge('default',`Conf: ${Math.round(Number(message.routing_confidence)*100)}%`):''}${message.handoff_status?statusBadge('error',`Handoff: ${message.handoff_status}`):''}</div>` : '';
    return `<div class="message ${message.role==='user'?'user':''}"><div class="message-bubble">${message.role==='user'?esc(message.content).replace(/\n/g,'<br>'):renderMarkdown(message.content)}<div class="message-meta">${esc(message.role)} · ${formatDate(message.created_at,{hour:'2-digit',minute:'2-digit'})}${message.latency_ms?` · ${message.latency_ms}ms`:''}</div>${isAssistant?feedbackControls(message.id,state.selectedConversationId,message.feedback_rating):''}${sourcesButton}${intentBadges}</div></div>`;
  }).join("");
  return `<header class="chat-head"><div style="display:flex;align-items:center;gap:10px"><span class="avatar">${initials(conv?.end_user_name || 'AN')}</span><div><strong>${esc(conv?.end_user_name || conv?.end_user_email || 'Anonymous customer')}</strong><div style="margin-top:4px">${statusBadge(conv?.handoff_needed?'handoff':'resolved',conv?.handoff_needed?'Needs handoff':'AI handled')}</div></div></div></header><div class="messages">${messages || emptyState("No messages","This conversation does not contain messages.")}</div>`;
}

async function openMessageSources(messageId) {
  let sources;
  try { sources = await api.messageSources(messageId); }
  catch (error) { toast(error.message,"error"); return; }
  const items = (sources || []).map((chunk) => `<div class="trace-step"><div><strong>${esc(chunk.filename || 'Document')}</strong><p>Chunk #${chunk.chunk_index} · ${formatDate(chunk.created_at,{hour:'2-digit',minute:'2-digit'})}</p><div style="margin-top:6px;font-size:11px;line-height:1.6;white-space:pre-wrap">${esc(chunk.content)}</div></div></div>`).join("");
  const body = `<div class="trace-chain">${items || emptyState("No sources","Jawaban ini tidak dikutip dari dokumen knowledge base.")}</div>`;
  el("#modal-root").innerHTML = modal({title:"Knowledge sources",body,wide:true});
}

async function openConversation(id) {
  state.selectedConversationId = id; state.messages = [];
  el("#conversation-chat").innerHTML = `<div class="loading-state"><div class="thinking"><i></i><i></i><i></i></div></div>`;
  try { state.messages = await api.messages(id); el("#conversation-chat").innerHTML = renderMessagePanel(); }
  catch (error) { el("#conversation-chat").innerHTML = errorState(error.message); }
  els(".conversation-row").forEach((row) => row.classList.toggle("active", row.dataset.conversationId === id));
}

function destroyChart(key) { if (state.charts[key]) { state.charts[key].destroy(); delete state.charts[key]; } }
function drawChart(key, selector, rows, type = "bar") {
  const canvas = el(selector); if (!canvas || !window.Chart) return; destroyChart(key);
  const labels = rows.map((row) => String(row.date || row.label || "").slice(5));
  const values = rows.map((row) => Number(row.convs ?? row.value ?? row.cost ?? 0));
  state.charts[key] = new Chart(canvas, { type, data:{labels,datasets:[{data:values,borderColor:'#ffffff',backgroundColor:type==='line'?'rgba(255,255,255,.1)':'rgba(255,255,255,.7)',fill:type==='line',tension:.38,borderWidth:2,pointRadius:0,borderRadius:5}]}, options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#6e6e6e',font:{size:9}}},y:{beginAtZero:true,grid:{color:'rgba(255,255,255,.06)'},ticks:{color:'#6e6e6e',font:{size:9}}}}} });
}

function drawDoughnutChart(key, selector, labels, values) {
  const canvas = el(selector); if (!canvas || !window.Chart) return; destroyChart(key);
  state.charts[key] = new Chart(canvas, { type:"doughnut", data:{labels,datasets:[{data:values,backgroundColor:['#333333','#c99a3e','#2e9e73'],borderWidth:0}]}, options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#6e6e6e',font:{size:10},boxWidth:10}}},cutout:'65%'} });
}

async function renderAnalytics(days = state.analyticsDays) {
  loadingPage(t('page.analytics.title'), t('page.analytics.subtitle'));
  if (!state.selectedBotId) { setPage(pageHeader(t('page.analytics.title'), t('page.analytics.subtitle')) + emptyState(t('page.analytics.no_agent'), t('page.analytics.no_agent_desc'))); return; }
  state.analyticsDays = Number(days) || 30;
  try { state.analytics = await api.botAnalytics(state.selectedBotId, state.analyticsDays); }
  catch (error) { setPage(errorState(error.message)); return; }
  const summary = state.analytics.summary || {};
  const resolution = summary.total_convs ? Math.round((1-(summary.handoff_count||0)/summary.total_convs)*100) : 0;
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const questions = state.analytics.top_questions || [];
  const questionRows = questions.map((q,index) => `<tr><td class="mono">${String(index+1).padStart(2,'0')}</td><td><span class="table-title">${esc(q.content)}</span></td><td>${formatNumber(q.frequency)}</td><td><div class="progress" style="min-width:100px"><span style="width:${Math.max(6,Math.round((q.frequency/(questions[0]?.frequency||1))*100))}%"></span></div></td></tr>`).join("");
  const periodTabs = [7, 30, 90].map((d) =>
    `<button class="${state.analyticsDays===d?'active':''}" data-analytics-days="${d}">${d === 90 ? '90d' : d === 30 ? '30d' : '7d'}</button>`
  ).join('');
  const coveragePct = Math.max(0, 100 - Math.round((summary.handoff_count||0) / (summary.total_convs||1) * 100));
  setPage(`${pageHeader(t('page.analytics.title'), t('page.analytics.subtitle'),`<div style="display:flex;gap:8px;align-items:center"><select class="select" data-analytics-bot aria-label="Switch agent">${options}</select><div class="analytics-period-row" role="group" aria-label="Time period">${periodTabs}</div></div>`)}
  <div class="grid grid-4">${metricCard(t('page.conv.all_tab')+" "+t('page.agents.convs'),formatNumber(summary.total_convs),`${formatNumber(summary.total_msgs)} pesan`,"chat")}${metricCard("AI Resolution",`${resolution}%`,`${summary.handoff_count||0} handoff`,"dashboard",resolution>=80?'trend-up':'')}${metricCard("Avg Rating",summary.avg_rating?`${Number(summary.avg_rating).toFixed(1)}/5`:'—',"Kepuasan pelanggan","analytics")}${metricCard("AI Latency",summary.avg_latency_ms?`${Math.round(summary.avg_latency_ms)}ms`:'—',"Waktu respons","agents")}</div>
  <div class="page-section-label">Volume Percakapan</div>
  <div class="grid grid-2">
    <div class="card"><div class="card-head"><h3>Percakapan harian</h3><span class="status-badge active">Live</span></div><div class="card-body"><div style="height:280px"><canvas id="analytics-chart"></canvas></div></div></div>
    <div class="card"><div class="card-head"><h3>Kualitas layanan</h3><span class="subtle">${state.analyticsDays} hari terakhir</span></div><div class="card-body analytics-quality-rows">
      <div class="usage-row"><div class="usage-row-head"><span>AI resolution</span><b>${resolution}%</b></div><div class="progress"><span class="${resolution>=80?'bar-green':'bar-amber'}" style="width:${resolution}%"></span></div></div>
      <div class="usage-row"><div class="usage-row-head"><span>Customer rating</span><b>${summary.avg_rating ? Number(summary.avg_rating).toFixed(1) : 0}/5</b></div><div class="progress"><span class="${Number(summary.avg_rating||0)>=4?'bar-green':'bar-amber'}" style="width:${Math.min(100,Number(summary.avg_rating||0)*20)}%"></span></div></div>
      <div class="usage-row"><div class="usage-row-head"><span>Automated coverage</span><b>${coveragePct}%</b></div><div class="progress"><span class="${coveragePct>=80?'bar-green':'bar-amber'}" style="width:${coveragePct}%"></span></div></div>
    </div></div>
  </div>
  <div class="page-section-label">Intelijen Pelanggan</div>
  <div class="card"><div class="card-head"><div><h3>${t('page.analytics.top_questions')}</h3><span class="subtle">Diekstrak dari riwayat percakapan nyata</span></div><span class="status-badge active">${state.analyticsDays}d window</span></div>${questionRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th style="width:36px">#</th><th>${t('page.analytics.question')}</th><th>${t('page.analytics.frequency')}</th><th>Permintaan</th></tr></thead><tbody>${questionRows}</tbody></table></div>`:emptyState("Belum ada data","Pertanyaan teratas muncul setelah pelanggan berinteraksi dengan agent ini.")}</div>`);
  drawChart("analytics","#analytics-chart",state.analytics.daily_volume||[],"bar");
}

async function renderRoutingLogs() {
  loadingPage("Routing Logs","Per-message Intent Router decisions: intent, selected agent, confidence, and handoff status.");
  const hasAnalytics = (state.rbac?.permissions || []).includes("analytics.read");
  if (!hasAnalytics) { setPage(pageHeader("Routing Logs","Akses terbatas untuk role dengan izin analytics.read.") + emptyState("Akses ditolak","Role kamu tidak memiliki izin untuk melihat Routing Logs.")); return; }
  if (!state.selectedBotId) { setPage(pageHeader("Routing Logs","Per-message Intent Router decisions.") + emptyState("No agent selected","Pilih agent untuk melihat routing log.")); return; }
  let data;
  try { data = await api.routingLogs(state.selectedBotId); }
  catch (error) { setPage(errorState(error.message)); return; }
  const logs = data.logs || [];
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const intentColor = { general:"default", business:"training", faq:"active", sales:"training", customer_service:"warning", knowledge:"active", analytics:"active", human_handoff:"error" };
  const rows = logs.map((log) => `<tr>
    <td class="mono">${relativeTime(log.created_at)}</td>
    <td>${esc(log.end_user_name || log.end_user_email || 'Anonymous')}</td>
    <td class="truncate" style="max-width:200px" title="${esc(log.content)}">${esc((log.content||'').slice(0,80))}</td>
    <td>${statusBadge(intentColor[log.intent]||'default', log.intent||'—')}</td>
    <td>${esc(log.selected_agent||'—')}</td>
    <td>${log.routing_confidence!=null ? `${Math.round(Number(log.routing_confidence)*100)}%` : '—'}</td>
    <td>${log.handoff_status ? statusBadge('error',log.handoff_status) : statusBadge('active','No handoff')}</td>
  </tr>`).join("");
  setPage(`${pageHeader("Routing Logs","Intent Router decisions per pesan — intent, selected agent, confidence, dan handoff status.",`<select class="select" data-routing-logs-bot>${options}</select>`)}
  <div class="page-section-label">Routing decisions — ${logs.length} entri terakhir</div>
  <div class="card"><div class="card-head"><div><h3>Routing decisions</h3><span class="subtle">Intent, agent terpilih, confidence score, dan handoff status per pesan</span></div><span class="subtle mono" style="font-size:9px">${logs.length} messages</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Customer</th><th>Message</th><th>Intent</th><th>Selected Agent</th><th>Confidence</th><th>Handoff</th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("No routing data","Kirim beberapa pesan ke agent ini untuk mengisi routing log.")}</div>`);
}

async function renderObservability(days = state.observabilityDays) {
  state.observabilityDays = Number(days) || 7;
  loadingPage("AI Observability","Inspect agent health, latency, token usage, and request traces.");
  let data;
  try { data = await api.observabilitySummary(state.observabilityDays); }
  catch (error) { setPage(errorState(error.message)); return; }
  const metrics = data.metrics || {};
  const agentRows = (data.agents || []).map((agent) => {
    const latest=agent.last_status||'unknown';
    // Semantik warna: error→FAILED (merah), skipped→IDLE (kuning, valid tanpa
    // tugas), success→HEALTHY (hijau), running→RUNNING. Merah HANYA untuk error nyata.
    let kind='pending', label='idle';
    if(agent.stalled){ kind='inactive'; label='○ offline (stalled)'; }   // running yg macet → mati
    else if(latest==='error'){ kind='error'; label='failed'; }
    else if(latest==='success'){ kind='active'; label='healthy'; }
    else if(latest==='running'){ kind='pending'; label='running'; }
    else if(latest==='retrying'){ kind='pending'; label='↻ retrying'; }
    else if(latest==='waiting'){ kind='pending'; label='⧗ waiting'; }
    else if(latest==='cancelled'){ kind='inactive'; label='⊘ cancelled'; }
    else if(latest==='skipped'){ kind='pending'; label='idle'; }
    // Tooltip alasan: untuk FAILED tampilkan error nyata (root cause), bukan hanya "failed".
    const reason = latest==='error' ? (agent.last_error || 'Error tanpa detail') : (latest==='skipped' ? 'Idle — tidak ada tugas untuk agent ini' : '');
    const title = reason ? ` title="${esc(reason)}"` : (agent.failures?` title="${formatNumber(agent.failures)} kegagalan historis di window ini"`:'');
    const retries = Number(agent.retries || 0);
    const retryBadge = retries > 0 ? ` <span class="subtle" style="font-size:10px;color:#c99a3e" title="${retries} auto-retry transient (exponential backoff)">↻ ${formatNumber(retries)}</span>` : '';
    // Baris FAILED bisa diklik → panel detail (Agent/Task/Error/Stacktrace/Retry/Root Cause/Fix).
    const clickAttr = latest==='error' ? ` data-obs-agent-error="${esc(agent.agent_name)}" style="cursor:pointer" title="Klik untuk detail error"` : '';
    const errHint = latest==='error'&&agent.last_error ? `<div class="subtle" style="font-size:10px;color:#f87171;margin-top:2px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(agent.last_error)} <span style="color:var(--accent,#7c3aed)">· detail →</span></div>` : '';
    return `<tr data-agent-row="${esc(agent.agent_name)}"${clickAttr}><td><span class="table-title mono">${esc(agent.agent_name)}</span></td><td>${formatNumber(agent.executions)}</td><td data-agent-status="${esc(agent.agent_name)}"><span${title}>${statusBadge(kind,label)}</span>${retryBadge}${errHint}</td><td>${Math.round(agent.average_latency_ms || 0)}ms</td><td>${formatNumber(agent.total_tokens)}</td><td>${agent.last_seen_at ? relativeTime(agent.last_seen_at) : '—'}</td></tr>`;
  }).join("");
  const traceRows = (data.traces || []).map((trace) => `<tr data-observability-trace="${esc(trace.id)}"><td class="mono">${esc(String(trace.id).slice(0,8))}</td><td><span class="table-title trace-question">${esc(trace.user_question)}</span></td><td>${statusBadge(trace.status === 'success' ? 'active' : trace.status, trace.status)}</td><td>${formatNumber(trace.agent_count)} agents</td><td>${trace.duration_ms || 0}ms</td><td>${formatNumber(trace.total_tokens)}</td><td>${relativeTime(trace.started_at)}</td></tr>`).join("");
  setPage(`${pageHeader("AI Observability","Every request and agent lifecycle is recorded for operational debugging.",`<button class="button" data-action="agent-self-test">${icon('refresh',14)} Jalankan Self-Test</button><select class="select" data-observability-days><option value="1" ${state.observabilityDays===1?'selected':''}>24 hours</option><option value="7" ${state.observabilityDays===7?'selected':''}>7 days</option><option value="30" ${state.observabilityDays===30?'selected':''}>30 days</option><option value="90" ${state.observabilityDays===90?'selected':''}>90 days</option></select>`)}
  <div class="grid grid-3 observability-metrics" style="margin-bottom:16px">${metricCard("Active Agents",formatNumber(metrics.active_agents),"Currently executing","agents")}${metricCard("Failed Agents",formatNumber(metrics.failed_agents),"Executions in selected window","observability",metrics.failed_agents?'trend-down':'trend-up')}${metricCard("Average Latency",`${Math.round(metrics.average_latency_ms||0)}ms`,"Per agent execution","analytics")}${metricCard("Token Usage",formatNumber(metrics.total_tokens),`${formatNumber(metrics.prompt_tokens)} prompt · ${formatNumber(metrics.completion_tokens)} completion`,"billing")}${metricCard("Success Rate",`${Number(metrics.success_rate||0).toFixed(1)}%`,"Completed executions","dashboard","trend-up")}${metricCard("Error Rate",`${Number(metrics.error_rate||0).toFixed(1)}%`,"Failed executions","observability",metrics.error_rate?'trend-down':'trend-up')}</div>
  <div class="page-section-label">Realtime activity <span id="obs-live-dot" class="obs-live-dot" title="Menghubungkan realtime…">●</span></div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Live Activity</h3><span class="subtle">Status agent tampil di sini secara realtime — tanpa reload</span></div></div>
    <div id="obs-live-feed" class="obs-live-feed"><div class="subtle" style="padding:14px;font-size:12px">Menunggu aktivitas agent…</div></div>
  </div>
  <div class="page-section-label">Agent health</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Agent health</h3><span class="subtle">Latency, failures, and token consumption per agent</span></div></div>${agentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Executions</th><th>Status</th><th>Avg latency</th><th>Tokens</th><th>Last seen</th></tr></thead><tbody>${agentRows}</tbody></table></div>`:emptyState("No execution data","Send a message to an AI agent to create the first trace.")}</div>
  <div class="page-section-label">Request traces</div>
  <div class="card"><div class="card-head"><div><h3>Agent Trace Viewer</h3><span class="subtle">Open a request to inspect its complete execution chain</span></div></div>${traceRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Trace</th><th>User question</th><th>Status</th><th>Chain</th><th>Latency</th><th>Tokens</th><th>Started</th></tr></thead><tbody>${traceRows}</tbody></table></div>`:emptyState("No traces yet","Request traces will appear here after an agent handles a message.")}</div>`);
  openObservabilityWs();   // aktifkan realtime (status berubah tanpa reload)
}

async function openObservabilityTrace(traceId) {
  let data;
  try { data = await api.observabilityTrace(traceId); }
  catch (error) { toast(error.message,"error"); return; }
  const trace = data.trace || {};
  const steps = (data.executions || []).map((step, index) => `<div class="trace-step ${step.status}"><span class="trace-node">${index + 1}</span><div><strong>${esc(step.agent_name)}</strong><p>${esc(step.status)} · ${step.duration_ms || 0}ms · ${formatNumber(step.total_tokens)} tokens${step.confidence_score != null ? ` · confidence ${Number(step.confidence_score).toFixed(1)}` : ''}</p>${step.error_message?`<div class="trace-error">${esc(step.error_message)}</div>`:''}${step.metadata && Object.keys(step.metadata).length?`<pre>${esc(JSON.stringify(step.metadata,null,2))}</pre>`:''}</div></div>`).join("");
  const body = `<div class="trace-summary"><span class="eyebrow">USER QUESTION</span><p>${esc(trace.user_question)}</p></div><div class="trace-chain">${steps}</div><div class="trace-summary final"><span class="eyebrow">FINAL ANSWER</span><div>${renderMarkdown(trace.final_answer || 'No final answer recorded.')}</div></div><div class="trace-totals"><span>${trace.duration_ms || 0}ms total</span><span>${formatNumber(trace.prompt_tokens)} prompt</span><span>${formatNumber(trace.completion_tokens)} completion</span><span>${formatNumber(trace.total_tokens)} tokens</span></div>`;
  el("#modal-root").innerHTML = modal({title:`Agent Trace ${String(trace.id).slice(0,8)}`,body,wide:true});
}

// ── Realtime observability WebSocket ────────────────────────────────────────
let _obsWs = null;
let _obsHbTimer = null;
function closeObservabilityWs() {
  if (_obsHbTimer) { clearInterval(_obsHbTimer); _obsHbTimer = null; }
  if (_obsWs) { try { _obsWs.onclose = null; _obsWs.close(); } catch(_) {} _obsWs = null; }
}
function _obsLiveDot(state) {
  const dot = document.getElementById("obs-live-dot");
  if (dot) { dot.className = `obs-live-dot ${state}`; dot.title = state === "on" ? "Realtime terhubung" : "Realtime terputus"; }
}
function _obsStatusMeta(status) {
  return ({ running:["#60a5fa","◍ running"], retrying:["#c99a3e","↻ retrying"], waiting:["#c99a3e","⧗ waiting"],
            success:["#34d399","✓ success"], skipped:["#c99a3e","○ idle"], cancelled:["var(--text-3)","⊘ cancelled"],
            error:["#f87171","✕ failed"] }[status] || ["var(--text-3)", status]);
}
function _obsHandleEvent(ev) {
  if (!ev || ev.type !== "agent") return;
  const [color, label] = _obsStatusMeta(ev.status);
  // 1) Prepend ke live feed
  const feed = document.getElementById("obs-live-feed");
  if (feed) {
    if (feed.querySelector(".subtle")) feed.innerHTML = "";
    const line = document.createElement("div");
    line.className = "obs-live-line";
    const extra = ev.status === "retrying" ? ` (retry ${ev.retry_count||0})` : (ev.status === "error" && ev.error_message ? ` — ${ev.error_message}` : "");
    line.innerHTML = `<span class="obs-live-time">${new Date().toLocaleTimeString('id-ID')}</span><span class="mono">${esc(ev.agent_name)}</span><span style="color:${color};font-weight:600">${label}${esc(extra)}</span>`;
    feed.prepend(line);
    while (feed.children.length > 40) feed.removeChild(feed.lastChild);
  }
  // 2) Update badge status agent di tabel Agent health (tanpa reload)
  const cell = document.querySelector(`[data-agent-status="${(window.CSS&&CSS.escape)?CSS.escape(ev.agent_name):ev.agent_name}"]`);
  if (cell) { cell.querySelector("span")?.remove?.(); cell.insertAdjacentHTML("afterbegin", `<span style="font-size:11px;font-weight:700;color:${color}">${label}</span> `); }
}
function openObservabilityWs() {
  closeObservabilityWs();
  const token = tokenStore.get();
  if (!token) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try {
    const ws = new WebSocket(`${proto}://${location.host}/api/observability/ws?token=${encodeURIComponent(token)}`);
    _obsWs = ws;
    ws.onopen = () => {
      _obsLiveDot("on");
      // Heartbeat tiap 10 dtk → jaga koneksi hidup & deteksi cepat bila mati.
      if (_obsHbTimer) clearInterval(_obsHbTimer);
      _obsHbTimer = setInterval(() => {
        if (ws.readyState === 1) { try { ws.send(JSON.stringify({ type: "ping", ts: Date.now() })); } catch(_) { _obsLiveDot("off"); } }
        else { _obsLiveDot("off"); }
      }, 10000);
    };
    ws.onclose = () => { if (_obsHbTimer) { clearInterval(_obsHbTimer); _obsHbTimer = null; } _obsLiveDot("off"); if (state.route === "observability") setTimeout(() => { if (state.route === "observability") openObservabilityWs(); }, 4000); };
    ws.onerror = () => _obsLiveDot("off");
    ws.onmessage = (m) => { try { _obsHandleEvent(JSON.parse(m.data)); } catch(_) {} };
  } catch(_) { _obsLiveDot("off"); }
}

async function runAgentSelfTest() {
  toast("Menjalankan self-test semua agent…", "info");
  let r;
  try { r = await api.agentSelfTest(); }
  catch (error) { toast(error.message, "error"); return; }
  const rows = (r.agents || []).map(a => {
    const ok = a.status === "ok";
    const badge = ok ? '<span style="color:#22c55e;font-weight:700">✓ OK</span>' : '<span style="color:#f87171;font-weight:700">✕ FAILED</span>';
    const detail = ok
      ? `<span class="subtle" style="font-size:11px">entrypoint <code>${esc(a.entrypoint||'-')}()</code> · ${a.duration_ms||0}ms</span>`
      : `<div class="subtle" style="font-size:11px;color:#f87171">${esc(a.error||'')}</div><div class="subtle" style="font-size:11px">↳ ${esc(a.root_cause||'')} · <b>fix:</b> ${esc(a.suggested_fix||'')}</div>`;
    return `<tr><td>${badge}</td><td><span class="mono">${esc(a.agent)}</span> <span class="subtle" style="font-size:10px">${esc(a.category||'')}</span></td><td>${detail}</td></tr>`;
  }).join("");
  const summary = `<div style="display:flex;gap:14px;margin-bottom:12px">
    <span style="font-size:22px;font-weight:800">${formatNumber(r.total||0)} <span class="subtle" style="font-size:12px">agent</span></span>
    <span style="font-size:22px;font-weight:800;color:#22c55e">${formatNumber(r.ok||0)} <span class="subtle" style="font-size:12px">OK</span></span>
    <span style="font-size:22px;font-weight:800;color:${r.failed?'#f87171':'var(--text-3)'}">${formatNumber(r.failed||0)} <span class="subtle" style="font-size:12px">gagal</span></span>
  </div>`;
  const body = `${summary}<div class="table-wrap"><table class="data-table"><thead><tr><th>Status</th><th>Agent</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="subtle" style="font-size:11px;margin-top:10px">Self-test meng-instansiasi tiap agent (menjalankan __init__ nyata) + memverifikasi entrypoint. Kegagalan = import/dependency/konstruktor/config bermasalah, dilaporkan lengkap dengan root cause.</p>`;
  el("#modal-root").innerHTML = modal({title:`Agent Self-Test — ${r.failed?`${r.failed} gagal`:'semua OK'}`,body,wide:true});
  toast(r.failed ? `Self-test: ${r.failed} agent gagal.` : `Self-test: semua ${r.ok} agent OK ✓`, r.failed ? "error" : "success");
}

async function openAgentErrorDetail(agentName) {
  let d;
  try { d = await api.observabilityAgentError(agentName); }
  catch (error) { toast(error.status===404 ? "Tidak ada detail error untuk agent ini." : error.message, "error"); return; }
  const row = (label, value, mono) => `<div style="margin-bottom:12px"><div class="eyebrow" style="font-size:10px;margin-bottom:3px">${esc(label)}</div><div style="${mono?'font-family:monospace;':''}font-size:13px;color:var(--text)">${value}</div></div>`;
  const body = `
    ${row('AGENT', `<span class="mono">${esc(d.agent_name)}</span> · ${relativeTime(d.execution_start)} · ${d.duration_ms||0}ms`)}
    ${row('TASK', esc(d.task || '—'))}
    ${row('ERROR', `<span style="color:#f87171">${esc(d.error_message || '—')}</span>`)}
    ${row('RETRY COUNT', `${formatNumber(d.retry_count||0)}× auto-retry ${Number(d.retry_count)>0?'(exponential backoff)':''}`)}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div style="background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.25);border-radius:8px;padding:10px 12px">
        <div class="eyebrow" style="font-size:10px;color:#fbbf24">ROOT CAUSE</div>
        <div style="font-size:12.5px;margin-top:4px">${esc(d.root_cause || '—')}</div>
      </div>
      <div style="background:rgba(34,197,94,.06);border:1px solid rgba(34,197,94,.25);border-radius:8px;padding:10px 12px">
        <div class="eyebrow" style="font-size:10px;color:#34d399">SUGGESTED FIX</div>
        <div style="font-size:12.5px;margin-top:4px">${esc(d.suggested_fix || '—')}</div>
      </div>
    </div>
    <div style="margin-top:14px"><div class="eyebrow" style="font-size:10px;margin-bottom:4px">STACKTRACE</div>
      <pre class="ca-out" style="max-height:300px">${d.error_stack ? esc(d.error_stack) : 'Stacktrace tidak tersimpan (kegagalan lama sebelum fitur ini, atau error tanpa traceback).'}</pre>
    </div>`;
  el("#modal-root").innerHTML = modal({title:`Error Detail — ${esc(d.agent_name)}`,body,wide:true});
}

function usd(value, digits = 4) { return `$${Number(value || 0).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits})}`; }

function costBreakdownTable(rows, heading) {
  const body = (rows || []).map((row) => `<tr><td><span class="table-title">${esc(row.label || 'unknown')}</span></td><td>${usd(row.cost,6)}</td><td>${formatNumber(row.tokens)}</td><td>${formatNumber(row.calls)}</td></tr>`).join("");
  return `<div class="card"><div class="card-head"><h3>${esc(heading)}</h3></div>${body?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Dimension</th><th>Cost</th><th>Tokens</th><th>Calls</th></tr></thead><tbody>${body}</tbody></table></div>`:emptyState("No cost data","Cost appears after an AI model processes tokens.")}</div>`;
}

async function renderCostIntelligence() {
  loadingPage("Cost Intelligence","Track AI operating cost and protect tenant budgets.");
  try { state.costIntelligence = await api.costIntelligence(); }
  catch (error) { setPage(errorState(error.message)); return; }
  const data = state.costIntelligence || {};
  const budget = data.budget || {};
  const pct = Math.min(100,Number(budget.percentage||0));
  const budgetClass = ['warning','critical','exceeded'].includes(budget.level) ? budget.level : 'healthy';
  const tenantRows = (data.cost_by_tenant || []).map((row) => `<tr><td><span class="table-title">${esc(row.name)}</span><div class="subtle mono">${esc(row.tenant_id)}</div></td><td>${usd(row.cost,6)}</td><td>${formatNumber(row.tokens)}</td></tr>`).join("");
  const routingRows = (data.model_routing || []).map((row) => `<tr><td>${statusBadge(row.task_complexity==='simple'?'active':'training',row.task_complexity)}</td><td class="mono">${esc(row.routed_model||'default')}</td><td>${formatNumber(row.requests)}</td></tr>`).join("");
  const budgetPanel = `<div class="card budget-card ${budgetClass}"><div class="card-head"><div><h3>Monthly Budget</h3><span class="subtle">${esc(budget.message||'')}</span></div>${statusBadge(budgetClass,budget.level||'unconfigured')}</div><div class="card-body"><div class="budget-amount"><strong>${usd(data.monthly_cost,4)}</strong><span>of ${budget.monthly_budget_usd?usd(budget.monthly_budget_usd,2):'not configured'}</span></div><div class="progress budget-progress"><span style="width:${pct}%"></span></div><div class="budget-thresholds"><span>80% warning</span><span>90% critical</span><span>100% exceeded</span></div><form data-cost-budget-form class="budget-form"><label class="field"><span>Monthly budget (USD)</span><input name="monthly_budget_usd" type="number" min="0" step="0.01" value="${Number(budget.monthly_budget_usd||0)}" required></label><button class="button button-primary" type="submit">Save budget</button></form></div></div>`;
  setPage(`${pageHeader("Cost Intelligence","FinOps visibility for every tenant, channel, conversation, agent, and model.",`<span class="status-badge active">USD estimated provider cost</span>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Monthly Cost",usd(data.monthly_cost),`${formatNumber(data.monthly_calls)} model calls`,"costs")}${metricCard("Daily Cost",usd(data.daily_cost),"Cost since 00:00 UTC","analytics")}${metricCard("Projected Month",usd(data.projected_monthly_cost),"Run-rate projection","billing")}${metricCard("Monthly Tokens",formatNumber(data.monthly_tokens),"Prompt + completion","observability")}</div>
  <div class="page-section-label">Budget & projections</div>
  <div class="grid grid-2" style="margin-bottom:16px">${budgetPanel}<div class="card"><div class="card-head"><div><h3>Daily AI Cost</h3><span class="subtle">Last 30 days</span></div></div><div class="card-body"><div style="height:270px"><canvas id="cost-daily-chart"></canvas></div></div></div></div>
  <div class="page-section-label">Cost breakdown</div>
  <div class="grid grid-2" style="margin-bottom:16px">${costBreakdownTable(data.cost_by_agent,"Cost By Agent")}${costBreakdownTable(data.cost_by_model,"Cost By Model")}${costBreakdownTable(data.cost_by_channel,"Cost By Channel")}${costBreakdownTable(data.cost_by_conversation,"Cost By Conversation")}</div>
  <div class="page-section-label">Distribution</div>
  <div class="grid grid-2"><div class="card"><div class="card-head"><div><h3>Cost By Tenant</h3><span class="subtle">Current tenant scope</span></div></div>${tenantRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tenant</th><th>Cost</th><th>Tokens</th></tr></thead><tbody>${tenantRows}</tbody></table></div>`:emptyState("No tenant cost","No model usage recorded this month.")}</div><div class="card"><div class="card-head"><div><h3>Model Routing</h3><span class="subtle">Simple → economy · Complex → quality</span></div></div>${routingRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Task</th><th>Model</th><th>Requests</th></tr></thead><tbody>${routingRows}</tbody></table></div>`:emptyState("No routing data","Model route decisions appear after AI requests.")}</div></div>`);
  drawChart("cost-daily","#cost-daily-chart",data.daily_costs||[],"line");
}

async function updateCostBudget(form) {
  if(!form.reportValidity()) return;
  const value = Number(new FormData(form).get("monthly_budget_usd") || 0);
  try { await api.updateCostBudget(value); toast("Monthly AI budget updated.","success"); await renderCostIntelligence(); }
  catch(error) { toast(error.message,"error"); }
}

async function renderMarketplace() {
  loadingPage("Agent Marketplace", "Install professional AI agents in one click, then ground each one with isolated knowledge.");
  try {
    const [templatesResult, installsResult, categoriesResult, analyticsResult, recommendedResult] = await Promise.all([
      api.marketplaceTemplates(), api.marketplaceInstalls(), api.marketplaceCategories(), api.marketplaceAnalytics(), api.marketplaceRecommended("", 12),
    ]);
    state.marketplace = {
      templates: templatesResult.templates || [],
      installs: installsResult.installs || [],
      categories: categoriesResult.categories || [],
      analytics: analyticsResult || {},
      recommended: recommendedResult.templates || [],
    };
  } catch (error) { setPage(errorState(error.message)); return; }

  // Publisher: template milik org + earnings (toleran — 403 utk non-publisher).
  try { state.marketplace.myTemplates = (await api.marketplaceMyTemplates()).templates || []; }
  catch { state.marketplace.myTemplates = []; }
  try { state.marketplace.earnings = await api.marketplaceEarnings(); }
  catch { state.marketplace.earnings = null; }

  state.marketplaceFilters ||= { search:"", category:"" };
  const filters = state.marketplaceFilters;
  const templates = state.marketplace?.templates || [];
  const installs = state.marketplace?.installs || [];
  const categories = state.marketplace?.categories || [];
  const analytics = state.marketplace?.analytics || {};
  const installedByKey = new Map(installs.map((item) => [item.template_key, item]));
  const normalizedSearch = String(filters.search || "").toLowerCase().trim();
  const filteredTemplates = templates.filter((template) => {
    const categoryOk = !filters.category || template.category === filters.category;
    const text = `${template.name} ${template.category} ${template.description}`.toLowerCase();
    const searchOk = !normalizedSearch || text.includes(normalizedSearch);
    return categoryOk && searchOk;
  });
  const featured = templates.filter((item) => item.featured).slice(0, 8);
  const trending = [...templates].sort((a,b)=>Number(b.install_count||0)-Number(a.install_count||0)).slice(0, 8);
  const recommended = (state.marketplace?.recommended || []).slice(0, 8);

  const marketplaceAgentCard = (template) => {
    const install = installedByKey.get(template.key);
    const installed = Boolean(install);
    const tools = (template.tools || []).slice(0, 3).map((tool)=>`<span>${esc(String(tool).replace(/_/g," "))}</span>`).join("");
    const starters = (template.starter_questions || []).slice(0, 2).map((q)=>`<li>${esc(q)}</li>`).join("");
    const color = template.primary_color || "#3d6791";
    return `<article class="card card-hover marketplace-agent-card" style="--agent-color:${esc(color)}">
      <div class="marketplace-agent-top"><span class="marketplace-agent-icon">${icon(template.icon || 'agents',18)}</span><div><h3>${esc(template.name)}</h3><p>${esc(template.category)}</p></div></div>
      <p class="marketplace-agent-desc">${esc(template.description)}</p>
      <div class="marketplace-agent-meta"><span>★ ${Number(template.rating || 0).toFixed(1)}</span><span>${formatNumber(template.install_count || 0)} installs</span><span>v${esc(template.version || '1.0.0')}</span></div>
      <div class="marketplace-tool-tags">${tools || '<span>knowledge base</span><span>prompt</span><span>workflow</span>'}</div>
      ${starters ? `<ul class="marketplace-starters">${starters}</ul>` : ''}
      <div class="marketplace-agent-actions"><span class="status-badge ${installed ? 'active' : template.is_paid ? 'pending' : 'ready'}">${installed ? t('marketplace.installed') : template.is_paid ? idr(template.price_idr) : t('marketplace.free')}</span><div>${installed ? `<button class="button" data-marketplace-update="${esc(install.id)}">${t('marketplace.update')}</button><button class="button button-danger" data-marketplace-uninstall="${esc(install.id)}">${t('marketplace.uninstall')}</button>` : `<button class="button button-primary" data-action="marketplace-install" data-marketplace-install="${esc(template.key)}">${template.is_paid ? t('marketplace.buy') : t('marketplace.install')}</button>`}</div></div>
    </article>`;
  };

  const categoryCards = categories.map((category) => `<button class="marketplace-chip ${filters.category===category.name?'active':''}" data-marketplace-category="${esc(category.name)}" style="--category-color:${esc(category.color || '#3d6791')}">${icon(category.icon || 'agents',15)}<span>${esc(category.name)}</span><span class="chip-count">${formatNumber(category.template_count || 0)}</span></button>`).join("");
  const installedRows = installs.map((item) => `<tr><td><span class="table-title">${esc(item.template_name)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(item.template_key)} · ${esc(item.template_version || '1.0.0')}</div></td><td>${esc(item.template_category || 'Business')}</td><td>${statusBadge(item.bot_status || 'inactive', item.bot_status || 'inactive')}</td><td>${esc(item.bot_name || '—')}</td><td>${relativeTime(item.installed_at)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap"><button class="button" data-marketplace-update="${esc(item.id)}">${t('marketplace.update')}</button><button class="button button-danger" data-marketplace-uninstall="${esc(item.id)}">${t('marketplace.uninstall')}</button></div></td></tr>`).join('');

  const actions = `<div class="marketplace-controls"><label class="search-box marketplace-search">${icon('search',15)}<input data-marketplace-search value="${esc(filters.search)}" placeholder="${t('marketplace.search_ph').replace('{n}', formatNumber(templates.length))}"></label><select class="select" data-marketplace-category-select><option value="">${t('marketplace.all_categories')}</option>${categories.map((cat)=>`<option value="${esc(cat.name)}" ${filters.category===cat.name?'selected':''}>${esc(cat.name)}</option>`).join('')}</select><button class="button" data-marketplace-clear>${t('marketplace.clear')}</button></div>`;
  const hero = `<section class="marketplace-hero"><div><span class="ln-label" style="margin-bottom:14px">Agent Marketplace</span><h2>Pasang AI agent siap pakai dalam satu klik.</h2><p>Pilih dari ${formatNumber(analytics.template_count || templates.length)} template profesional. Setiap agent punya knowledge base terisolasi dan langsung terhubung ke Supervisor Routing.</p></div><div class="marketplace-hero-stats"><div><strong>${formatNumber(analytics.template_count || templates.length)}</strong><span>Template tersedia</span></div><div><strong>${formatNumber(analytics.installed_count || installs.length)}</strong><span>Terpasang di workspace</span></div><div><strong>${Number(analytics.average_rating || 0).toFixed(1)}</strong><span>Rating rata-rata</span></div></div></section>`;
  const featuredSection = featured.length ? `<section class="marketplace-section"><div class="section-head"><div><h3>Featured</h3><p>Agent paling populer untuk memulai</p></div><span class="status-badge active">${featured.length} pilihan</span></div><div class="marketplace-agent-grid">${featured.slice(0,4).map(marketplaceAgentCard).join('')}</div></section>` : '';
  const catalogSection = `<section class="marketplace-section"><div class="section-head"><div><h3>Semua agent</h3><p>${formatNumber(filteredTemplates.length)} template · knowledge &amp; prompt terisolasi per agent</p></div></div>${filteredTemplates.length ? `<div class="marketplace-agent-grid">${filteredTemplates.map(marketplaceAgentCard).join('')}</div>` : emptyState("Tidak ada agent yang cocok","Coba kata kunci atau kategori lain.")}</section>`;

  // Publisher: template milik org (buat → publish/unpublish → edit).
  const myTemplates = state.marketplace?.myTemplates || [];
  const myRows = myTemplates.map((t) => `<tr>
    <td><span class="table-title">${esc(t.name)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(t.key)}</div></td>
    <td>${esc(t.category || '—')}</td>
    <td>${t.is_paid ? idr(t.price_idr) : '<span class="subtle">Gratis</span>'}</td>
    <td>${statusBadge(t.status === 'published' ? 'active' : 'pending', t.status)}</td>
    <td>${formatNumber(t.install_count || 0)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      ${t.status === 'published'
        ? `<button class="button" data-mkt-unpublish="${esc(t.key)}">Unpublish</button>`
        : `<button class="button button-primary" data-mkt-publish="${esc(t.key)}">Publish</button>`}
      <button class="button" data-mkt-edit="${esc(t.key)}">Edit</button>
    </div></td></tr>`).join('');
  const earn = state.marketplace?.earnings;
  const earningsBar = earn ? `<div style="display:flex;gap:24px;padding:12px 16px;border-bottom:1px solid var(--border);font-size:12px">
    <div><span class="subtle">Total pendapatan</span><br><b style="font-size:15px">${idr(earn.total_earned_idr || 0)}</b></div>
    <div><span class="subtle">Menunggu payout</span><br><b style="font-size:15px">${idr(earn.pending_payout_idr || 0)}</b></div>
    <div><span class="subtle">Terjual</span><br><b style="font-size:15px">${formatNumber(earn.sales_count || 0)}</b></div>
  </div>` : '';
  const myTemplatesSection = `<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Template Saya</h3><span class="subtle" style="font-size:9px">Buat & publish agent template Anda sendiri ke marketplace · bagi hasil 70% publisher</span></div><button class="button button-primary" data-action="mkt-create">+ Buat Template</button></div>${earningsBar}${myRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Nama</th><th>Kategori</th><th>Harga</th><th>Status</th><th>Install</th><th>Aksi</th></tr></thead><tbody>${myRows}</tbody></table></div>` : emptyState("Belum ada template buatan Anda","Klik “Buat Template” untuk membuat & publish agent Anda sendiri.")}</div>`;

  setPage(`${pageHeader("Agent Marketplace","Pasang agent siap pakai, tambahkan knowledge, dan biarkan Supervisor Routing memilih spesialis terbaik.",actions)}${hero}<div class="marketplace-chips"><button class="marketplace-chip ${!filters.category?'active':''}" data-marketplace-category="">${icon('marketplace',15)}<span>Semua</span><span class="chip-count">${formatNumber(templates.length)}</span></button>${categoryCards}</div>${featuredSection}${catalogSection}${myTemplatesSection}<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Agent terpasang</h3><span class="subtle" style="font-size:9px">Kelola install per-tenant</span></div></div>${installedRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Template</th><th>Kategori</th><th>Status</th><th>Bot</th><th>Dipasang</th><th>Aksi</th></tr></thead><tbody>${installedRows}</tbody></table></div>` : emptyState("Belum ada agent terpasang","Pasang template untuk membuat AI agent pertama Anda.")}</div>`);
}

async function renderKnowledge() {
  loadingPage(t('page.knowledge.title'), t('page.knowledge.subtitle'));
  if (!state.selectedBotId) { setPage(pageHeader(t('page.knowledge.title'), t('page.knowledge.subtitle')) + emptyState(t('page.knowledge.no_agent_title'), t('page.knowledge.no_agent_desc'))); return; }
  const filters = state.knowledgeFilters || { status:"", category:"", agent_id:"", search:"" };
  try {
    const [docs, sourceResult, seedStatus] = await Promise.all([
      api.documents(state.selectedBotId),
      api.knowledgeSources({ bot_id:state.selectedBotId, status:filters.status, category:filters.category, agent_id:filters.agent_id, search:filters.search, limit:100 }),
      api.knowledgeSeedStatus({ bot_id:state.selectedBotId }),
    ]);
    state.documents = docs;
    state.knowledgeSources = sourceResult.sources || [];
    state.knowledgeStats = sourceResult.stats || {};
    state.knowledgeSeedStatus = seedStatus || {};
  } catch (error) { setPage(errorState(error.message)); return; }
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const stats = state.knowledgeStats || {};
  const seedStatus = state.knowledgeSeedStatus || {};
  const categories = [...new Set([...(seedStatus.per_category||[]).map((s)=>s.category), ...state.knowledgeSources.map((s)=>s.category)].filter(Boolean))].sort();
  const agents = [...new Set([...(seedStatus.per_agent||[]).map((s)=>s.agent_id), ...state.knowledgeSources.map((s)=>s.agent_type)].filter(Boolean))].sort();
  const categoryOptions = `<option value="">${t('marketplace.all_categories')}</option>` + categories.map((cat)=>`<option value="${esc(cat)}" ${filters.category===cat?'selected':''}>${esc(cat)}</option>`).join("");
  const agentOptions = `<option value="">All agents</option>` + agents.map((agent)=>`<option value="${esc(agent)}" ${filters.agent_id===agent?'selected':''}>${esc(agent.replace(/_/g,' '))}</option>`).join("");
  const statusOptions = ["","pending","crawling","indexed","failed","skipped"].map((status)=>`<option value="${esc(status)}" ${filters.status===status?'selected':''}>${status?esc(status):'All status'}</option>`).join("");
  const sourceRows = state.knowledgeSources.map((src) => {
    const failed = src.status === 'failed';
    const actions = `${failed?`<button class="button" data-retry-source="${esc(src.id)}">Retry</button>`:''}<button class="button button-danger" data-delete-source="${esc(src.id)}">Delete</button>`;
    return `<tr><td><span class="table-title">${esc(src.title || src.url)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px;max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(src.url)}</div>${src.error_message?`<div class="subtle" style="margin-top:4px;color:var(--danger)">${esc(src.error_message)}</div>`:''}</td><td>${esc(src.category || '-')}</td><td>${statusBadge(src.status,src.status)}</td><td>${esc(src.priority || 'normal')}</td><td>${formatDate(src.last_crawled_at || src.created_at)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap">${actions}</div></td></tr>`;
  }).join("");
  const docRows = state.documents.slice(0,8).map((doc) => {
    const sourceLabel = doc.source_type === 'url' ? 'Website URL' : 'File upload';
    const sourceInfo = doc.source_url ? `<div class="subtle mono" style="font-size:8px;margin-top:3px;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(doc.source_url)}</div>` : '';
    return `<tr><td><span class="table-title">${esc(doc.filename)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(sourceLabel)}</div>${sourceInfo}</td><td>${formatNumber(doc.chunk_count)}</td><td>${statusBadge(doc.status,doc.status)}</td><td><button class="button button-danger" data-delete-document="${esc(doc.id)}">Delete</button></td></tr>`;
  }).join("");
  const seedAgents = ["travel_agent","ecommerce_agent","clinic_agent","school_agent","sales_agent","property_agent","faq_agent","customer_service_agent","botnesia_business"];
  const seedButtons = seedAgents.map((agent)=>`<button class="button" data-seed-agent="${agent}">${esc(agent.replace(/_/g,' '))}</button>`).join("");
  const agentStatusRows = (seedStatus.per_agent || []).slice(0, 20).map((row)=>`<tr><td><span class="table-title">${esc(String(row.agent_id||'unknown').replace(/_/g,' '))}</span></td><td>${formatNumber(row.total)}</td><td>${formatNumber(row.pending)}</td><td>${formatNumber(row.crawling)}</td><td>${formatNumber(row.indexed)}</td><td>${formatNumber(row.failed)}</td></tr>`).join("");
  setPage(`${pageHeader(t('page.knowledge.title'), t('page.knowledge.subtitle'),`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="select" data-knowledge-bot>${options}</select><label class="button button-primary">${icon('upload',14)} ${t('page.knowledge.upload_btn')}<input type="file" data-document-upload accept=".pdf,.docx,.txt,.csv,.md,.markdown" hidden></label></div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Total URLs",formatNumber(stats.total),"Queued for selected agent","knowledge")}${metricCard("Pending",formatNumber(stats.pending),"Waiting for crawler","observability")}${metricCard("Crawling",formatNumber(stats.crawling),"Current batch","refresh")}${metricCard("Failed",formatNumber(stats.failed),"Retry failed in batch","learning",stats.failed?'trend-down':'')}</div>
  <div class="page-section-label">Import tools</div>
  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="card"><div class="card-head"><div><h3>${t('kb.bulk_title')}</h3><span class="subtle">${t('kb.bulk_desc')}</span></div></div><form data-bulk-url-form class="card-body" style="display:grid;gap:10px"><textarea class="input" name="urls" rows="8" placeholder="https://platform.openai.com/docs\nhttps://docs.python.org/3"></textarea><div style="display:flex;gap:8px;justify-content:flex-end"><button class="button button-primary" type="submit">${icon('link',14)} ${t('kb.import_btn')}</button></div></form></div>
    <div class="card"><div class="card-head"><div><h3>Agent Knowledge Seeder</h3><span class="subtle">Import seed JSON without crawling everything at once.</span></div></div><div class="card-body" style="display:flex;gap:8px;flex-wrap:wrap"><button class="button button-primary" data-seed-marketplace>${icon('marketplace',14)} Seed Marketplace 1000</button><button class="button" data-retry-failed-sources>${icon('refresh',14)} Retry failed</button><button class="button" data-seed-general>${icon('knowledge',14)} General AI</button><button class="button" data-seed-all-agents>All agent seeds</button>${seedButtons}</div></div>
  </div>
  <div class="page-section-label">URL per agent</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>URL per Agent</h3><span class="subtle">Marketplace knowledge isolation by agent_id</span></div></div>${agentStatusRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Total</th><th>Pending</th><th>Crawling</th><th>Indexed</th><th>Failed</th></tr></thead><tbody>${agentStatusRows}</tbody></table></div>`:emptyState("No agent URL queue","Seed marketplace URLs to see per-agent status.")}</div>
  <div class="page-section-label">Source tracking</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>${t('kb.source_title')}</h3><span class="subtle">${t('kb.source_desc')}</span></div><div style="display:flex;gap:8px;flex-wrap:wrap"><input class="input" data-source-search value="${esc(filters.search||'')}" placeholder="${t('kb.search_url')}" style="min-width:180px"><select class="select" data-source-status>${statusOptions}</select><select class="select" data-source-agent>${agentOptions}</select><select class="select" data-source-category>${categoryOptions}</select><button class="button" data-action="refresh">${icon('refresh',14)} ${t('common.refresh')}</button></div></div>${sourceRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('page.knowledge.col_url')}</th><th>${t('page.knowledge.col_category')}</th><th>${t('page.knowledge.col_status')}</th><th>${t('page.knowledge.col_priority')}</th><th>${t('page.knowledge.col_updated')}</th><th></th></tr></thead><tbody>${sourceRows}</tbody></table></div>`:emptyState(t('page.knowledge.empty_urls'),t('page.knowledge.empty_urls_desc'))}</div>
  <div class="page-section-label">Document library</div>
  <div class="card"><div class="card-head"><div><h3>Indexed Document Library</h3><span class="subtle">Latest processed documents and URL pages</span></div></div>${docRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Chunks</th><th>Status</th><th></th></tr></thead><tbody>${docRows}</tbody></table></div>`:emptyState("No indexed documents","Crawler output appears here after a source is indexed.")}</div>`);
}

async function renderKnowledgeBuilder() {
  loadingPage("Knowledge Builder","Auto-generate FAQ, SOP, summaries, categories, and quality scores from your documents.");
  if (!state.selectedBotId) { setPage(pageHeader("Knowledge Builder","Auto-generate knowledge from documents.") + emptyState("No agent available","Create an agent before building knowledge.")); return; }
  const [overviewResult, faqsResult, sopsResult] = await Promise.all([
    settle("kbOverview", api.kbOverview(state.selectedBotId)),
    settle("kbFaqs", api.kbFaqs(state.selectedBotId)),
    settle("kbSops", api.kbSops(state.selectedBotId)),
  ]);
  if (!overviewResult.ok) { setPage(errorState(overviewResult.error.message)); return; }
  state.kbOverview = overviewResult.data;
  state.kbFaqs = faqsResult.ok ? faqsResult.data.faqs || [] : [];
  state.kbSops = sopsResult.ok ? sopsResult.data.sops || [] : [];

  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const overview = state.kbOverview;
  const quality = overview.quality || {};

  const documentRows = (overview.documents || []).map((doc) => {
    const tags = (doc.tags||[]).map(t=>`<span class="status-badge ready" style="margin:2px">${esc(t)}</span>`).join('');
    const categories = (doc.categories||[]).map(c=>`<span class="status-badge active" style="margin:2px">${esc(c)}</span>`).join('');
    const kbStatus = doc.kb_status || 'pending';
    return `<tr><td><span class="table-title">${esc(doc.filename)}</span><div class="subtle" style="font-size:9px;margin-top:3px;max-width:320px">${esc(doc.summary||'')}</div></td><td>${categories||'—'}</td><td>${tags||'—'}</td><td>${statusBadge(kbStatus,kbStatus)}</td><td><button class="button" data-kb-regenerate="${esc(doc.id)}" ${doc.status!=='ready'?'disabled':''}>${icon('refresh',14)} Regenerate</button></td></tr>`;
  }).join('');

  const faqRows = state.kbFaqs.map((faq) => `<tr><td><span class="table-title">${esc(faq.question)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(faq.answer)}</div></td><td>${esc(faq.category||'—')}</td><td>${statusBadge(faq.status,faq.status)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap">${faq.status!=='approved'?`<button class="button button-primary" data-kb-faq-action="approved" data-kb-faq-id="${esc(faq.id)}">Approve</button>`:''}${faq.status!=='rejected'?`<button class="button button-danger" data-kb-faq-action="rejected" data-kb-faq-id="${esc(faq.id)}">Reject</button>`:''}${faq.status!=='suggested'?`<button class="button" data-kb-faq-action="suggested" data-kb-faq-id="${esc(faq.id)}">Reset</button>`:''}<button class="button" data-kb-faq-edit="${esc(faq.id)}">Edit</button></div></td></tr>`).join('');

  const sopRows = state.kbSops.map((sop) => `<tr><td><span class="table-title">${esc(sop.title)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${(sop.steps||[]).map((s,i)=>`${i+1}. ${esc(s)}`).join('<br>')}</div></td><td>${esc(sop.category||'—')}</td><td>${statusBadge(sop.status,sop.status)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap">${sop.status!=='approved'?`<button class="button button-primary" data-kb-sop-action="approved" data-kb-sop-id="${esc(sop.id)}">Approve</button>`:''}${sop.status!=='rejected'?`<button class="button button-danger" data-kb-sop-action="rejected" data-kb-sop-id="${esc(sop.id)}">Reject</button>`:''}${sop.status!=='suggested'?`<button class="button" data-kb-sop-action="suggested" data-kb-sop-id="${esc(sop.id)}">Reset</button>`:''}<button class="button" data-kb-sop-edit="${esc(sop.id)}">Edit</button></div></td></tr>`).join('');

  const missingTopics = (overview.missing_topics || []).map((item) => `<span class="status-badge error" style="margin:3px">${esc(item.topic)} (${item.document_count})</span>`).join('') || '<span class="subtle">Tidak ada topik penting yang terdeteksi hilang.</span>';

  setPage(`${pageHeader("Knowledge Builder","Dokumen otomatis dianalisis menjadi ringkasan, kategori, tag, FAQ, SOP, dan skor kualitas knowledge base.",`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="select" data-knowledge-builder-bot>${options}</select><label class="button button-primary">${icon('upload',14)} Import FAQ CSV<input type="file" data-faq-import accept=".csv" hidden></label></div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Overall quality",`${quality.overall_score||0}`,`${quality.documents_scored||0} dokumen dinilai`,"analytics")}${metricCard("Completeness",`${quality.completeness_score||0}`,"Kelengkapan informasi","knowledge")}${metricCard("Coverage",`${quality.coverage_score||0}`,"Cakupan topik penting","observability")}${metricCard("Redundancy",`${quality.redundancy_score||0}`,"100 = tidak ada duplikasi","learning")}</div>
  <div class="page-section-label">Documents</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Documents</h3><span class="subtle">Status pemrosesan Auto Knowledge Builder</span></div><span class="subtle mono" style="font-size:9px">${(overview.documents||[]).length} docs</span></div>${documentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Categories</th><th>Tags</th><th>KB Status</th><th></th></tr></thead><tbody>${documentRows}</tbody></table></div>`:emptyState("Belum ada dokumen","Upload dokumen di Knowledge Base untuk memulai Auto Knowledge Builder.")}</div>
  <div class="page-section-label">Generated FAQ & SOP</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Generated FAQ</h3><span class="subtle">${overview.faqs?.suggested||0} suggested · ${overview.faqs?.approved||0} approved · ${overview.faqs?.rejected||0} rejected</span></div>${overview.faqs?.suggested ? `<span class="approval-count-badge">${overview.faqs.suggested}</span>` : ''}</div>${faqRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>FAQ</th><th>Category</th><th>Status</th><th></th></tr></thead><tbody>${faqRows}</tbody></table></div>`:emptyState("Belum ada FAQ","FAQ hasil AI akan muncul di sini setelah dokumen diproses.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Generated SOP</h3><span class="subtle">${overview.sops?.suggested||0} suggested · ${overview.sops?.approved||0} approved · ${overview.sops?.rejected||0} rejected</span></div>${overview.sops?.suggested ? `<span class="approval-count-badge">${overview.sops.suggested}</span>` : ''}</div>${sopRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>SOP</th><th>Category</th><th>Status</th><th></th></tr></thead><tbody>${sopRows}</tbody></table></div>`:emptyState("Belum ada SOP","SOP hasil AI akan muncul di sini setelah dokumen diproses.")}</div>
  <div class="page-section-label">Gap analysis</div>
  <div class="card"><div class="card-head"><div><h3>${t('kb.missing_title')}</h3><span class="subtle">${t('kb.missing_desc')}</span></div></div><div class="card-body" style="padding:16px">${missingTopics}</div></div>`);
}

async function renderMultimedia() {
  loadingPage("Multimedia Studio", "Generate gambar, analisis gambar (Vision AI), dan buat dokumen PDF/DOCX/XLSX/PPTX.");
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  try {
    const result = await api.imagesHistory({ bot_id: state.selectedBotId || undefined, limit: 24 });
    state.multimedia.history = result.items || [];
  } catch (error) { state.multimedia.history = []; }

  const mm = state.multimedia;
  const imagePreview = mm.lastImage
    ? `<div class="card-body" style="display:grid;gap:8px"><img src="${esc(mm.lastImage.image_url)}" alt="Generated" style="max-width:100%;border-radius:8px;border:1px solid var(--border)"><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><span class="subtle">Provider: ${esc(mm.lastImage.provider)} · ${mm.lastImage.generation_time}s</span><a class="button" href="${esc(mm.lastImage.image_url)}" target="_blank" rel="noopener" download>${icon('upload',14)} Download</a></div></div>`
    : "";
  const analyzePreview = mm.lastAnalysis
    ? `<div class="card-body"><div style="white-space:pre-wrap;font-size:12px;line-height:1.6">${esc(mm.lastAnalysis.answer)}</div></div>`
    : "";
  const documentPreview = mm.lastDocument
    ? `<div class="card-body"><a class="button button-primary" href="${esc(mm.lastDocument.file_url)}" target="_blank" rel="noopener" download>${icon('upload',14)} Download ${esc(mm.lastDocument.format.toUpperCase())}: ${esc(mm.lastDocument.title)}</a></div>`
    : "";

  const historyItems = mm.history.map((item) => {
    if (item.kind === "analyze") {
      return `<div class="card" style="padding:10px"><span class="status-badge active">Analyze</span><p class="subtle" style="margin-top:6px;font-size:10px">${esc(item.prompt || '')}</p><span class="subtle mono" style="font-size:8px">${formatDate(item.created_at,{hour:'2-digit',minute:'2-digit'})}</span></div>`;
    }
    return `<div class="card" style="padding:10px"><img src="${esc(item.image_url)}" alt="" style="width:100%;border-radius:6px;aspect-ratio:1/1;object-fit:cover"><p class="subtle" style="margin-top:6px;font-size:10px;max-height:36px;overflow:hidden">${esc(item.prompt || '')}</p><span class="subtle mono" style="font-size:8px">${esc(item.provider)} · ${formatDate(item.created_at,{hour:'2-digit',minute:'2-digit'})}</span></div>`;
  }).join("");

  setPage(`${pageHeader("Multimedia Studio","Generate gambar, analisis gambar (Vision AI), dan buat dokumen PDF/DOCX/XLSX/PPTX.",`<select class="select" data-multimedia-bot><option value="">Semua agent</option>${options}</select>`)}
  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-head"><div><h3>${icon('multimedia',16)} Generate Image</h3><span class="subtle">OpenAI · Google Imagen · Replicate · Stability AI · Fal.ai</span></div></div>
      <form data-multimedia-image-form class="card-body" style="display:grid;gap:10px">
        <textarea class="input" name="prompt" rows="3" placeholder="Contoh: Buat logo restoran modern" required></textarea>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <input class="input" name="style" placeholder="Style (opsional, contoh: minimalist)" style="flex:1;min-width:160px">
          <select class="select" name="size"><option value="1024x1024">1024x1024</option><option value="1536x1024">1536x1024</option><option value="1024x1536">1024x1536</option></select>
          <select class="select" name="provider"><option value="">Default provider</option><option value="replicate">Replicate</option><option value="openai">OpenAI</option><option value="google_imagen">Google Imagen</option><option value="stability">Stability AI</option><option value="fal">Fal.ai</option></select>
        </div>
        <div style="display:flex;justify-content:flex-end"><button class="button button-primary" type="submit" ${mm.generating?'disabled':''}>${icon('send',14)} ${mm.generating?'Generating...':'Generate Image'}</button></div>
      </form>
      ${imagePreview}
    </div>
    <div class="card">
      <div class="card-head"><div><h3>${icon('chat',16)} Analyze Image (Vision AI)</h3><span class="subtle">Deskripsi, OCR, analisis UI/dashboard, atau baca invoice/dokumen</span></div></div>
      <form data-multimedia-analyze-form class="card-body" style="display:grid;gap:10px">
        <input class="input" type="file" name="file" accept="image/png,image/jpeg,image/webp,image/gif" required>
        <input class="input" name="question" placeholder="Pertanyaan (opsional, contoh: ada teks apa di gambar ini?)">
        <select class="select" name="mode"><option value="describe">Deskripsikan gambar</option><option value="ocr">Baca teks (OCR)</option><option value="ui_analysis">Analisis UI/Dashboard</option><option value="document">Baca invoice/dokumen</option></select>
        <div style="display:flex;justify-content:flex-end"><button class="button button-primary" type="submit" ${mm.analyzing?'disabled':''}>${icon('send',14)} ${mm.analyzing?'Analyzing...':'Analyze Image'}</button></div>
      </form>
      ${analyzePreview}
    </div>
  </div>
  <div class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h3>${icon('knowledge',16)} Generate Document</h3><span class="subtle">PDF · DOCX · XLSX · PPTX — AI menyusun outline otomatis dari permintaanmu</span></div></div>
    <form data-multimedia-document-form class="card-body" style="display:grid;gap:10px">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <select class="select" name="format"><option value="pdf">PDF</option><option value="docx">DOCX (Word)</option><option value="xlsx">XLSX (Excel)</option><option value="pptx">PPTX (PowerPoint)</option></select>
      </div>
      <textarea class="input" name="prompt" rows="3" placeholder="Contoh: Buat laporan penjualan bulan ini dalam bentuk tabel" required></textarea>
      <div style="display:flex;justify-content:flex-end"><button class="button button-primary" type="submit" ${mm.generatingDoc?'disabled':''}>${icon('send',14)} ${mm.generatingDoc?'Generating...':'Generate Document'}</button></div>
    </form>
    ${documentPreview}
  </div>
  <div class="card">
    <div class="card-head"><h3>Image History</h3><span class="subtle">Hasil generate &amp; analisis terbaru</span></div>
    ${historyItems ? `<div class="card-body" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px">${historyItems}</div>` : emptyState("Belum ada riwayat","Generate atau analisis gambar untuk mulai mengisi riwayat di sini.")}
  </div>`);
}

async function generateMultimediaImage(form) {
  const data = Object.fromEntries(new FormData(form));
  state.multimedia.generating = true;
  await renderMultimedia();
  try {
    const result = await api.imagesGenerate({
      prompt: data.prompt, style: data.style || "", size: data.size || "1024x1024",
      provider: data.provider || "", bot_id: state.selectedBotId || null,
    });
    state.multimedia.lastImage = result;
    toast("Gambar berhasil dibuat.", "success");
  } catch (error) { toast(error.message, "error"); }
  state.multimedia.generating = false;
  await renderMultimedia();
}

async function analyzeMultimediaImage(form) {
  const fd = new FormData(form);
  const file = fd.get("file");
  if (!file || !file.size) { toast("Pilih gambar dulu.", "error"); return; }
  state.multimedia.analyzing = true;
  await renderMultimedia();
  try {
    const result = await api.imagesAnalyze(file, {
      question: fd.get("question") || "", mode: fd.get("mode") || "describe", botId: state.selectedBotId || null,
    });
    state.multimedia.lastAnalysis = result;
    toast("Analisis gambar selesai.", "success");
  } catch (error) { toast(error.message, "error"); }
  state.multimedia.analyzing = false;
  await renderMultimedia();
}

async function generateMultimediaDocument(form) {
  const data = Object.fromEntries(new FormData(form));
  state.multimedia.generatingDoc = true;
  await renderMultimedia();
  try {
    const result = await api.documentsGenerate({
      format: data.format, prompt: data.prompt, bot_id: state.selectedBotId || null,
    });
    state.multimedia.lastDocument = result;
    toast("Dokumen berhasil dibuat.", "success");
  } catch (error) { toast(error.message, "error"); }
  state.multimedia.generatingDoc = false;
  await renderMultimedia();
}

async function runAgentTask(form) {
  const data = Object.fromEntries(new FormData(form));
  state.agentTaskRun.running = true;
  state.agentTaskRun.lastError = null;
  state.agentTaskRun.lastResult = null;
  await renderAgentCenter();
  try {
    if (COMPUTER_AGENT_TYPES.has(data.agent)) {
      // Computer Agent: kirim ke local agent via LLM planner
      const result = await api.computerAgentRunLocal(data.goal, 30);
      state.agentTaskRun.lastResult = { _type: "computer_agent", ...result };
      const okCount = result.ok_steps || 0;
      const total = result.total_steps || 0;
      toast(`Computer Agent selesai: ${okCount}/${total} langkah berhasil.`, okCount > 0 ? "success" : "error");
    } else {
      const fn = AGENT_RUN_TASK_FN[data.agent];
      if (!fn) { toast("Agent tidak dikenal", "error"); state.agentTaskRun.running = false; return; }
      const result = await api[fn](data.goal);
      state.agentTaskRun.lastResult = result;
      toast(result.status === "completed" ? "Task selesai." : "Task selesai, tapi verifikasi tidak lolos.", result.status === "completed" ? "success" : "error");
    }
  } catch (error) {
    state.agentTaskRun.lastError = error.message;
    state.agentTaskRun.lastResult = null;
    toast(error.message, "error");
  }
  state.agentTaskRun.running = false;
  await renderAgentCenter();
}

const WF_CATEGORY_META = {
  trigger: { label: "Trigger" }, condition: { label: "Condition" }, agent: { label: "Agent" },
  action: { label: "Action" }, notification: { label: "Notification" },
};

function workflowBuilderStyles() {
  if (document.getElementById('dynamic-workflow-style')) return;
  const style = document.createElement('style'); style.id = 'dynamic-workflow-style';
  style.textContent = `
.wf-editor{display:grid;grid-template-columns:200px 1fr 280px;gap:16px;align-items:start}
.wf-palette{padding:14px}
.wf-palette-group{margin-bottom:14px}
.wf-palette-title{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-3);margin-bottom:6px}
.wf-palette-item{display:block;width:100%;text-align:left;padding:7px 10px;margin-bottom:5px;background:var(--surface-2);border:1px solid var(--line);border-radius:8px;color:var(--text);font-size:11px;cursor:pointer}
.wf-palette-item:hover{border-color:var(--brand)}
.wf-canvas-wrap{padding:0;overflow:auto;max-height:560px}
.wf-canvas{position:relative;min-width:900px;min-height:520px;background-image:radial-gradient(circle,var(--line) 1px,transparent 1px);background-size:20px 20px}
.wf-canvas-hint{position:absolute;top:16px;left:16px;color:var(--text-3);font-size:11px}
.wf-edges{position:absolute;top:0;left:0;pointer-events:none;z-index:1}
.wf-edges .wf-edge-del{pointer-events:auto}
.wf-node{position:absolute;width:180px;min-height:64px;background:var(--surface-2);border:1px solid var(--line);border-radius:10px;z-index:2;box-shadow:var(--shadow)}
.wf-node.selected{border-color:var(--brand)}
.wf-node-head{display:flex;align-items:center;gap:6px;padding:8px 10px;cursor:grab;font-size:11px}
.wf-node-head strong{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wf-node-tag{font-size:8px;font-weight:700;letter-spacing:.06em;color:var(--text-3);background:var(--surface-3);border-radius:6px;padding:2px 5px}
.wf-node-del{background:none;border:0;color:var(--text-3);cursor:pointer;padding:0;display:flex}
.wf-node-del:hover{color:var(--red)}
.wf-dot{position:absolute;width:14px;height:14px;border-radius:50%;background:var(--surface-3);border:2px solid var(--brand);cursor:crosshair;z-index:3;font-size:8px;display:flex;align-items:center;justify-content:center;color:var(--text-2)}
.wf-dot-in{left:-7px;top:24px}
.wf-dot-out{right:-7px;top:24px}
.wf-dot-true{right:-7px;top:14px;border-color:var(--green)}
.wf-dot-false{right:-7px;top:46px;border-color:var(--red)}
.wf-inspector{padding:14px;min-height:200px}
.active-row{background:var(--surface-2)}
@media(max-width:1100px){.wf-editor{grid-template-columns:1fr}.wf-canvas-wrap{max-height:420px}}`;
  document.head.appendChild(style);
}

function workflowCategoryShort(cat) {
  return { trigger: "TRG", condition: "IF", agent: "AGT", action: "ACT", notification: "NTF" }[cat] || String(cat).slice(0, 3).toUpperCase();
}

function workflowNodeCard(node, catalog, selected) {
  const def = (catalog[node.category] || {})[node.type] || {};
  const label = def.label || node.type;
  const pos = node.position || { x: 40, y: 40 };
  const isCondition = node.category === "condition";
  const showInDot = node.category !== "trigger";
  const outDots = isCondition
    ? `<span class="wf-dot wf-dot-out wf-dot-true" data-wf-out="${esc(node.id)}" data-wf-handle="true" title="Jika true">T</span><span class="wf-dot wf-dot-out wf-dot-false" data-wf-out="${esc(node.id)}" data-wf-handle="false" title="Jika false">F</span>`
    : `<span class="wf-dot wf-dot-out" data-wf-out="${esc(node.id)}" data-wf-handle="" title="Output"></span>`;
  return `<div class="wf-node wf-node-${esc(node.category)} ${selected ? "selected" : ""}" data-wf-node="${esc(node.id)}" style="left:${pos.x}px;top:${pos.y}px">
    <div class="wf-node-head" data-wf-drag="${esc(node.id)}">
      <span class="wf-node-tag">${workflowCategoryShort(node.category)}</span>
      <strong>${esc(label)}</strong>
      <button class="wf-node-del" data-wf-delete-node="${esc(node.id)}" title="Hapus node">${icon("close", 12)}</button>
    </div>
    ${showInDot ? `<span class="wf-dot wf-dot-in" data-wf-in="${esc(node.id)}" title="Input"></span>` : ""}
    ${outDots}
  </div>`;
}

function workflowInspector(node, catalog) {
  const def = (catalog[node.category] || {})[node.type] || {};
  const fields = def.config_fields || [];
  const cfg = node.config || {};
  const fieldHtml = fields.map((field) => {
    const value = cfg[field.key] ?? field.default ?? "";
    if (field.type === "textarea") return `<label class="field full"><span>${esc(field.label)}</span><textarea data-wf-config-field="${esc(field.key)}">${esc(value)}</textarea></label>`;
    if (field.type === "select") return `<label class="field full"><span>${esc(field.label)}</span><select class="select" data-wf-config-field="${esc(field.key)}">${(field.options || []).map((opt) => `<option value="${esc(opt.value)}" ${String(value) === String(opt.value) ? "selected" : ""}>${esc(opt.label)}</option>`).join("")}</select></label>`;
    return `<label class="field full"><span>${esc(field.label)}</span><input data-wf-config-field="${esc(field.key)}" type="${field.type === "number" ? "number" : "text"}" value="${esc(value)}" ${field.type === "number" ? 'step="0.01"' : ""}></label>`;
  }).join("");
  return `<div class="card-head"><h3>${esc(def.label || node.type)}</h3><span class="subtle" style="font-size:9px">${esc(WF_CATEGORY_META[node.category]?.label || node.category)}</span></div>
  <form id="wf-node-config-form" data-wf-node-id="${esc(node.id)}" class="form-grid">${fieldHtml || '<p class="subtle">Node ini tidak memerlukan konfigurasi.</p>'}</form>`;
}

function workflowExecutionDetail(execData) {
  const ex = execData.execution; const steps = execData.steps || [];
  const rows = steps.map((s) => `<tr><td>${esc(s.node_type)}</td><td>${esc(s.category)}</td><td>${statusBadge(s.status, s.status)}</td><td>${s.attempt}</td><td>${s.duration_ms ?? "—"} ms</td><td>${s.error ? esc(s.error) : "—"}</td></tr>`).join("");
  return `<div style="margin-bottom:10px"><strong>Execution ${esc(String(ex.id).slice(0, 8))}</strong> ${statusBadge(ex.status, ex.status)} ${ex.error ? `<span class="subtle" style="color:var(--red)">${esc(ex.error)}</span>` : ""}</div>
  ${rows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Node</th><th>Category</th><th>Status</th><th>Attempt</th><th>Duration</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="subtle">Tidak ada step.</p>'}`;
}

function updateWorkflowEdgeLines() {
  const canvas = el("#wf-canvas"); const svg = el("#wf-edges-svg");
  if (!canvas || !svg || !state.wfWorkflow) return;
  const canvasRect = canvas.getBoundingClientRect();
  const width = Math.max(canvas.scrollWidth, canvas.clientWidth);
  const height = Math.max(canvas.scrollHeight, canvas.clientHeight);
  svg.setAttribute("width", width); svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const parts = [`<defs><marker id="wf-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="var(--brand)"/></marker></defs>`];
  for (const edge of (state.wfWorkflow.edges || [])) {
    const handle = edge.source_handle || "";
    const srcDot = canvas.querySelector(`[data-wf-out="${edge.source}"][data-wf-handle="${handle}"]`);
    const tgtDot = canvas.querySelector(`[data-wf-in="${edge.target}"]`);
    if (!srcDot || !tgtDot) continue;
    const s = srcDot.getBoundingClientRect(); const t = tgtDot.getBoundingClientRect();
    const x1 = s.left + s.width / 2 - canvasRect.left + canvas.scrollLeft;
    const y1 = s.top + s.height / 2 - canvasRect.top + canvas.scrollTop;
    const x2 = t.left + t.width / 2 - canvasRect.left + canvas.scrollLeft;
    const y2 = t.top + t.height / 2 - canvasRect.top + canvas.scrollTop;
    const mx = (x1 + x2) / 2;
    const color = handle === "false" ? "var(--red)" : handle === "true" ? "var(--green)" : "var(--brand)";
    parts.push(`<path d="M${x1},${y1} C ${mx},${y1} ${mx},${y2} ${x2},${y2}" stroke="${color}" stroke-width="2" fill="none" marker-end="url(#wf-arrow)"/>`);
    parts.push(`<g class="wf-edge-del" data-wf-delete-edge="${esc(edge.id)}"><circle cx="${mx}" cy="${(y1 + y2) / 2}" r="7" fill="var(--surface-2)" stroke="${color}"/><text x="${mx}" y="${(y1 + y2) / 2 + 3}" text-anchor="middle" font-size="10" fill="${color}">×</text></g>`);
  }
  svg.innerHTML = parts.join("");
}

async function renderWorkflowBuilder() {
  loadingPage("Workflow Builder", "Rancang automasi AI Agent ala n8n/Zapier/Make.");
  if (!state.selectedBotId) { setPage(pageHeader("Workflow Builder", "Rancang automasi AI Agent.") + emptyState("No agent available", "Create an agent before building workflows.")); return; }
  if (!state.wfNodeCatalog) {
    const catalogResult = await settle("wfNodeCatalog", api.wfNodeCatalog());
    if (catalogResult.ok) state.wfNodeCatalog = catalogResult.data.categories;
  }
  if (state.wfWorkflow) { await renderWorkflowEditor(); return; }

  const listResult = await settle("wfWorkflows", api.wfList(state.selectedBotId));
  if (!listResult.ok) { setPage(errorState(listResult.error.message)); return; }
  state.wfWorkflows = listResult.data.workflows || [];

  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id === state.selectedBotId ? "selected" : ""}>${esc(bot.name)}</option>`).join("");
  const rows = state.wfWorkflows.map((wf) => `<tr>
    <td><span class="table-title">${esc(wf.name)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(wf.description || "")}</div></td>
    <td>${esc(wf.trigger_type)}</td>
    <td>${statusBadge(wf.status, wf.status)}</td>
    <td>${relativeTime(wf.updated_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-wf-open="${esc(wf.id)}">Edit</button>
      ${wf.status === "published" ? `<button class="button" data-wf-unpublish="${esc(wf.id)}">Unpublish</button>` : `<button class="button button-primary" data-wf-publish="${esc(wf.id)}">Publish</button>`}
      <button class="button button-danger" data-wf-delete="${esc(wf.id)}">Delete</button>
    </div></td>
  </tr>`).join("");

  setPage(`${pageHeader("Workflow Builder", "Rancang automasi AI Agent — Trigger, Condition, Agent, Action, dan Notification ala n8n/Zapier/Make.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="select" data-workflow-builder-bot>${options}</select><button class="button button-primary" data-action="wf-new">${icon("plus", 14)} New workflow</button></div>`)}
  <div class="page-section-label">Workflow list — ${state.wfWorkflows.length} workflow</div>
  <div class="card"><div class="card-head"><div><h3>Workflows</h3><span class="subtle">Trigger → Condition → Agent → Action → Notification</span></div><span class="subtle mono" style="font-size:9px">${state.wfWorkflows.filter(w=>w.status==='published').length} published</span></div>${rows
      ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Workflow</th><th>Trigger</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
      : emptyState("Belum ada workflow", "Buat workflow pertama untuk automasi AI Agent — Trigger → Condition → Agent → Action → Notification.")}</div>`);
}

async function renderWorkflowEditor() {
  workflowBuilderStyles();
  const wf = state.wfWorkflow;
  const catalog = state.wfNodeCatalog || {};
  const categories = Object.keys(catalog);
  const palette = categories.map((cat) => `<div class="wf-palette-group"><div class="wf-palette-title">${esc(WF_CATEGORY_META[cat]?.label || cat)}</div>${Object.entries(catalog[cat] || {}).map(([type, def]) => `<button class="wf-palette-item" data-wf-add="${esc(cat)}:${esc(type)}" title="${esc(def.description || "")}">${esc(def.label || type)}</button>`).join("")}</div>`).join("");

  const nodes = wf.nodes || [];
  const nodeCards = nodes.map((node) => workflowNodeCard(node, catalog, node.id === state.wfSelectedNodeId)).join("");

  const selectedNode = nodes.find((n) => n.id === state.wfSelectedNodeId) || null;
  const inspector = selectedNode ? workflowInspector(selectedNode, catalog) : `<div class="card-body"><p class="subtle">Pilih node pada canvas untuk mengatur konfigurasinya. Hubungkan node dengan klik titik output (kanan), lalu klik titik input (kiri) node tujuan.</p></div>`;

  const triggerOptions = Object.entries(catalog.trigger || {}).map(([type, def]) => `<option value="${esc(type)}" ${wf.trigger_type === type ? "selected" : ""}>${esc(def.label || type)}</option>`).join("");

  const executions = (state.wfExecutions || []).map((ex) => `<tr class="${state.wfExecution?.execution?.id === ex.id ? "active-row" : ""}" data-wf-execution="${esc(ex.id)}" style="cursor:pointer">
    <td>${statusBadge(ex.status, ex.status)}</td><td>${esc(ex.trigger_type)}</td><td>${ex.duration_ms ?? "—"} ms</td><td>${relativeTime(ex.started_at)}</td>
  </tr>`).join("");

  const executionDetail = state.wfExecution ? workflowExecutionDetail(state.wfExecution) : '<p class="subtle">Klik salah satu eksekusi untuk melihat detail step.</p>';

  setPage(`${pageHeader("Workflow Builder", "Trigger → Condition → Agent → Action → Notification.",
    `<button class="button" data-action="wf-back">${icon("arrow", 14)} Kembali</button>
     <button class="button" data-action="wf-test">Test</button>
     ${wf.status === "published" ? `<button class="button" data-action="wf-unpublish">Unpublish</button>` : `<button class="button" data-action="wf-publish">Publish</button>`}
     <button class="button button-primary" data-action="wf-save">Save</button>`)}
  <div class="card" style="margin-bottom:16px"><div class="card-body" style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
    <label class="field" style="min-width:220px"><span>Nama workflow</span><input data-wf-field="name" value="${esc(wf.name)}"></label>
    <label class="field" style="min-width:220px"><span>Trigger</span><select class="select" data-wf-field="trigger_type">${triggerOptions}</select></label>
    <label class="field" style="flex:1;min-width:220px"><span>Deskripsi</span><input data-wf-field="description" value="${esc(wf.description || "")}"></label>
    <div>${statusBadge(wf.status, wf.status)}</div>
  </div></div>
  <div class="wf-editor">
    <div class="card wf-palette">${palette}</div>
    <div class="card wf-canvas-wrap"><div class="wf-canvas" id="wf-canvas">
      <svg class="wf-edges" id="wf-edges-svg"></svg>
      ${nodeCards || '<div class="wf-canvas-hint">Klik node pada palette kiri untuk menambahkannya ke canvas.</div>'}
    </div></div>
    <div class="card wf-inspector">${inspector}</div>
  </div>
  <div class="card" style="margin-top:16px"><div class="card-head"><h3>Execution history</h3></div>
    ${executions ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Status</th><th>Trigger</th><th>Duration</th><th>Started</th></tr></thead><tbody>${executions}</tbody></table></div>` : emptyState("Belum ada eksekusi", "Klik Test atau publish workflow ini agar eksekusi tercatat di sini.")}
    <div class="card-body" id="wf-execution-detail">${executionDetail}</div>
  </div>`);

  requestAnimationFrame(updateWorkflowEdgeLines);
}

async function openWorkflow(id) {
  try {
    state.wfWorkflow = await api.wfGet(id);
    state.wfSelectedNodeId = null; state.wfLinkFrom = null; state.wfExecution = null;
    const execResult = await settle("wfExecutions", api.wfExecutions(id));
    state.wfExecutions = execResult.ok ? execResult.data.executions || [] : [];
    await renderWorkflowBuilder();
  } catch (error) { toast(error.message, "error"); }
}

function backToWorkflowList() {
  state.wfWorkflow = null; state.wfSelectedNodeId = null; state.wfLinkFrom = null; state.wfExecution = null;
  renderWorkflowBuilder();
}

async function createWorkflowPrompt() {
  const name = prompt("Nama workflow:", "Workflow baru"); if (!name) return;
  try {
    const wf = await api.wfCreate(state.selectedBotId, { name, trigger_type: "manual_trigger", nodes: [], edges: [] });
    toast("Workflow dibuat.", "success");
    await openWorkflow(wf.id);
  } catch (error) { toast(error.message, "error"); }
}

async function saveWorkflow() {
  const wf = state.wfWorkflow; if (!wf) return;
  try {
    state.wfWorkflow = await api.wfUpdate(wf.id, { name: wf.name, description: wf.description, trigger_type: wf.trigger_type, nodes: wf.nodes, edges: wf.edges });
    toast("Workflow disimpan.", "success");
    await renderWorkflowBuilder();
  } catch (error) { toast(error.message, "error"); }
}

async function publishWorkflow() {
  const wf = state.wfWorkflow; if (!wf) return;
  try { state.wfWorkflow = await api.wfPublish(wf.id); toast("Workflow dipublikasikan.", "success"); await renderWorkflowBuilder(); }
  catch (error) { toast(error.message, "error"); }
}

async function unpublishWorkflow() {
  const wf = state.wfWorkflow; if (!wf) return;
  try { state.wfWorkflow = await api.wfUnpublish(wf.id); toast("Workflow diset ke draft.", "success"); await renderWorkflowBuilder(); }
  catch (error) { toast(error.message, "error"); }
}

async function deleteWorkflowConfirm(id) {
  if (!confirm("Hapus workflow ini?")) return;
  try {
    await api.wfDelete(id); toast("Workflow dihapus.", "success");
    if (state.wfWorkflow?.id === id) state.wfWorkflow = null;
    await renderWorkflowBuilder();
  } catch (error) { toast(error.message, "error"); }
}

async function testWorkflowRun() {
  const wf = state.wfWorkflow; if (!wf) return;
  const payloadText = prompt("Payload test (JSON, opsional):", "{}");
  if (payloadText === null) return;
  let payload = {};
  try { payload = payloadText.trim() ? JSON.parse(payloadText) : {}; } catch { return toast("Payload harus berupa JSON valid.", "error"); }
  try {
    const result = await api.wfTest(wf.id, payload);
    toast(`Test selesai: ${result.execution.status}`, result.execution.status === "success" ? "success" : "error");
    state.wfExecution = result;
    const execResult = await settle("wfExecutions", api.wfExecutions(wf.id));
    state.wfExecutions = execResult.ok ? execResult.data.executions || [] : [];
    await renderWorkflowBuilder();
  } catch (error) { toast(error.message, "error"); }
}

async function openWorkflowExecution(executionId) {
  try { state.wfExecution = await api.wfExecution(executionId); await renderWorkflowBuilder(); }
  catch (error) { toast(error.message, "error"); }
}

function addWorkflowNode(category, type) {
  const wf = state.wfWorkflow; if (!wf) return;
  wf.nodes = wf.nodes || [];
  const index = wf.nodes.length;
  const node = { id: `n_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, category, type, config: {}, position: { x: 40 + (index % 4) * 220, y: 40 + Math.floor(index / 4) * 150 } };
  wf.nodes.push(node);
  state.wfSelectedNodeId = node.id;
  renderWorkflowBuilder();
}

function deleteWorkflowNode(nodeId) {
  const wf = state.wfWorkflow; if (!wf) return;
  wf.nodes = (wf.nodes || []).filter((n) => n.id !== nodeId);
  wf.edges = (wf.edges || []).filter((e) => e.source !== nodeId && e.target !== nodeId);
  if (state.wfSelectedNodeId === nodeId) state.wfSelectedNodeId = null;
  renderWorkflowBuilder();
}

function selectWorkflowNode(nodeId) {
  state.wfSelectedNodeId = nodeId;
  renderWorkflowBuilder();
}

function startWorkflowLink(nodeId, handle) {
  state.wfLinkFrom = { nodeId, handle: handle || "" };
  toast("Klik titik input (kiri) node tujuan untuk menghubungkan.");
}

function completeWorkflowLink(targetNodeId) {
  const from = state.wfLinkFrom; state.wfLinkFrom = null;
  if (!from || from.nodeId === targetNodeId) return;
  const wf = state.wfWorkflow; if (!wf) return;
  wf.edges = (wf.edges || []).filter((e) => !(e.source === from.nodeId && (e.source_handle || "") === from.handle));
  wf.edges.push({ id: `e_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, source: from.nodeId, target: targetNodeId, source_handle: from.handle || undefined });
  renderWorkflowBuilder();
}

function deleteWorkflowEdge(edgeId) {
  const wf = state.wfWorkflow; if (!wf) return;
  wf.edges = (wf.edges || []).filter((e) => e.id !== edgeId);
  updateWorkflowEdgeLines();
}

function formatIDR(amount) { return `Rp ${formatNumber(Math.round(Number(amount || 0)))}`; }

async function renderFinance() {
  loadingPage("Finance Center", "Invoice, expense, dan laporan keuangan bisnis Anda — dikelola oleh AI Workforce.");
  let dashboard, invoices, expenses;
  try {
    [dashboard, invoices, expenses] = await Promise.all([
      api.financeDashboard(), api.financeInvoices({ limit: 50 }), api.financeExpenses({ limit: 50 }),
    ]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.financeDashboard = dashboard; state.financeInvoices = invoices.invoices || []; state.financeExpenses = expenses.expenses || [];

  const invoiceRows = state.financeInvoices.map((inv) => `<tr>
    <td><span class="table-title">${esc(inv.invoice_number)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(inv.customer_name)}</div></td>
    <td>${formatIDR(inv.amount_idr)}</td>
    <td>${statusBadge(inv.status, inv.status)}</td>
    <td>${relativeTime(inv.due_date)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      ${inv.status === "draft" ? `<button class="button" data-finance-invoice-status="${esc(inv.id)}:sent">Kirim</button>` : ""}
      ${inv.status === "sent" || inv.status === "overdue" ? `<button class="button button-primary" data-finance-invoice-status="${esc(inv.id)}:paid">Tandai lunas</button>` : ""}
      ${inv.status !== "paid" && inv.status !== "cancelled" ? `<button class="button button-danger" data-finance-invoice-status="${esc(inv.id)}:cancelled">Batalkan</button>` : ""}
    </div></td>
  </tr>`).join("");

  const expenseRows = state.financeExpenses.map((exp) => `<tr>
    <td><span class="table-title">${esc(exp.description)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(exp.category)}</div></td>
    <td>${formatIDR(exp.amount_idr)}</td>
    <td>${statusBadge(exp.status, exp.status)}</td>
    <td>${relativeTime(exp.expense_date)}</td>
    <td>${exp.status === "recorded" ? `<div style="display:flex;gap:6px"><button class="button button-primary" data-finance-expense-approve="${esc(exp.id)}:1">Approve</button><button class="button button-danger" data-finance-expense-approve="${esc(exp.id)}:0">Reject</button></div>` : ""}</td>
  </tr>`).join("");

  setPage(`${pageHeader("Finance Center", "Generate invoice, catat expense, dan pantau revenue/profit/cashflow bisnis Anda.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="finance-ask-ai">${icon("chat", 14)} Tanya AI</button>
      <button class="button" data-action="finance-new-expense">+ Expense</button>
      <button class="button button-primary" data-action="finance-new-invoice">${icon("plus", 14)} Buat Invoice</button>
    </div>`)}
  <div class="finance-strip">
    <div class="finance-strip-item d-finance"><span>Revenue (30d)</span><strong style="color:var(--domain-finance)">${formatIDR(dashboard.revenue_30d_idr)}</strong></div>
    <div class="finance-strip-item"><span>Profit (30d)</span><strong style="color:${dashboard.profit_30d_idr >= 0 ? 'var(--green)' : 'var(--red)'}">${formatIDR(dashboard.profit_30d_idr)}</strong></div>
    <div class="finance-strip-item"><span>MRR</span><strong>${formatIDR(dashboard.mrr_idr)}</strong></div>
  </div>
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("ARR", formatIDR(dashboard.arr_idr), `Churn ${dashboard.churn_pct || 0}%`, "finance")}
    ${metricCard("Invoice Pending", formatNumber(dashboard.pending_invoices_count), formatIDR(dashboard.pending_invoices_amount_idr), "finance", dashboard.overdue_invoices_count ? "trend-down" : "trend-up")}
    ${metricCard("Overdue", formatNumber(dashboard.overdue_invoices_count), "Perlu ditagih ulang", "finance", dashboard.overdue_invoices_count ? "trend-down" : "trend-up")}
    ${metricCard("Total Expense (30d)", formatIDR(dashboard.expense_30d_idr || 0), "Pengeluaran tercatat", "finance")}
  </div>
  <div class="page-section-label">Invoice management</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Invoices</h3><span class="subtle">Buat, kirim, dan tandai lunas dari sini</span></div><span class="status-badge ${dashboard.overdue_invoices_count ? 'error' : 'active'}">${formatNumber(dashboard.pending_invoices_count)} pending</span></div>${invoiceRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Invoice</th><th>Jumlah</th><th>Status</th><th>Jatuh tempo</th><th style="width:180px"></th></tr></thead><tbody>${invoiceRows}</tbody></table></div>` : emptyState("Belum ada invoice", "Buat invoice pertama untuk pelanggan Anda.")}</div>
  <div class="page-section-label">Expense tracking</div>
  <div class="card"><div class="card-head"><div><h3>Expenses</h3><span class="subtle">Semua pengeluaran tercatat dan masuk ke laporan profit</span></div></div>${expenseRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Expense</th><th>Jumlah</th><th>Status</th><th>Tanggal</th><th style="width:160px"></th></tr></thead><tbody>${expenseRows}</tbody></table></div>` : emptyState("Belum ada expense", "Catat pengeluaran bisnis untuk laporan profit yang akurat.")}</div>`);
}

async function createInvoicePrompt() {
  const customer_name = prompt("Nama pelanggan:"); if (!customer_name) return;
  const amount_raw = prompt("Jumlah invoice (Rp, angka saja):"); if (!amount_raw) return;
  const amount_idr = parseInt(amount_raw.replace(/[^0-9]/g, ""), 10);
  if (!amount_idr || amount_idr <= 0) { toast("Jumlah tidak valid", "error"); return; }
  try {
    await api.financeCreateInvoice({ customer_name, amount_idr });
    toast("Invoice dibuat.", "success");
    await renderFinance();
  } catch (error) { toast(error.message, "error"); }
}

async function createExpensePrompt() {
  const description = prompt("Deskripsi expense:"); if (!description) return;
  const category = prompt("Kategori (operasional/gaji/marketing/sewa/lainnya):", "lainnya") || "lainnya";
  const amount_raw = prompt("Jumlah (Rp, angka saja):"); if (!amount_raw) return;
  const amount_idr = parseInt(amount_raw.replace(/[^0-9]/g, ""), 10);
  if (!amount_idr || amount_idr <= 0) { toast("Jumlah tidak valid", "error"); return; }
  try {
    await api.financeCreateExpense({ description, category, amount_idr });
    toast("Expense dicatat.", "success");
    await renderFinance();
  } catch (error) { toast(error.message, "error"); }
}

async function askFinanceAiPrompt() {
  const text = prompt("Tulis permintaan finance (contoh: 'Buatkan invoice untuk Budi Rp 500000'):"); if (!text) return;
  try {
    const result = await api.financeParse(text);
    toast(`AI Finance: ${result?.intent?.action || "unknown"} berhasil diproses.`, "success");
    await renderFinance();
  } catch (error) { toast(error.message, "error"); }
}

async function renderMarketing() {
  loadingPage("Marketing Center", "Generate konten IG/TikTok/Facebook/Blog/Email/WhatsApp, kelola content calendar, dan catat engagement — dikelola oleh AI Workforce.");
  let dashboard, content, campaigns;
  try {
    [dashboard, content, campaigns] = await Promise.all([
      api.marketingDashboard(), api.marketingContent({ limit: 50 }), api.marketingCampaigns(50),
    ]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.marketingDashboard = dashboard; state.marketingContent = content.content || []; state.marketingCampaigns = campaigns.campaigns || [];

  const PLATFORM_CLS = { instagram:'instagram', tiktok:'tiktok', facebook:'facebook', blog:'blog', email:'email', whatsapp:'whatsapp' };
  const platformBadge = (p) => `<span class="platform-dot ${PLATFORM_CLS[p]||''}">${esc(p)}</span>`;
  const contentRows = state.marketingContent.map((item) => `<tr>
    <td><span class="table-title">${esc(item.title || item.platform)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc((item.body || "").slice(0, 80))}${(item.body || "").length > 80 ? "…" : ""}</div></td>
    <td>${platformBadge(item.platform)}</td>
    <td>${statusBadge(item.status, item.status)}</td>
    <td class="subtle">${item.scheduled_at ? relativeTime(item.scheduled_at) : "—"}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      ${item.status === "draft" ? `<button class="button" data-marketing-content-approve="${esc(item.id)}">Approve</button>` : ""}
      ${item.status === "ready_to_publish" || item.status === "scheduled" ? `<button class="button button-primary" data-marketing-content-publish="${esc(item.id)}">Tandai published</button>` : ""}
      ${item.status !== "published" && item.status !== "cancelled" ? `<button class="button button-danger" data-marketing-content-cancel="${esc(item.id)}">Batalkan</button>` : ""}
    </div></td>
  </tr>`).join("");

  const campaignRows = state.marketingCampaigns.map((c) => `<tr>
    <td><span class="table-title">${esc(c.name)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(c.goal || "")}</div></td>
    <td>${statusBadge(c.status, c.status)}</td>
    <td>${c.start_date ? relativeTime(c.start_date) : "—"}</td>
  </tr>`).join("");

  const totalEngagement = Object.values(dashboard.engagement_30d || {}).reduce((a, b) => a + b, 0);
  setPage(`${pageHeader("Marketing Center", "AI generate konten per platform dan jadwalkan di content calendar — publikasi tetap manual, engagement dicatat dari platform masing-masing.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="marketing-new-campaign">${icon("plus",14)} Campaign Baru</button>
      <button class="button button-primary" data-action="marketing-generate-content">${icon("chat", 14)} Generate Konten</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Campaign Aktif", formatNumber(dashboard.active_campaigns), "Sedang berjalan", "marketing")}
    ${metricCard("Draft", formatNumber(dashboard.content_draft), `${formatNumber(dashboard.content_due_now)} siap tayang`, "marketing", dashboard.content_due_now ? "trend-down" : "trend-up")}
    ${metricCard("Published", formatNumber(dashboard.content_published), `${formatNumber(dashboard.content_ready_to_publish)} siap publish`, "marketing", "trend-up")}
    ${metricCard("Engagement (30d)", formatNumber(totalEngagement), "Likes · comments · shares", "marketing", "trend-up")}
  </div>
  <div class="page-section-label">Content calendar</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Content Calendar</h3><span class="subtle">Approve draft lalu tandai published setelah posting manual</span></div><span class="status-badge ${dashboard.content_due_now ? 'pending' : 'active'}">${formatNumber(state.marketingContent.length)} items</span></div>${contentRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Konten</th><th>Platform</th><th>Status</th><th>Jadwal</th><th></th></tr></thead><tbody>${contentRows}</tbody></table></div>` : emptyState("Belum ada konten", "Generate konten pertama untuk campaign Anda.")}</div>
  <div class="page-section-label">Campaigns</div>
  <div class="card"><div class="card-head"><h3>Campaigns</h3></div>${campaignRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Campaign</th><th>Status</th><th>Mulai</th></tr></thead><tbody>${campaignRows}</tbody></table></div>` : emptyState("Belum ada campaign", "Buat campaign untuk mengelompokkan konten marketing Anda.")}</div>`);
}

async function createMarketingCampaignPrompt() {
  const name = prompt("Nama campaign:"); if (!name) return;
  const goal = prompt("Goal campaign (opsional):") || null;
  try {
    await api.marketingCreateCampaign({ name, goal });
    toast("Campaign dibuat.", "success");
    await renderMarketing();
  } catch (error) { toast(error.message, "error"); }
}

async function generateMarketingContentPrompt() {
  const platform = prompt("Platform (instagram/tiktok/facebook/blog/email/whatsapp):", "instagram"); if (!platform) return;
  const brief = prompt("Brief konten (contoh: 'Promo akhir bulan diskon 20% untuk semua produk'):"); if (!brief) return;
  try {
    await api.marketingGenerateContent({ platform: platform.trim().toLowerCase(), brief });
    toast("Konten berhasil digenerate.", "success");
    await renderMarketing();
  } catch (error) { toast(error.message, "error"); }
}

async function renderHR() {
  loadingPage("HR Center", "CV screening, candidate scoring, interview questions, evaluasi karyawan, dan rekomendasi training — dikelola oleh AI Workforce.");
  let dashboard, candidates, employees;
  try {
    [dashboard, candidates, employees] = await Promise.all([
      api.hrDashboard(), api.hrCandidates({ limit: 50 }), api.hrEmployees({ limit: 50 }),
    ]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.hrDashboard = dashboard; state.hrCandidates = candidates.candidates || []; state.hrEmployees = employees.employees || [];

  const candidateRows = state.hrCandidates.map((c) => {
    const score = c.score != null ? Number(c.score) : null;
    const scorePct = score !== null ? Math.min(100, score) : 0;
    const scoreHtml = score !== null
      ? `<div class="candidate-score"><div class="score-bar"><i style="width:${scorePct}%"></i></div><span class="score-num">${score}</span></div>`
      : `<span class="subtle">—</span>`;
    return `<tr>
      <td><span class="table-title">${esc(c.name)}</span><div class="subtle" style="font-size:9px;margin-top:2px">${esc(c.position_applied || "")}</div></td>
      <td style="min-width:120px">${scoreHtml}</td>
      <td>${statusBadge(c.status, c.status)}</td>
      <td><div style="display:flex;gap:6px;flex-wrap:wrap"><button class="button" data-hr-candidate-score="${esc(c.id)}">Score AI</button><button class="button button-danger" data-hr-candidate-delete="${esc(c.id)}">Hapus</button></div></td>
    </tr>`;
  }).join("");

  const employeeRows = state.hrEmployees.map((e) => `<tr>
    <td><span class="table-title">${esc(e.full_name)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(e.position || "")}${e.department ? " · " + esc(e.department) : ""}</div></td>
    <td>${statusBadge(e.status, e.status)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-hr-employee-evaluate="${esc(e.id)}">Generate Evaluasi (AI)</button>
    </div></td>
  </tr>`).join("");

  setPage(`${pageHeader("HR Center", "AI membantu screening CV, scoring kandidat, draft evaluasi, dan rekomendasi training — keputusan akhir tetap di tangan tim Anda.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="hr-new-candidate">${icon("plus",14)} Kandidat Baru</button>
      <button class="button button-primary" data-action="hr-new-employee">${icon("plus", 14)} Karyawan Baru</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Kandidat Baru", formatNumber(dashboard.candidates_by_status?.new || 0), "Belum diproses AI", "hr")}
    ${metricCard("Kandidat Screened", formatNumber(dashboard.candidates_by_status?.screened || 0), "Sudah di-score AI", "hr", "trend-up")}
    ${metricCard("Karyawan Aktif", formatNumber(dashboard.employees_by_status?.active || 0), "Terdaftar di sistem", "hr", "trend-up")}
    ${metricCard("Avg Evaluasi (90d)", dashboard.avg_evaluation_score_90d != null ? dashboard.avg_evaluation_score_90d : "—", `${formatNumber(dashboard.pending_training_recommendations)} training pending`, "hr")}
  </div>
  <div class="page-section-label">Talent pipeline</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Kandidat</h3><span class="subtle">AI scoring membantu prioritas — keputusan hire tetap manusia</span></div><span class="status-badge default">${formatNumber(state.hrCandidates.length)} kandidat</span></div>${candidateRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Kandidat</th><th>Skor AI</th><th>Status</th><th></th></tr></thead><tbody>${candidateRows}</tbody></table></div>` : emptyState("Belum ada kandidat", "Tambahkan kandidat untuk mulai proses screening.")}</div>
  <div class="page-section-label">Employee performance</div>
  <div class="card"><div class="card-head"><div><h3>Karyawan</h3><span class="subtle">Generate evaluasi AI untuk setiap karyawan</span></div><span class="status-badge active">${formatNumber(state.hrEmployees.length)} karyawan</span></div>${employeeRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Karyawan</th><th>Status</th><th></th></tr></thead><tbody>${employeeRows}</tbody></table></div>` : emptyState("Belum ada karyawan", "Tambahkan karyawan untuk mulai tracking performa.")}</div>`);
}

async function createHRCandidatePrompt() {
  const name = prompt("Nama kandidat:"); if (!name) return;
  const position_applied = prompt("Posisi yang dilamar:") || null;
  try {
    await api.hrCreateCandidate({ name, position_applied });
    toast("Kandidat ditambahkan.", "success");
    await renderHR();
  } catch (error) { toast(error.message, "error"); }
}

async function createHREmployeePrompt() {
  const full_name = prompt("Nama karyawan:"); if (!full_name) return;
  const position = prompt("Posisi/jabatan:") || null;
  try {
    await api.hrCreateEmployee({ full_name, position });
    toast("Karyawan ditambahkan.", "success");
    await renderHR();
  } catch (error) { toast(error.message, "error"); }
}

async function scoreHRCandidatePrompt(candidateId) {
  const position = prompt("Posisi yang dilamar (untuk scoring AI):"); if (!position) return;
  try {
    await api.hrScoreCandidate(candidateId, { position });
    toast("Kandidat berhasil di-score AI.", "success");
    await renderHR();
  } catch (error) { toast(error.message, "error"); }
}

async function evaluateHREmployeePrompt(employeeId) {
  const role = prompt("Role/jabatan karyawan saat ini:"); if (!role) return;
  const notes = prompt("Catatan manajer tentang performa karyawan ini:"); if (!notes) return;
  try {
    await api.hrGenerateEvaluation(employeeId, { role, notes });
    toast("Draft evaluasi berhasil digenerate AI (belum final).", "success");
    await renderHR();
  } catch (error) { toast(error.message, "error"); }
}

async function renderOperations() {
  loadingPage("Operations Center", "Tenant health, workflow & SLA monitoring, weekly/monthly report — dikelola oleh AI Workforce.");
  let dashboard, alerts, reports;
  try {
    [dashboard, alerts, reports] = await Promise.all([
      api.opsDashboard(), api.opsAlerts({ status: "open", limit: 50 }), api.opsReports({ limit: 10 }),
    ]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.opsDashboard = dashboard; state.opsAlerts = alerts.alerts || []; state.opsReports = reports.reports || [];

  const health = dashboard.health || {};
  const healthTrend = health.label === "healthy" ? "trend-up" : (health.label === "warning" ? "default" : "trend-down");

  const alertRows = state.opsAlerts.map((a) => `<tr>
    <td>${statusBadge(a.severity, a.severity)}</td>
    <td><span class="table-title">${esc(a.category.replace(/_/g, " "))}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(a.message)}</div></td>
    <td>${relativeTime(a.created_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-ops-alert-status="${esc(a.id)}:acknowledged">Acknowledge</button>
      <button class="button button-primary" data-ops-alert-status="${esc(a.id)}:resolved">Resolve</button>
    </div></td>
  </tr>`).join("");

  const reportRows = state.opsReports.map((r) => `<tr>
    <td>${statusBadge("default", r.report_type)}</td>
    <td>${esc((r.summary || "").slice(0, 100))}${(r.summary || "").length > 100 ? "…" : ""}</td>
    <td>${relativeTime(r.created_at)}</td>
  </tr>`).join("");

  const opsHealthLabel = health.label || "watch";
  const opsHealthCls = { healthy:"healthy", warning:"warning", critical:"critical" }[opsHealthLabel] || "watch";
  setPage(`${pageHeader("Operations Center", "AI memonitor health tenant, workflow, dan SLA, lalu menyusun laporan — alert butuh tindak lanjut manusia.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="ops-scan">${icon("refresh", 14)} Run Scan</button>
      <button class="button" data-action="ops-generate-weekly">Weekly Report</button>
      <button class="button button-primary" data-action="ops-generate-monthly">Monthly Report</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card metric-card d-operations domain-card"><div class="metric-top"><span class="metric-label">Health Score</span></div><div class="metric-value">${health.score ?? "—"}</div><div class="metric-meta"><span class="health-chip ${opsHealthCls}"><i></i>${esc(opsHealthLabel)}</span></div></div>
    ${metricCard("Workflow Success", `${dashboard.workflow_health?.success_rate_pct ?? "—"}%`, `${formatNumber(dashboard.workflow_health?.total_executions||0)} eksekusi`, "operations", dashboard.workflow_health?.success_rate_pct >= 90 ? "trend-up" : "")}
    ${metricCard("SLA Breach Rate", `${dashboard.sla_health?.breach_rate_pct ?? "—"}%`, `${formatNumber(dashboard.sla_health?.total_handoffs||0)} handoff`, "operations", dashboard.sla_health?.breach_rate_pct > 10 ? "trend-down" : "trend-up")}
    ${metricCard("Open Alerts", formatNumber(state.opsAlerts.length), `${formatNumber(dashboard.open_alerts_by_severity?.critical||0)} critical`, "operations", state.opsAlerts.length ? "trend-down" : "trend-up")}
  </div>
  <div class="page-section-label">Alert management</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Alerts</h3><span class="subtle">Acknowledge untuk tandai diketahui, Resolve jika sudah diatasi</span></div><span class="status-badge ${state.opsAlerts.length ? 'error' : 'active'}">${formatNumber(state.opsAlerts.length)} terbuka</span></div>${alertRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Alert</th><th>Waktu</th><th style="width:180px"></th></tr></thead><tbody>${alertRows}</tbody></table></div>` : emptyState("Tidak ada alert terbuka", "Jalankan scan untuk mendeteksi masalah operasional.")}</div>
  <div class="page-section-label">Reports</div>
  <div class="card"><div class="card-head"><h3>Laporan operasional</h3></div>${reportRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tipe</th><th>Ringkasan</th><th>Dibuat</th></tr></thead><tbody>${reportRows}</tbody></table></div>` : emptyState("Belum ada laporan", "Generate laporan weekly/monthly pertama Anda.")}</div>`);
}

const EXECUTIVE_TREND_PERIODS = [["1","Today"],["7","7 Days"],["30","30 Days"],["90","90 Days"],["365","1 Year"]];

async function renderExecutive() {
  loadingPage("Executive Center", "AI CEO Assistant — company health score dan executive brief lintas Finance/Marketing/HR/Operations/Security/Sales.");
  const trendDays = state.executiveTrendDays || 30;
  let dashboard, reports, trends;
  try {
    [dashboard, reports, trends] = await Promise.all([api.executiveDashboard(), api.executiveReports({ limit: 10 }), api.executiveTrends(trendDays)]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.executiveDashboard = dashboard; state.executiveReports = reports.reports || []; state.executiveTrends = trends || {};

  const health = dashboard.health || {};
  const byDomain = health.by_domain || {};
  const healthTrend = health.label === "healthy" ? "trend-up" : (health.label === "warning" ? "default" : "trend-down");
  const sales = dashboard.synthesis?.sales || {};
  const periodTabs = EXECUTIVE_TREND_PERIODS.map(([value, label]) => `<button class="button ${trendDays===Number(value)?'button-primary':''}" data-exec-trend-period="${value}">${label}</button>`).join("");

  const domainDefs = [
    { key:"finance",    label:"Finance",    color:"var(--domain-finance)"    },
    { key:"marketing",  label:"Marketing",  color:"var(--domain-marketing)"  },
    { key:"hr",         label:"HR",         color:"var(--domain-hr)"         },
    { key:"operations", label:"Operations", color:"var(--domain-operations)" },
    { key:"security",   label:"Security",   color:"var(--domain-security)"   },
    { key:"sales",      label:"Sales",      color:"var(--domain-sales)"      },
  ];
  const domainScoreBars = domainDefs.map(({ key, label, color }) => {
    const score = byDomain[key] ?? null;
    const pct = score !== null ? Math.min(100, Number(score)) : 0;
    return `<div class="domain-score-row"><span>${esc(label)}</span><div class="domain-score-progress"><i style="width:${pct}%;background:${color}"></i></div><strong>${score ?? '—'}</strong></div>`;
  }).join("");

  let briefHtml = "";
  if (state.executiveReports.length) {
    try {
      const full = await api.executiveReport(state.executiveReports[0].id);
      const brief = full.data?.brief || {};
      const listBlock = (title, items) => (items || []).length
        ? `<div style="margin-bottom:12px"><div class="subtle" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">${esc(title)}</div><ul style="margin:0;padding-left:18px">${items.map((item) => `<li style="font-size:12px;margin-bottom:4px">${esc(item)}</li>`).join("")}</ul></div>`
        : "";
      briefHtml = `<div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Executive Brief Terbaru</h3><span class="subtle mono" style="font-size:9px">${esc(full.report_type || "")}</span></div>
        ${brief.executive_summary ? `<p style="font-size:13px;margin-bottom:14px">${esc(brief.executive_summary)}</p>` : ""}
        ${listBlock("Growth Recommendations", brief.growth_recommendations)}
        ${listBlock("Cost Optimization", brief.cost_optimization)}
        ${listBlock("Revenue Opportunities", brief.revenue_opportunities)}
        ${listBlock("Strategic Insights", brief.strategic_insights)}
      </div>`;
    } catch { /* tetap tampilkan dashboard meski brief detail gagal dimuat */ }
  }

  const reportRows = state.executiveReports.map((r) => `<tr>
    <td>${statusBadge('default', r.report_type)}</td>
    <td>${esc((r.summary || '').slice(0,100))}${(r.summary||'').length>100?'…':''}</td>
    <td>${relativeTime(r.created_at)}</td>
  </tr>`).join("");

  const analysisHtml = renderBusinessAnalysis(state.businessAnalysis);

  const chartCard = (title, canvasId) => `<div class="card"><div class="card-head"><h3 style="font-size:13px">${esc(title)}</h3></div><div class="card-body"><div style="height:220px"><canvas id="${canvasId}"></canvas></div></div></div>`;

  const overallScore = health.overall ?? null;
  const healthLabel = health.label || "watch";
  const healthChipCls2 = { healthy:"healthy", warning:"warning", critical:"critical" }[healthLabel] || "watch";
  setPage(`${pageHeader("Executive Center", "AI CEO Assistant: sintesis lintas-domain jadi satu company health score & rekomendasi strategis.",
    `<button class="button button-primary" data-action="analyze-business">${icon('executive',14)} Analyze My Business</button>
     <button class="button" data-action="executive-generate-weekly">Weekly Brief</button>
     <button class="button" data-action="executive-generate-monthly">Monthly Brief</button>`)}
  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="card d-executive domain-card"><div class="card-head"><h3>Company Health Score</h3><span class="health-chip ${healthChipCls2}"><i></i>${esc(healthLabel)}</span></div><div class="card-body" style="display:flex;align-items:center;gap:24px"><div class="score-display"><strong style="color:var(--domain-executive)">${overallScore ?? '—'}</strong><span>/ 100</span></div><div style="flex:1"><div class="domain-scores">${domainScoreBars}</div></div></div></div>
    ${metricCard("Active Workforce Tasks", formatNumber(0), "Cek halaman Workforce", "workforce")}
  </div>
  ${analysisHtml}
  ${briefHtml}
  <div class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h3>Executive Analytics</h3><span class="subtle">Tren lintas-domain — data nyata, bukan simulasi</span></div><div class="business-quick-actions" style="margin:0">${periodTabs}</div></div>
    <div class="card-body">
      <div class="grid grid-3" style="margin-bottom:14px">
        ${chartCard("Revenue Trend", "exec-revenue-chart")}
        ${chartCard("Customer Growth", "exec-customer-growth-chart")}
        ${chartCard("Sales Growth", "exec-sales-growth-chart")}
      </div>
      <div class="grid grid-3">
        ${chartCard("Lead Conversion (%)", "exec-lead-conversion-chart")}
        ${chartCard("Customer Satisfaction", "exec-satisfaction-chart")}
        ${chartCard("AI Performance (Quality Score)", "exec-ai-performance-chart")}
      </div>
      <div class="grid grid-2" style="margin-top:14px">
        <div class="card"><div class="card-head"><h3 style="font-size:13px">Lead Distribution</h3></div><div class="card-body"><div style="height:200px"><canvas id="exec-lead-distribution-chart"></canvas></div></div></div>
        <div class="card"><div class="card-head"><h3 style="font-size:13px">Ringkasan Periode</h3></div><div class="card-body"><p class="subtle" style="font-size:11px;margin:0">Grafik di atas menampilkan data ${trendDays===1?"hari ini":`${trendDays} hari terakhir`}. Belum ada data akan tampak sebagai grafik kosong — ini normal untuk bisnis baru, bukan kesalahan sistem.</p></div></div>
      </div>
    </div>
  </div>
  <div class="card"><div class="card-head"><h3>Riwayat Executive Brief</h3></div>${reportRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tipe</th><th>Ringkasan</th><th>Dibuat</th></tr></thead><tbody>${reportRows}</tbody></table></div>` : emptyState("Belum ada executive brief", "Generate brief weekly/monthly pertama Anda — AI akan menyintesis 6 domain jadi satu rekomendasi strategis.")}</div>`);

  const trendData = state.executiveTrends || {};
  drawChart("exec-revenue", "#exec-revenue-chart", trendData.revenue_trend || [], "bar");
  drawChart("exec-customer-growth", "#exec-customer-growth-chart", trendData.customer_growth || [], "line");
  drawChart("exec-sales-growth", "#exec-sales-growth-chart", trendData.sales_growth || [], "bar");
  drawChart("exec-lead-conversion", "#exec-lead-conversion-chart", trendData.lead_conversion || [], "line");
  drawChart("exec-satisfaction", "#exec-satisfaction-chart", trendData.customer_satisfaction || [], "line");
  drawChart("exec-ai-performance", "#exec-ai-performance-chart", trendData.ai_performance || [], "bar");
  drawDoughnutChart("exec-lead-distribution", "#exec-lead-distribution-chart", ["Cold", "Warm", "Hot"], [sales.cold || 0, sales.warm || 0, sales.hot || 0]);
}

function renderBusinessAnalysis(result) {
  if (!result) return "";
  const healthKind = { Excellent: "active", Good: "active", Warning: "pending", Critical: "error" }[result.business_health_label] || "default";
  const analysis = result.analysis || {};
  const rootCause = (analysis.root_cause_analysis || []).map((item) => `<div class="founder-insight warning" style="margin-bottom:8px"><span></span><div><strong>${esc(item.question)}</strong><p>${esc(item.explanation)}</p></div></div>`).join("");
  const recs = analysis.recommendations || {};
  const recBlock = (label, items, kind) => (items || []).length
    ? `<div style="margin-bottom:10px"><span class="status-badge ${kind}">${esc(label)}</span><ul style="margin:8px 0 0;padding-left:18px">${items.map((i) => `<li style="font-size:12px;margin-bottom:4px">${esc(i)}</li>`).join("")}</ul></div>` : "";
  const plan = analysis.action_plan || {};
  const planBlock = (label, items) => `<div class="card" style="flex:1"><div class="card-head"><h3 style="font-size:13px">${esc(label)}</h3></div><div class="card-body">${(items||[]).length ? `<ul style="margin:0;padding-left:18px">${items.map((i) => `<li style="font-size:12px;margin-bottom:6px">${esc(i)}</li>`).join("")}</ul>` : `<span class="subtle" style="font-size:11px">Tidak ada langkah spesifik.</span>`}</div></div>`;
  const noHistory = result.deltas && result.deltas.has_historical_data === false
    ? `<p class="subtle" style="font-size:11px;margin:0 0 12px">Belum ada riwayat report sebelumnya — analisis ini berdasarkan kondisi saat ini saja, generate weekly/monthly brief dulu agar root-cause bisa membandingkan tren.</p>` : "";
  return `<div class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h3>AI Business Analyst</h3><span class="subtle">Business Health: ${statusBadge(healthKind, result.business_health_label)}</span></div></div>
    <div class="card-body">
      ${noHistory}
      ${analysis.executive_summary ? `<p style="font-size:13px;margin-bottom:14px">${esc(analysis.executive_summary)}</p>` : ""}
      ${rootCause ? `<div style="margin-bottom:14px"><div class="subtle" style="font-size:10px;text-transform:uppercase;margin-bottom:6px">Root Cause Analysis</div>${rootCause}</div>` : ""}
      <div class="subtle" style="font-size:10px;text-transform:uppercase;margin-bottom:6px">Recommendations</div>
      ${recBlock("Prioritas Tinggi", recs.high, "error")}
      ${recBlock("Prioritas Sedang", recs.medium, "pending")}
      ${recBlock("Prioritas Rendah", recs.low, "default")}
      <div class="subtle" style="font-size:10px;text-transform:uppercase;margin:14px 0 6px">Action Plan</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">${planBlock("7 Hari", plan["7_days"])}${planBlock("30 Hari", plan["30_days"])}${planBlock("90 Hari", plan["90_days"])}</div>
    </div>
  </div>`;
}

async function renderWorkforce() {
  loadingPage("Workforce Orchestration", "Koordinasi task lintas-agent: assign, deteksi konflik, eskalasi, dan human approval workflow.");
  let dashboard, tasksResult;
  try {
    [dashboard, tasksResult] = await Promise.all([api.workforceDashboard(), api.workforceTasks({ limit: 50 })]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.workforceDashboard = dashboard; state.workforceTasks = tasksResult.tasks || [];

  const priorityKind = (p) => (p === "critical" || p === "high" ? "error" : (p === "medium" ? "pending" : "active"));
  const statusKind = (s) => (s === "completed" ? "active" : (s === "escalated" || s === "cancelled" ? "error" : "pending"));

  const taskRows = state.workforceTasks.map((t) => `<tr>
    <td>${statusBadge('default', t.domain)}</td>
    <td><span class="table-title">${esc(t.title)}</span>${t.has_conflict ? `<div class="subtle" style="font-size:9px;margin-top:3px;color:var(--danger,#e11d48)">⚠ Konflik: ${esc(t.conflict_note||'')}</div>` : ''}</td>
    <td>${statusBadge(priorityKind(t.priority), t.priority)}</td>
    <td>${statusBadge(statusKind(t.status), t.status)}</td>
    <td>${t.requires_approval ? (t.approved_at ? statusBadge('active','Approved') : statusBadge('pending','Needs approval')) : '—'}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      ${t.status==='pending' ? `<button class="button" data-workforce-status="${esc(t.id)}:in_progress">Start</button>` : ''}
      ${t.status!=='completed' && t.status!=='cancelled' ? `<button class="button button-primary" data-workforce-status="${esc(t.id)}:completed">Complete</button><button class="button button-danger" data-workforce-status="${esc(t.id)}:cancelled">Cancel</button>` : ''}
      ${t.requires_approval && !t.approved_at ? `<button class="button" data-workforce-approve="${esc(t.id)}">Approve</button>` : ''}
    </div></td>
  </tr>`).join("");

  const conflictLabel = dashboard.conflicts_count ? ` — ${dashboard.conflicts_count} konflik` : '';
  setPage(`${pageHeader("Workforce Orchestration", "Task koordinasi lintas Finance/Marketing/HR/Operations/Security/Executive — eksekusi tetap manual lewat masing-masing domain.",
    `<button class="button" data-action="workforce-create-task">${icon('plus',14)} Buat Task</button>
     <button class="button button-primary" data-action="workforce-scan-conflicts">${icon('refresh',14)} Scan Konflik</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Pending", formatNumber(dashboard.by_status?.pending||0), "Task belum dimulai", "workforce")}
    ${metricCard("In Progress", formatNumber(dashboard.by_status?.in_progress||0), "Sedang dikerjakan", "workforce")}
    ${metricCard("Butuh Approval", formatNumber(dashboard.pending_approval_count||0), "Menunggu human approval", "workforce", dashboard.pending_approval_count?'trend-down':'trend-up')}
    ${metricCard("Konflik Terdeteksi", formatNumber(dashboard.conflicts_count||0), "Perlu ditinjau manusia", "workforce", dashboard.conflicts_count?'trend-down':'trend-up')}
  </div>
  ${dashboard.conflicts_count ? `<div class="page-section-label" style="color:var(--amber)">Task list${conflictLabel} — butuh review manusia</div>` : '<div class="page-section-label">Task list</div>'}
  <div class="card"><div class="card-head"><div><h3>Workforce Tasks</h3><span class="subtle">${formatNumber(state.workforceTasks.length)} task lintas domain</span></div>${dashboard.pending_approval_count ? `<span class="approval-count-badge">${dashboard.pending_approval_count} approval</span>` : ''}</div>${taskRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Domain</th><th>Task</th><th>Priority</th><th>Status</th><th>Approval</th><th></th></tr></thead><tbody>${taskRows}</tbody></table></div>` : emptyState("Belum ada task", "Buat task koordinasi pertama untuk salah satu domain AI Workforce.")}</div>`);
}

async function renderWorkforceOverview() {
  loadingPage("AI Workforce Overview", "Company health score lintas Finance/Marketing/HR/Operations/Security/Executive dalam satu tampilan.");
  const results = await Promise.all([
    settle("finance", api.financeDashboard()),
    settle("marketing", api.marketingDashboard()),
    settle("hr", api.hrDashboard()),
    settle("operations", api.opsDashboard()),
    settle("security", api.securityDashboard()),
    settle("executive", api.executiveDashboard()),
    settle("workforce", api.workforceDashboard()),
    settle("learning", api.learningDashboard()),
  ]);
  const data = Object.fromEntries(results.filter((result) => result.ok).map((result) => [result.label, result.data]));
  const failed = results.filter((result) => !result.ok);
  const executiveHealth = data.executive?.health || {};
  const opsHealth = data.operations?.health || {};
  const securityRisk = data.security?.risk_level || "—";
  const workforceStatus = data.workforce?.by_status || {};
  const learningStatus = data.learning?.by_status || {};
  const revenue = data.finance?.revenue_30d_idr ?? data.finance?.total_revenue_idr ?? data.finance?.revenue_idr ?? 0;
  const marketingContent = data.marketing?.content_30d ?? data.marketing?.scheduled_content_count ?? data.marketing?.published_content_count ?? 0;
  const hrPending = data.hr?.pending_training_recommendations ?? data.hr?.open_candidates_count ?? data.hr?.active_employees_count ?? 0;
  const openOpsAlerts = Object.values(data.operations?.open_alerts_by_severity || {}).reduce((sum, value) => sum + Number(value || 0), 0);
  const securityOpenAlerts = data.security?.open_risk_alerts_count ?? data.security?.security_events_24h ?? 0;
  const healthTrend = executiveHealth.label === "healthy" ? "trend-up" : (executiveHealth.label === "critical" ? "trend-down" : "");

  const domainDef = [
    { key:"finance",   label:"Finance",       value:idr(revenue),                                          meta:`${formatNumber(data.finance?.pending_invoices_count||0)} invoice pending`,  route:"finance",       cls:"d-finance"   },
    { key:"marketing", label:"Marketing",      value:formatNumber(marketingContent),                        meta:"Konten/kampanye aktif",                                                     route:"marketing",     cls:"d-marketing"  },
    { key:"hr",        label:"HR",             value:formatNumber(hrPending),                               meta:"Training/kandidat perlu review",                                           route:"hr",            cls:"d-hr"         },
    { key:"operations",label:"Operations",     value:opsHealth.score ?? "—",                                meta:`${formatNumber(openOpsAlerts)} alert terbuka`,                              route:"operations",    cls:"d-operations" },
    { key:"security",  label:"Security",       value:securityRisk,                                          meta:`${formatNumber(securityOpenAlerts)} sinyal risiko`,                         route:"security",      cls:"d-security"   },
    { key:"executive", label:"Executive",      value:executiveHealth.overall ?? "—",                        meta:executiveHealth.label || "Company health",                                   route:"executive",     cls:"d-executive"  },
    { key:"workforce", label:"Workforce",      value:formatNumber((workforceStatus.pending||0)+(workforceStatus.in_progress||0)), meta:"Task aktif lintas-agent",                           route:"workforce",     cls:"d-workforce"  },
    { key:"learning",  label:"Self-Learning",  value:formatNumber(learningStatus.candidate||0),             meta:"Insight menunggu approval",                                                 route:"self-learning", cls:"d-workforce"  },
  ];
  const domainCards = domainDef.map(({ key, label, value, meta, route, cls }) =>
    `<article class="wf-domain-card ${cls}" data-route="${route}" role="button" tabindex="0" aria-label="${esc(label)} — ${esc(meta)}"><div class="wf-domain-label">${esc(label)}</div><div class="wf-domain-value">${value}</div><div class="wf-domain-meta">${esc(meta)}</div></article>`
  ).join("");

  const failedNote = failed.length
    ? `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Data belum lengkap</h3></div><div class="card-body"><p class="subtle" style="margin:0;font-size:11px">${esc(failed.map((r) => `${r.label}: ${r.error.message}`).join(" · "))}</p></div></div>`
    : "";

  const healthLabel = executiveHealth.label || "watch";
  const healthChipCls = { healthy:"healthy", warning:"warning", critical:"critical" }[healthLabel] || "watch";

  setPage(`${pageHeader("AI Workforce Overview", "Satu ringkasan untuk membaca kondisi perusahaan dan langsung masuk ke domain AI Workforce yang perlu perhatian.",
    `<button class="button" data-action="refresh">${icon('refresh',14)} Refresh</button>
     <button class="button button-primary" data-route="workforce">${icon('arrow',14)} Lihat Task</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Company Health", executiveHealth.overall ?? "—", executiveHealth.label || "Executive score", "executive", healthTrend)}
    ${metricCard("Operations Health", opsHealth.score ?? "—", opsHealth.label || "Operational score", "operations", opsHealth.label === "healthy" ? "trend-up" : "")}
    ${metricCard("Security Risk", securityRisk.charAt(0).toUpperCase()+securityRisk.slice(1), "Risk posture", "security", securityRisk === "low" ? "trend-up" : "trend-down")}
    ${metricCard("Active Tasks", formatNumber((workforceStatus.pending||0)+(workforceStatus.in_progress||0)), `${formatNumber(data.workforce?.pending_approval_count||0)} butuh approval`, "workforce", data.workforce?.pending_approval_count ? "trend-down" : "trend-up")}
  </div>
  <div class="page-section-label">Domain overview — klik untuk masuk ke domain</div>
  <div class="workforce-domain-grid">${domainCards}</div>
  ${failedNote}`);
}

async function createWorkforceTaskPrompt() {
  const domain = prompt("Domain (finance/marketing/hr/operations/security/executive):"); if (!domain) return;
  const title = prompt("Judul task:"); if (!title) return;
  const priority = prompt("Priority (low/medium/high/critical):", "medium") || "medium";
  const needsApproval = confirm("Task ini butuh human approval sebelum bisa diselesaikan?");
  try {
    await api.createWorkforceTask({ domain, title, priority, requires_approval: needsApproval });
    toast("Task dibuat.", "success");
    await renderWorkforce();
  } catch (error) { toast(error.message, "error"); }
}

const AGENT_RUN_TASK_FN = { finance: "financeRunTask", marketing: "marketingRunTask", hr: "hrRunTask", operations: "opsRunTask" };
const COMPUTER_AGENT_TYPES = new Set(["computer", "local_computer", "project_debugger"]);

function opsStatCard(label, value, sub, ico, tone = "") {
  return `<div class="ops-stat ${tone}">
    <div class="ops-stat-ico">${icon(ico, 16)}</div>
    <div class="ops-stat-body">
      <div class="ops-stat-value">${value}</div>
      <div class="ops-stat-label">${esc(label)}</div>
      <div class="ops-stat-sub">${esc(sub)}</div>
    </div>
  </div>`;
}

async function renderAgentCenter() {
  loadingPage("Agent Center", "Direktori semua AI agent di platform ini, ringkasan execution log lintas-sistem, dan antrian approval Computer Agent + Local Agent + Channel Messaging.");
  const results = await Promise.all([
    settle("overview", api.agentCenterOverview()),
    settle("agents", api.agentCenterAgents()),
    settle("executionLog", api.executionLogList({ limit: 20 })),
    settle("caPending", api.computerAgentTasks({ status: "pending_approval", limit: 20 })),
    settle("cmPending", api.channelMessagingTasks({ status: "pending_approval", limit: 20 })),
    settle("laPending", api.localAgentHistory({ status: "pending_approval", limit: 20 })),
    settle("localAgent", api.localAgentStatus()),
    settle("aiPower", api.aiPower()),
    settle("agentToggles", api.agentToggles()),
  ]);
  const data = Object.fromEntries(results.filter((r) => r.ok).map((r) => [r.label, r.data]));
  const failed = results.filter((r) => !r.ok);

  const overview = data.overview || {};
  const agents = data.agents?.agents || [];
  const logEntries = data.executionLog?.entries || [];
  const caPending = data.caPending?.tasks || [];
  const cmPending = data.cmPending?.tasks || [];
  const laPending = data.laPending?.commands || [];
  const localAgent = data.localAgent || {};
  const aiPower = data.aiPower || { enabled: true, status: "active" };
  const aiOn = aiPower.enabled !== false;
  const agentToggles = (data.agentToggles && data.agentToggles.toggles) || {};
  const agentEnabled = (key) => agentToggles[key] !== false;   // absen = ON

  const bySourceType = overview.execution_log?.by_source_type || {};
  const totalLogEntries = Object.values(bySourceType).reduce((sum, v) => sum + Number(v || 0), 0);
  const workforcePendingApproval = overview.workforce?.pending_approval_count || 0;
  const caPendingCount = overview.computer_agent_pending_approval_count || 0;
  const cmPendingCount = cmPending.length;
  const laPendingCount = laPending.length;

  const run = state.agentTaskRun;

  // ── Computer Agent result renderer ─────────────────────────────────────────
  function renderComputerAgentResult(r) {
    const toolIcon = t => ({ get_info:"🖥", list_dir:"📂", read_file:"📄", find_files:"🔍", search_text:"🔎", tree:"🌳", scan_project:"🔬", run_command:"⚡", write_file:"✏️", edit_file:"✏️", delete_file:"🗑" }[t] || "🔧");
    const steps = r.steps || [];

    const stepHtml = steps.map((s, i) => {
      const statusColor = s.status === "ok" ? "var(--green)" : s.status === "needs_approval" ? "var(--amber,#f59e0b)" : "var(--red)";
      const statusIcon = s.status === "ok" ? "✅" : s.status === "needs_approval" ? "⏳" : "❌";
      let resultHtml = "";
      const res = s.result || {};

      if (s.status === "ok") {
        if (s.tool === "get_info") {
          resultHtml = `<table style="font-size:11px;border-collapse:collapse;margin-top:6px">` +
            [["Hostname",res.hostname],["Platform",res.platform],["User",res.username],["Home",res.home_dir],["Disk",`${res.disk_used_gb}GB / ${res.disk_total_gb}GB`]]
            .map(([k,v])=>`<tr><td style="color:var(--text-muted);padding:2px 10px 2px 0;white-space:nowrap">${esc(k)}</td><td style="color:var(--text)">${esc(String(v||"–"))}</td></tr>`).join("") + `</table>`;
        } else if (s.tool === "list_dir") {
          const items = res.items || [];
          resultHtml = `<p style="font-size:11px;color:var(--text-muted);margin:4px 0 2px">📂 ${esc(res.path||"")} — ${items.length} item</p>` +
            `<div style="max-height:140px;overflow-y:auto;font-size:11px">` +
            items.slice(0, 30).map(it=>`<span style="display:inline-block;margin:1px 6px 1px 0;color:var(--text-muted)">${it.type==="dir"?"📁":"📄"} ${esc(it.name)}</span>`).join("") +
            (items.length > 30 ? `<span style="color:var(--text-muted)">...+${items.length-30}</span>` : "") + `</div>`;
        } else if (s.tool === "find_files") {
          const matches = res.matches || [];
          resultHtml = `<p style="font-size:11px;color:var(--text-muted);margin:4px 0 2px">${matches.length} file ditemukan</p>` +
            `<div style="max-height:120px;overflow-y:auto;font-size:11px">` +
            matches.slice(0,20).map(m=>`<div style="color:var(--text);padding:1px 0">${esc(m)}</div>`).join("") +
            (matches.length > 20 ? `<div style="color:var(--text-muted)">...+${matches.length-20}</div>` : "") + `</div>`;
        } else if (s.tool === "search_text") {
          const matches = res.matches || [];
          resultHtml = `<p style="font-size:11px;color:var(--text-muted);margin:4px 0 2px">${matches.length} baris ditemukan</p>` +
            `<div style="max-height:120px;overflow-y:auto;font-size:11px;font-family:monospace">` +
            matches.slice(0,15).map(m=>`<div style="padding:1px 0"><span style="color:var(--text-muted)">${esc(m.file.split("/").pop())}:${m.line}</span> <span style="color:var(--text)">${esc(m.text)}</span></div>`).join("") + `</div>`;
        } else if (s.tool === "tree") {
          resultHtml = `<pre style="font-size:10px;max-height:140px;overflow:auto;margin:4px 0 0;color:var(--text)">${esc((res.tree||"").slice(0,2000))}</pre>`;
        } else if (s.tool === "scan_project") {
          const exts = Object.entries(res.extensions||{}).slice(0,6).map(([k,v])=>`${k||"(no ext)"}×${v}`).join(" · ");
          resultHtml = `<p style="font-size:11px;margin:4px 0 2px"><strong>Jenis project:</strong> ${esc(res.project_type||"unknown")} · ${res.total_files} file</p>` +
            `<p style="font-size:11px;color:var(--text-muted);margin:2px 0">File kunci: ${esc((res.key_files||[]).join(", ")||"–")}</p>` +
            `<p style="font-size:11px;color:var(--text-muted);margin:2px 0">Ekstensi: ${esc(exts||"–")}</p>`;
        } else if (s.tool === "read_file") {
          resultHtml = `<pre style="font-size:10px;max-height:140px;overflow:auto;margin:4px 0 0;color:var(--text)">${esc((res.content||"").slice(0,1500))}</pre>`;
        } else if (s.tool === "run_command") {
          resultHtml = `<pre style="font-size:10px;max-height:100px;overflow:auto;margin:4px 0 0;color:${res.exit_code===0?"var(--green)":"var(--red)"}">${esc((res.stdout||res.stderr||"(kosong)").slice(0,1000))}</pre>`;
        }
      } else if (s.status === "needs_approval") {
        resultHtml = `<p style="font-size:11px;color:var(--amber,#f59e0b);margin:4px 0 0">⏳ Menunggu approval di Antrian Izin sebelum dijalankan</p>`;
      } else {
        resultHtml = `<p style="font-size:11px;color:var(--red);margin:4px 0 0">❌ ${esc(s.message||"Error tidak diketahui")}</p>`;
      }

      return `<div style="border-left:3px solid ${statusColor};padding:8px 12px;margin-bottom:8px;background:var(--surface-2);border-radius:0 6px 6px 0">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:2px">
          <span style="font-size:14px">${toolIcon(s.tool)}</span>
          <span style="font-size:12px;font-weight:600;color:var(--text)">${statusIcon} Step ${i+1}: ${esc(s.tool)}</span>
          <span style="font-size:11px;color:var(--text-muted);flex:1">${esc(s.reason||"")}</span>
        </div>
        ${resultHtml}
      </div>`;
    }).join("");

    const needsApprovalHtml = (r.needs_approval||[]).length
      ? `<div style="margin-top:8px;padding:8px 12px;background:var(--surface-2);border-radius:6px;border:1px solid var(--amber,#f59e0b)">
          <p style="font-size:12px;font-weight:600;color:var(--amber,#f59e0b);margin:0 0 4px">⏳ ${r.needs_approval.length} langkah perlu approval:</p>
          ${r.needs_approval.map(na=>`<p style="font-size:11px;color:var(--text-muted);margin:2px 0">${toolIcon(na.tool)} <strong>${esc(na.tool)}</strong> — ${esc(na.reason)}</p>`).join("")}
          <p style="font-size:11px;color:var(--text-muted);margin:4px 0 0">Buka <strong>Antrian Izin</strong> di bawah untuk menyetujui.</p>
        </div>` : "";

    return `<div class="card-body" style="display:grid;gap:4px">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
        <span style="font-size:12px;font-weight:600">🖥 Computer Agent</span>
        ${statusBadge(r.ok_steps > 0 ? "active" : "error", `${r.ok_steps}/${r.total_steps} berhasil`)}
      </div>
      ${stepHtml}${needsApprovalHtml}
    </div>`;
  }

  const runResultPanel = run.lastError
    ? `<div class="card-body"><p style="color:var(--red);margin:0;font-size:13px">${esc(run.lastError)}</p></div>`
    : run.lastResult
    ? run.lastResult._type === "computer_agent"
      ? renderComputerAgentResult(run.lastResult)
      : `<div class="card-body" style="display:grid;gap:8px">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${statusBadge(run.lastResult.status === "completed" ? "active" : "error", run.lastResult.status)}<span class="subtle" style="font-size:10px">${esc(run.lastResult.agent_name || "")}</span></div>
          <div style="white-space:pre-wrap;font-size:12px;line-height:1.6">${esc(run.lastResult.report || "(tidak ada report)")}</div>
          ${run.lastResult.verification ? `<p class="subtle" style="margin:0;font-size:10px">Verifikasi: ${esc(run.lastResult.verification.reasoning || "")}</p>` : ""}
        </div>`
    : "";

  const cmRows = cmPending.map((t) => `<tr>
    <td>${statusBadge("default", t.channel)}</td>
    <td><span class="table-title">${esc(t.recipient || "—")}</span></td>
    <td>${esc(t.message || "—")}</td>
    <td>${esc(t.agent_name || "—")}</td>
    <td>${relativeTime(t.created_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button button-primary" data-cm-approve="${esc(t.id)}">Approve</button>
      <button class="button button-danger" data-cm-reject="${esc(t.id)}">Reject</button>
    </div></td>
  </tr>`).join("");

  const channelLabel = (c) => (c === "chat_pipeline" ? "Chat Pipeline" : "Authenticated API");
  const channelBadge = (c) => statusBadge(c === "chat_pipeline" ? "active" : "default", channelLabel(c));

  const agentRows = agents.map((a) => `<tr>
    <td><span class="table-title">${esc(a.name)}</span></td>
    <td>${statusBadge("default", a.category)}</td>
    <td>${channelBadge(a.channel)}</td>
    <td>${a.skills.length}</td>
    <td>${a.tools.length}</td>
  </tr>`).join("");

  const logStatusKind = (s) => (s === "success" || s === "completed" ? "active" : (s === "failed" || s === "rejected" ? "error" : "pending"));
  const logRows = logEntries.map((e) => `<tr>
    <td>${statusBadge("default", e.source_type)}</td>
    <td><span class="table-title">${esc(e.label || "—")}</span></td>
    <td>${statusBadge(logStatusKind(e.status), e.status)}</td>
    <td>${relativeTime(e.started_at)}</td>
  </tr>`).join("");

  const caRows = caPending.map((t) => `<tr>
    <td><span class="table-title">${esc(t.goal || "—")}</span></td>
    <td>${esc(t.target_url || "—")}</td>
    <td>${relativeTime(t.created_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button button-primary" data-ca-approve="${esc(t.id)}">Approve</button>
      <button class="button button-danger" data-ca-reject="${esc(t.id)}">Reject</button>
    </div></td>
  </tr>`).join("");

  const laRows = laPending.map((t) => {
    let argsPreview = "—";
    try { argsPreview = JSON.stringify(JSON.parse(t.args || "{}")); } catch { argsPreview = t.args || "—"; }
    return `<tr>
    <td>${statusBadge("pending", t.tool)}</td>
    <td><span class="mono" style="font-size:11px">${esc(argsPreview.slice(0, 80))}</span></td>
    <td>${relativeTime(t.created_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button button-primary" data-la-approve="${esc(t.id)}">Approve</button>
      <button class="button button-danger" data-la-reject="${esc(t.id)}">Reject</button>
    </div></td>
  </tr>`;
  }).join("");

  const failedNote = failed.length
    ? `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Data belum lengkap</h3></div><div class="card-body"><p class="subtle" style="margin:0;font-size:11px">${esc(failed.map((r) => `${r.label}: ${r.error.message}`).join(" · "))}</p></div></div>`
    : "";

  const totalApprovalPending = workforcePendingApproval + caPendingCount + cmPendingCount + laPendingCount;

  // ── Local Agent install instructions (offline state) ────────────────────────
  const _laToken = localStorage.getItem("bn_token") || "";
  const _laDl    = `${location.origin}/download/botnesia-local-agent.py`;
  const _laCmd1  = `wget -O botnesia_local_agent.py "${_laDl}"`;
  const _laCmd2  = `python3 botnesia_local_agent.py --token ${_laToken}`;
  const laInstallHtml = `<div style="font-size:13px;margin-bottom:14px">
    <p style="margin:0 0 6px;font-weight:600">Langkah 1 — Download script (sekali saja):</p>
    <code style="display:block;background:var(--surface-2);padding:8px 12px;border-radius:6px;font-size:11px;margin-bottom:10px;word-break:break-all">${esc(_laCmd1)}</code>
    <p style="margin:0 0 6px;font-weight:600">Langkah 2 — Jalankan di terminal:</p>
    <code style="display:block;background:var(--surface-2);padding:8px 12px;border-radius:6px;font-size:11px;margin-bottom:10px;word-break:break-all">${esc(_laCmd2)}</code>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <a href="${esc(_laDl)}" download="botnesia_local_agent.py" class="button button-sm">⬇ Download Script</a>
      <button class="button button-sm" onclick="navigator.clipboard.writeText(${JSON.stringify(_laCmd1+'\n'+_laCmd2)}).then(()=>toast('Perintah disalin!','success'))">Salin Semua Perintah</button>
    </div>
    <p style="margin:10px 0 0;font-size:11px;color:var(--text-muted)">Token sudah terisi otomatis dari akun Anda. Script auto-install dependency.</p>
  </div>`;

  // ── Local Agent: daftar perangkat (multi-device) ────────────────────────────
  const laDevices = localAgent.devices || [];
  const _fmtUptime = (s) => { s = Number(s || 0); if (!s) return "-"; const h = Math.floor(s/3600), m = Math.floor((s%3600)/60); return h ? `${h}j ${m}m` : `${m}m`; };
  const _fmtGB = (v) => (v == null ? "-" : `${Number(v)} GB`);
  const _fmtRamMb = (mb) => (mb == null ? "-" : `${(Number(mb)/1024).toFixed(1)} GB`);
  const _laStatusBadge = (st) => {
    const map = { online: ["#2e9e73", "● Online"], busy: ["var(--amber)", "● Busy"], offline: ["var(--text-muted)", "○ Offline"] };
    const [c, label] = map[st] || map.offline;
    return `<span style="font-size:11px;font-weight:700;color:${c}">${label}</span>`;
  };
  function laDeviceCard(d) {
    const online = d.status !== "offline";
    const metaRow = (k, v) => `<div style="min-width:120px"><div style="font-size:10px;color:var(--text-muted)">${k}</div><div style="font-size:12px;font-weight:600">${esc(String(v ?? "-"))}</div></div>`;
    return `<div class="card" style="padding:14px;margin-bottom:10px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px">
          <strong style="font-size:14px">${esc(d.name || d.hostname || "Perangkat")}</strong>
          ${_laStatusBadge(d.status)}
        </div>
        <div style="display:flex;gap:6px">
          <button class="button button-sm" data-la-rename="${esc(d.device_id)}" title="Ganti nama">✏️</button>
          <button class="button button-sm" data-action="local-agent-refresh" title="Muat ulang status">⟳</button>
          ${online ? `<button class="button button-sm button-danger" data-la-device-disconnect="${esc(d.device_id)}">Putus</button>` : ""}
        </div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:12px">
        ${metaRow("HOSTNAME", d.hostname)}
        ${metaRow("OS", d.platform)}
        ${metaRow("CPU", d.cpu ? `${d.cpu}${d.cpu_count?` (${d.cpu_count} core)`:""}` : (d.cpu_count?`${d.cpu_count} core`:"-"))}
        ${metaRow("RAM", d.cpu_percent!=null||d.ram_percent!=null ? `${_fmtRamMb(d.ram_total_mb)}${d.ram_percent!=null?` · ${Math.round(d.ram_percent)}%`:""}` : _fmtRamMb(d.ram_total_mb))}
        ${metaRow("DISK", _fmtGB(d.disk_total_gb))}
        ${metaRow("IP", d.ip)}
        ${metaRow("CPU LOAD", d.cpu_percent!=null?`${Math.round(d.cpu_percent)}%`:"-")}
        ${metaRow("UPTIME", _fmtUptime(d.uptime_seconds))}
        ${metaRow("LAST SEEN", d.last_seen ? formatDate(d.last_seen, {hour:'2-digit',minute:'2-digit',day:'2-digit',month:'short'}) : "-")}
      </div>
      ${online ? `<div class="ops-device-actions">
        <button class="button button-sm button-primary" data-la-act="agent:${esc(d.device_id)}">${icon('security',13)} Computer Agent</button>
        <button class="button button-sm" data-la-act="terminal:${esc(d.device_id)}">⌘ Terminal</button>
        <button class="button button-sm" data-la-act="files:${esc(d.device_id)}">📂 Files</button>
        <button class="button button-sm" data-la-act="browser:${esc(d.device_id)}">🌐 Browser</button>
        <button class="button button-sm" data-la-act="info:${esc(d.device_id)}">🖥 Info</button>
      </div>` : `<div class="ops-device-actions"><span class="subtle" style="font-size:11px">Perangkat offline — jalankan agent untuk mengaktifkan aksi.</span></div>`}
    </div>`;
  }
  const laInfoHtml = laDevices.length ? `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <span class="subtle" style="font-size:12px">${laDevices.length} perangkat · ${localAgent.online_count||0} online</span>
      <button class="button button-sm" data-action="local-agent-refresh">⟳ Muat ulang</button>
    </div>
    ${laDevices.map(laDeviceCard).join("")}
    <details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:var(--text-2)">+ Tambah perangkat lain</summary><div style="margin-top:10px">${laInstallHtml}</div></details>`
    : laInstallHtml;

  // ── Approval queue sections (only shown if items exist) ──────────────────────
  const caApprovalSection = caPendingCount ? `
    <div class="page-section-label" style="color:var(--amber)">Antrian Izin — Computer Agent (${caPendingCount})</div>
    <div class="card approval-queue-card" style="margin-bottom:16px">
      <div class="card-head"><div><h3>Antrian Izin — Computer Agent</h3><span class="subtle">Perintah berisiko seperti akses file, terminal, atau browser harus disetujui dulu sebelum dijalankan</span></div><span class="approval-count-badge">${caPendingCount}</span></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Goal</th><th>Target URL</th><th>Dibuat</th><th></th></tr></thead><tbody>${caRows}</tbody></table></div>
    </div>` : "";

  const cmApprovalSection = cmPendingCount ? `
    <div class="page-section-label" style="color:var(--amber)">Antrian Izin — Channel Messaging (${cmPendingCount})</div>
    <div class="card approval-queue-card" style="margin-bottom:16px">
      <div class="card-head"><div><h3>Antrian Izin — Channel Messaging</h3><span class="subtle">Pesan keluar belum terkirim sampai disetujui oleh admin</span></div><span class="approval-count-badge">${cmPendingCount}</span></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Penerima</th><th>Pesan</th><th>Dibuat oleh</th><th>Dibuat</th><th></th></tr></thead><tbody>${cmRows}</tbody></table></div>
    </div>` : "";

  const laApprovalSection = laPendingCount ? `
    <div class="page-section-label" style="color:var(--amber)">Antrian Izin — Local Agent (${laPendingCount})</div>
    <div class="card approval-queue-card" style="margin-bottom:16px">
      <div class="card-head"><div><h3>Antrian Izin — Local Agent</h3><span class="subtle">Aksi berisiko di komputer Anda (terminal, tulis/hapus file) harus disetujui dulu sebelum dijalankan</span></div><span class="approval-count-badge">${laPendingCount}</span></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Tool</th><th>Args</th><th>Dibuat</th><th></th></tr></thead><tbody>${laRows}</tbody></table></div>
    </div>` : "";

  const noApprovalSection = (!caPendingCount && !cmPendingCount && !laPendingCount) ? `
    <div class="page-section-label">Antrian Izin</div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-body">
        <p style="font-size:12px;color:var(--text-muted);margin:0 0 8px">Perintah berisiko seperti akses file, terminal, atau browser harus disetujui dulu sebelum dijalankan.</p>
        <p style="font-size:13px;color:var(--text-muted);margin:0">Tidak ada antrean izin.</p>
      </div>
    </div>` : "";

  // ── AI Operations Center: hero + master switch (the heart) ──────────────────
  const devicesOnline = Number(localAgent.online_count ?? (localAgent.devices||[]).filter(d=>d.status!=='offline').length ?? 0);
  const _okLogs = logEntries.filter(e => ['ok','success','completed','done'].includes(String(e.status||'').toLowerCase())).length;
  const successRate = logEntries.length ? Math.round(_okLogs / logEntries.length * 100) : null;
  const aiMasterSwitch = `
    <button class="ai-master-switch ${aiOn?'is-on':'is-off'}" data-action="ai-power-toggle" aria-pressed="${aiOn}" title="${aiOn?'Klik untuk menjeda AI':'Klik untuk mengaktifkan AI'}">
      <span class="ai-master-track"><span class="ai-master-thumb"></span></span>
      <span class="ai-master-label">
        <span class="ai-master-state">${aiOn?'🟢 AI ACTIVE':'○ AI PAUSED'}</span>
        <span class="ai-master-sub">${aiOn?'Otonom — otomatisasi & eksekusi aktif':'Mode manual — otomatisasi dijeda'}</span>
      </span>
    </button>`;
  const heroDeviceId = (localAgent.devices||[]).find(d=>d.status!=='offline')?.device_id || null;
  const heroComputerBtn = heroDeviceId
    ? `<button class="button button-primary" data-la-act="agent:${esc(heroDeviceId)}">${icon('security',14)} Computer Agent</button>`
    : `<button class="button" disabled title="Sambungkan perangkat dulu">${icon('security',14)} Computer Agent</button>`;
  const opsHero = `
    <div class="ops-hero ${aiOn?'is-on':'is-off'}">
      <div class="ops-hero-left">
        <div class="ops-hero-eyebrow">${icon('security',13)} AI OPERATIONS CENTER</div>
        <h1 class="ops-hero-title">${esc(state.org?.name||'Workspace')}</h1>
        <p class="ops-hero-sub">Kendalikan seluruh AI, perangkat, dan otomatisasi dari satu tempat.</p>
        <div class="ops-hero-actions">${heroComputerBtn}</div>
      </div>
      <div class="ops-hero-right">${aiMasterSwitch}</div>
    </div>`;
  const opsStats = `
    <div class="ops-stats">
      ${opsStatCard('Running Agents', formatNumber(agents.length), 'agent aktif', 'agents')}
      ${opsStatCard('Connected Devices', formatNumber(devicesOnline), `${(localAgent.devices||[]).length} terdaftar`, 'security')}
      ${opsStatCard("Today's Tasks", formatNumber(totalLogEntries), 'entri execution log', 'observability')}
      ${opsStatCard('Success Rate', successRate==null?'—':`${successRate}%`, 'dari aktivitas terbaru', 'trend-up')}
      ${opsStatCard('Approval Queue', formatNumber(totalApprovalPending), totalApprovalPending?'menunggu izin':'bersih', 'workforce', totalApprovalPending?'warn':'')}
    </div>`;
  // ── Right rail: Computer Status · Approval · Live Activity ───────────────────
  const primaryDev = localAgent.last_connection || (localAgent.devices||[])[0] || null;
  const railComputer = `
    <div class="ops-rail-card">
      <div class="ops-rail-head">${icon('security',13)} Computer Status</div>
      <div class="ops-rail-body">
        <div class="ops-metric-row"><span>Perangkat online</span><b>${devicesOnline}</b></div>
        ${primaryDev ? `<div class="ops-metric-row"><span>Utama</span><b>${esc(primaryDev.name||primaryDev.hostname||'-')}</b></div>
        <div class="ops-metric-row"><span>Status</span><b style="color:${primaryDev.status!=='offline'?'#2e9e73':'var(--text-muted)'}">${primaryDev.status==='busy'?'● Busy':primaryDev.status!=='offline'?'● Online':'○ Offline'}</b></div>` : `<div class="subtle" style="font-size:12px">Belum ada perangkat terhubung.</div>`}
      </div>
    </div>`;
  const railApproval = `
    <div class="ops-rail-card ${totalApprovalPending?'is-warn':''}">
      <div class="ops-rail-head">${icon('workforce',13)} Approval Queue</div>
      <div class="ops-rail-body">
        <div class="ops-approval-big ${totalApprovalPending?'has':''}">${formatNumber(totalApprovalPending)}</div>
        <div class="subtle" style="font-size:12px">${totalApprovalPending?`${laPendingCount} local · ${caPendingCount} computer · ${cmPendingCount} pesan`:'Tidak ada aksi menunggu izin'}</div>
      </div>
    </div>`;
  const _feedIcon = (s) => ({ok:'✓',success:'✓',completed:'✓',done:'✓',failed:'✕',error:'✕',pending:'◔',running:'◍'}[String(s||'').toLowerCase()]||'•');
  const railActivity = `
    <div class="ops-rail-card">
      <div class="ops-rail-head">${icon('observability',13)} Live Activity</div>
      <div class="ops-rail-body ops-activity">
        ${logEntries.length ? logEntries.slice(0,8).map(e=>`
          <div class="ops-activity-item">
            <span class="ops-activity-dot s-${esc(String(e.status||'').toLowerCase())}">${_feedIcon(e.status)}</span>
            <span class="ops-activity-txt">${esc(e.label||e.source_type||'aktivitas')}</span>
            <span class="ops-activity-time">${e.created_at?relativeTime(e.created_at):''}</span>
          </div>`).join('') : `<div class="subtle" style="font-size:12px">Belum ada aktivitas.</div>`}
      </div>
    </div>`;
  const opsRightRail = `<aside class="ops-rail">${railComputer}${railApproval}${railActivity}</aside>`;

  // ── Agent roster: kartu per-agent dengan toggle ON/OFF masing-masing ────────
  const _catIcon = (c) => ({finance:'finance',marketing:'marketing',hr:'hr',operations:'operations',sales:'workforce',cs:'chat',customer_service:'chat',knowledge:'knowledge',security:'security',executive:'executive',workforce:'workforce',computer:'security'}[String(c||'').toLowerCase()]||'agents');
  function agentRosterCard(name, category, desc, key, extra = "") {
    const on = agentEnabled(key);
    return `<div class="agent-roster-card ${on?'':'is-off'}">
      <div class="arc-head">
        <div class="arc-ico">${icon(_catIcon(category),16)}</div>
        <div class="arc-meta"><strong>${esc(name)}</strong><span class="arc-cat">${esc(category||'agent')}</span></div>
        <button class="mini-switch ${on?'is-on':''}" data-agent-toggle="${esc(key)}" aria-pressed="${on}" title="${on?'Matikan agent ini':'Nyalakan agent ini'}"><span class="mini-track"><span class="mini-thumb"></span></span></button>
      </div>
      <p class="arc-desc">${esc(desc||'AI agent')}</p>
      ${extra}
      <div class="arc-status">${on?'<span class="arc-on">● Aktif</span>':'<span class="arc-off">○ Nonaktif — tugas ditolak (423)</span>'}</div>
    </div>`;
  }
  const computerAgentCard = agentRosterCard(
    "Computer Control Agent", "computer",
    "Kendalikan komputer lokal: terminal, file, browser, dan tugas natural-language.",
    "computer",
    `<div class="arc-actions">${heroComputerBtn}</div>`,
  );
  const agentRosterCards = computerAgentCard + agents.map(a =>
    agentRosterCard(a.name, a.category,
      (a.goals && a.goals[0]) || (a.skills || []).slice(0,3).join(", ") || "AI agent",
      a.category)
  ).join("");

  setPage(`${opsHero}
  ${opsStats}
  <div class="ops-layout">
  <div class="ops-main">
  <div class="page-section-label">Tanya Agent</div>
  <div class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h3>Tanya / Beri Tugas ke AI Agent</h3><span class="subtle">Tulis pertanyaan atau tugas, pilih agent, lalu klik Jalankan</span></div></div>
    <form data-agent-run-task-form class="card-body" style="display:grid;gap:10px">
      <div style="display:grid;gap:8px">
        <select class="select" id="agent-select" name="agent" aria-label="Pilih agent" onchange="window.onAgentSelectChange(this.value)">
          <optgroup label="── Bisnis ──">
            <option value="finance">Finance Agent</option>
            <option value="marketing">Marketing Agent</option>
            <option value="hr">HR Agent</option>
            <option value="operations">Operations Agent</option>
          </optgroup>
          <optgroup label="── Komputer Lokal ──">
            <option value="computer">💻 Computer Agent ${localAgent.connected ? "● Online" : "○ Offline"}</option>
            <option value="local_computer">🖥 Local Computer Agent ${localAgent.connected ? "● Online" : "○ Offline"}</option>
            <option value="project_debugger">🔬 Project Debugger Agent ${localAgent.connected ? "● Online" : "○ Offline"}</option>
          </optgroup>
        </select>
        <p id="agent-hint" style="font-size:11px;color:var(--text-muted);margin:0;display:none"></p>
      </div>
      <textarea class="input" id="agent-goal" name="goal" rows="3" placeholder="Tulis pertanyaan atau tugas untuk agent, contoh: Cek invoice yang belum lunas" required aria-label="Goal"></textarea>
      <div style="display:flex;justify-content:flex-end"><button class="button button-primary" type="submit" ${(run.running || (COMPUTER_AGENT_TYPES.has(run._lastAgent||'') && !localAgent.connected)) ? 'disabled' : ''}>${icon('send',14)} ${run.running ? 'Menjalankan...' : 'Jalankan Tugas'}</button></div>
    </form>
    ${runResultPanel}
  </div>
  <div class="page-section-label">Tes Akses Komputer Lokal ${localAgent.connected ? '<span class="status-badge status-active" style="margin-left:8px;font-size:10px">● TERHUBUNG</span>' : '<span class="status-badge status-inactive" style="margin-left:8px;font-size:10px">○ OFFLINE</span>'}</div>
  <div class="card" style="margin-bottom:16px">
    <div class="card-body">
      ${laInfoHtml}
      <div style="border-top:1px solid var(--border);padding-top:14px;margin-top:${localAgent.connected?'14':'0'}px">
        <p style="font-size:13px;font-weight:600;margin:0 0 4px">Tes Perintah Komputer</p>
        <p style="font-size:12px;color:var(--text-muted);margin:0 0 12px">Bagian ini hanya untuk menguji apakah BotNesia bisa mengakses komputer lokal, file, terminal, dan browser.</p>
        <div style="display:grid;gap:8px;margin-bottom:10px">
          <select id="la-tool" style="padding:6px 10px;border-radius:6px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-size:13px" onchange="laToolChange(this.value)">
            <option value="get_info">get_info — info sistem</option>
            <option value="list_dir">list_dir — lihat isi folder</option>
            <option value="read_file">read_file — baca isi file</option>
            <option value="run_command">run_command — jalankan perintah shell</option>
            <option value="find_files">find_files — cari file</option>
          </select>
          <div id="la-fields" style="display:grid;gap:6px"></div>
          <button class="button button-primary" data-action="local-agent-test" ${localAgent.connected?'':'disabled'}>
            ${localAgent.connected ? 'Kirim Perintah Tes' : '⚠ Agent Offline — sambungkan dulu'}
          </button>
        </div>
        <div id="la-result" style="display:none"></div>
      </div>
    </div>
  </div>
  ${caApprovalSection}${laApprovalSection}${cmApprovalSection}${noApprovalSection}
  <div class="page-section-label">AI Agents — ${formatNumber(agents.length + 1)} agent · toggle masing-masing</div>
  <div class="agent-roster">${agentRosterCards}</div>
  <div class="page-section-label">Execution log</div>
  <div class="card"><div class="card-head"><h3>Execution Log Terbaru</h3><span class="subtle">20 entri terakhir dari semua sumber</span></div>
    ${logRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Sumber</th><th>Label</th><th>Status</th><th>Waktu</th></tr></thead><tbody>${logRows}</tbody></table></div>` : emptyState("Belum ada aktivitas", "Belum ada entri execution log.")}
  </div>
  ${failedNote}
  </div>${opsRightRail}
  </div>`);
  if (localAgent.connected) setTimeout(() => window.laToolChange("get_info"), 0);
}

async function renderLearning() {
  loadingPage(t('route.self-learning.title'), t('route.self-learning.desc'));
  let dashboard, insightsResult;
  try {
    [dashboard, insightsResult] = await Promise.all([api.learningDashboard(), api.learningInsights({ limit: 50 })]);
  } catch (error) { setPage(errorState(error.message)); return; }
  state.learningDashboard = dashboard; state.learningInsights = insightsResult.insights || [];

  const categoryLabels = { sales_pattern: "Sales Pattern", complaint_resolution: "Complaint Resolution", successful_approach: "Successful Approach" };
  const statusKind = (s) => (s === "approved" ? "active" : (s === "rejected" ? "error" : (s === "archived" ? "default" : "pending")));

  const insightRows = state.learningInsights.map((i) => `<tr>
    <td>${statusBadge('default', categoryLabels[i.category] || i.category)}</td>
    <td><span class="table-title">${esc(i.insight)}</span><div class="subtle" style="font-size:9px;margin-top:3px">Terdeteksi ${formatNumber(i.occurrence_count)}x</div></td>
    <td>${statusBadge(statusKind(i.status), i.status)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      ${i.status==='candidate' ? `<button class="button button-primary" data-learning-status="${esc(i.id)}:approved">Approve</button><button class="button button-danger" data-learning-status="${esc(i.id)}:rejected">Reject</button>` : ''}
      ${i.status==='approved' ? `<button class="button" data-learning-status="${esc(i.id)}:archived">Archive</button>` : ''}
    </div></td>
  </tr>`).join("");

  setPage(`${pageHeader(t('route.self-learning.title'), t('route.self-learning.desc'),
    `<button class="button button-primary" data-action="learning-scan">${icon('refresh',14)} ${t('common.refresh')} Scan</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Candidate", formatNumber(dashboard.by_status?.candidate||0), "Waiting review", "learning", dashboard.by_status?.candidate?'default':'trend-up')}
    ${metricCard("Approved", formatNumber(dashboard.by_status?.approved||0), "Active in chat", "learning", "trend-up")}
    ${metricCard("Sales Pattern", formatNumber(dashboard.approved_by_category?.sales_pattern||0), "Approved", "learning")}
    ${metricCard("Successful Approach", formatNumber(dashboard.approved_by_category?.successful_approach||0), "Approved", "learning")}
  </div>
  ${dashboard.by_status?.candidate ? `<div class="page-section-label" style="color:var(--amber)">Insight review queue — ${formatNumber(dashboard.by_status.candidate)} waiting</div>` : `<div class="page-section-label">Insight review queue</div>`}
  <div class="card"><div class="card-head"><div><h3>Learning Insights</h3><span class="subtle">Only approved insights affect bot answers</span></div>${dashboard.by_status?.candidate ? `<span class="approval-count-badge">${dashboard.by_status.candidate}</span>` : ''}</div>${insightRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Category</th><th>Insight</th><th>Status</th><th></th></tr></thead><tbody>${insightRows}</tbody></table></div>` : emptyState("No insights yet", "Run scan to detect patterns from conversations, sales, and complaints.")}</div>`);
}

function parseFeatures(value) {
  if (value && typeof value === "object") return value;
  try { return JSON.parse(value || "{}"); } catch { return {}; }
}

function formatFileSize(bytes) { const n=Number(bytes||0); if(n<1024)return `${n} B`; if(n<1048576)return `${(n/1024).toFixed(1)} KB`; return `${(n/1048576).toFixed(1)} MB`; }

async function renderTeam() {
  loadingPage(t('page.team.title'), t('page.team.subtitle'));
  const [teamResult, rolesResult, meResult] = await Promise.all([settle("team",api.team()),settle("roles",api.roles()),settle("me",api.rbacMe())]);
  state.team = teamResult.ok ? teamResult.data.team || [] : state.team;
  state.roles = rolesResult.ok ? rolesResult.data.roles || [] : [];
  state.rbac = meResult.ok ? meResult.data : state.rbac;
  const rows = state.team.map((member) => `<tr>
    <td><div class="member-col"><span class="avatar" aria-hidden="true">${initials(member.full_name||member.email)}</span><div class="member-meta"><strong>${esc(member.full_name||'Unnamed user')}</strong><small>${esc(member.email)}</small></div></div></td>
    <td><div class="roles-wrap">${(member.roles||[]).map((role)=>`<span class="status-badge ready">${esc(role)}</span>`).join('')||'<span class="subtle">—</span>'}</div></td>
    <td>${statusBadge(member.is_active?'active':'inactive',member.is_active?t('common.active'):t('common.disabled'))}</td>
    <td class="subtle">${relativeTime(member.last_login_at)}</td>
    <td><button class="icon-button" data-team-user="${esc(member.id)}" data-action="manage-member" aria-label="Manage ${esc(member.full_name||member.email)}">${icon('more')}</button></td>
  </tr>`).join("");
  const myPerms = (state.rbac?.permissions||[]);
  const permBadges = myPerms.slice(0,12).map((item) => `<span class="status-badge ready">${esc(item)}</span>`).join('');
  const myRoles = (state.rbac?.roles||[]).join(', ');
  setPage(`${pageHeader(t('page.team.title'), t('page.team.subtitle'),`<button class="button" data-action="export-team">${icon('export',13)} ${t('page.team.export_btn')}</button><button class="button button-primary" data-action="invite-member">${icon('plus',14)} ${t('page.team.add_member_btn')}</button>`)}
  <div class="grid grid-3" style="margin-bottom:16px">
    ${metricCard(t('page.team.workspace_metric'),state.org?.name||'—',state.org?.slug||'tenant',"dashboard")}
    ${metricCard(t('page.team.members_metric'),formatNumber(state.team.length),`${state.team.filter((x)=>x.is_active).length} ${t('common.active')}`,"team")}
    ${metricCard(t('page.team.roles_metric'),formatNumber(state.rbac?.roles?.length||0),myRoles||t('page.team.no_role'),"settings")}
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>${t('page.team.workspace_members')}</h3><span class="subtle">${t('page.team.isolated')}</span></div><span class="status-badge active">${formatNumber(state.team.length)} ${state.team.length !== 1?t('common.members'):t('common.member')}</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('page.team.col_member')}</th><th>${t('page.team.col_roles')}</th><th>${t('page.team.col_status')}</th><th>${t('page.team.col_last_login')}</th><th style="width:44px"></th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState(t('page.team.empty_title'),t('page.team.empty_desc'))}</div>
  <div class="grid grid-2">
    <div class="card"><div class="card-head"><h3>${t('page.team.tenant_workspace')}</h3></div><div class="table-wrap"><table class="data-table"><thead><tr><th>${t('page.team.col_tenant')}</th><th>${t('page.team.col_billing')}</th><th>${t('page.team.col_plan')}</th><th>${t('page.team.col_members')}</th></tr></thead><tbody><tr><td><span class="table-title">${esc(state.org?.name||'Workspace')}</span><div class="subtle mono" style="font-size:8px;margin-top:2px">${esc(state.org?.slug||'tenant')}</div></td><td>${statusBadge(state.org?.billing_status||'active',state.org?.billing_status||'active')}</td><td>${planBadge(state.org?.plan||'free')}</td><td>${formatNumber(state.team.length)}</td></tr></tbody></table></div></div>
    <div class="card"><div class="card-head"><h3>${t('page.team.your_perms')}</h3><span class="subtle">${myPerms.length} ${t('page.team.perms_count')}</span></div><div class="card-body"><div class="your-perms">${permBadges||`<span class="subtle">${t('page.team.no_perms')}</span>`}</div></div></div>
  </div>`);
}

// Translate feature strings from DB (always stored in Indonesian) to active lang
function translateFeature(text) {
  if (getLang() !== "en") return text;
  return String(text)
    .replace(/percakapan\/bulan/gi, "conversations/month")
    .replace(/Knowledge Base dasar/gi, "Basic Knowledge Base")
    .replace(/Knowledge Base lebih besar/gi, "Larger Knowledge Base")
    .replace(/Analytics dasar/gi, "Basic Analytics")
    .replace(/Analytics lengkap/gi, "Full Analytics")
    .replace(/Branding BotNesia/gi, "BotNesia Branding")
    .replace(/SLA Perusahaan/gi, "Enterprise SLA")
    .replace(/Dukungan Prioritas/gi, "Priority Support")
    .replace(/Manajemen Tim/gi, "Team Management")
    .replace(/Akses API/gi, "API Access")
    .replace(/Domain Kustom/gi, "Custom Domain")
    .replace(/Dukungan Dedikasi/gi, "Dedicated Support")
    .replace(/Integrasi Kustom/gi, "Custom Integration")
    .replace(/Keamanan Lanjutan/gi, "Advanced Security")
    .replace(/Log Audit/gi, "Audit Log");
}

// Flip to true (or delete the gatewayStatusBanner block in renderBilling())
// once Midtrans finishes the merchant business review and approves real
// payment channels for this account.
const MIDTRANS_GATEWAY_APPROVED = false;

const BILLING_PAYMENT_BANNER_STYLE = {
  success: "background:#111111;border-color:#2e9e73;color:#2e9e73",
  pending: "background:#111111;border-color:#c99a3e;color:#c99a3e",
  failed:  "background:#111111;border-color:#d64550;color:#d64550",
};
const BILLING_PAYMENT_BANNER_ICON = { success: "✓", pending: "⏳", failed: "✕" };

// Midtrans mengarahkan browser kembali ke /dashboard/billing?order_id=...  setelah
// checkout (full page redirect, bukan navigasi SPA) -- backend main.py meneruskan
// query string itu ke sini sebagai #billing. `order_id` di URL HANYA dipakai untuk
// tahu invoice mana yang harus dicek; status yang ditampilkan selalu dibaca ulang
// dari backend (kolom `invoices.status`, yang cuma diisi oleh midtrans_webhook),
// tidak pernah dipercaya langsung dari redirect. URL dibersihkan segera supaya
// refresh halaman tidak memicu pengecekan berulang dari order_id lama.
async function resolveBillingPaymentBanner() {
  const params = new URLSearchParams(location.search);
  const redirectOrderId = params.get("order_id");
  if (redirectOrderId) {
    state.pendingPaymentOrderId = redirectOrderId;
    state.pendingPaymentAttempts = 0;
    history.replaceState(null, "", location.pathname + "#billing");
  }
  const orderId = state.pendingPaymentOrderId;
  if (!orderId) return "";

  let invStatus = null;
  try { invStatus = (await api.invoiceByNumber(orderId)).invoice?.status; } catch {}

  const outcome = invStatus === "paid" ? "success"
    : (invStatus === "void" || invStatus === "uncollectible") ? "failed"
    : "pending";
  history.replaceState(null, "", location.pathname + `#billing/${outcome}`);

  if (outcome === "pending" && (state.pendingPaymentAttempts||0) < 5) {
    // Webhook Midtrans kadang butuh beberapa detik untuk sampai setelah redirect
    // browser -- coba lagi singkat sebelum menganggap ini benar-benar tertunda.
    state.pendingPaymentAttempts = (state.pendingPaymentAttempts||0) + 1;
    setTimeout(() => { if (state.route === "billing") renderBilling(); }, 3000);
  } else {
    if (outcome === "success") bustCache("plans","subscription","usage","invoices");
    delete state.pendingPaymentOrderId;
    delete state.pendingPaymentAttempts;
  }

  return `<div style="margin-bottom:16px;padding:12px 16px;border:1px solid;border-radius:8px;font-size:13px;${BILLING_PAYMENT_BANNER_STYLE[outcome]}">
    <strong>${BILLING_PAYMENT_BANNER_ICON[outcome]} ${esc(t(`billing.payment_${outcome}_title`))}</strong>
    <div style="margin-top:2px">${esc(t(`billing.payment_${outcome}_sub`))}</div>
  </div>`;
}

async function renderBilling() {
  loadingPage(t('billing.title'), t('billing.subtitle'));
  const paymentBanner = await resolveBillingPaymentBanner();
  const [plansResult, subResult, usageResult, invoicesResult, creditsResult, addonsResult] = await Promise.all([
    cachedSettle("plans", () => api.plans(), 300),
    cachedSettle("subscription", () => api.subscription(), 120),
    cachedSettle("usage", () => api.usage(), 45),
    cachedSettle("invoices", () => api.invoices(), 60),
    settle("credits", api.credits()),
    cachedSettle("addons", () => api.addons(), 120),
  ]);
  state.plans = plansResult.ok ? plansResult.data.plans || [] : [];
  state.salesEmail = (plansResult.ok && plansResult.data.sales_email) || 'sales@botnesia.id';
  state.subscription = subResult.ok ? subResult.data : state.subscription;
  state.usage = usageResult.ok ? usageResult.data.usage || {} : {};
  state.channelUsage = usageResult.ok ? usageResult.data.channel_usage || {} : {};
  state.invoices = invoicesResult.ok ? invoicesResult.data.invoices || [] : [];
  const buyerTax = (invoicesResult.ok && invoicesResult.data.buyer) || null;
  const taxMeta = (invoicesResult.ok && invoicesResult.data.tax) || {};
  const credits = creditsResult.ok ? creditsResult.data : { addon_conversation_balance: 0, topup_packages: [], history: [] };
  const addonsData = addonsResult.ok ? addonsResult.data : { catalog: [], owned: {} };
  const currentKey = state.subscription?.subscription?.plan_key || state.org?.plan || 'free';
  const currentStatus = state.subscription?.subscription?.status || state.org?.billing_status || 'active';
  const isTrial = state.subscription?.subscription?.is_free_trial || currentStatus === 'trialing';
  const trialEnds = state.subscription?.subscription?.trial_ends_at;

  // ── Plan cards (Free, Starter, Pro, Business) in 4-col grid + Enterprise row ──
  const planOrder = ['free','starter','pro','business','enterprise'];
  const sortedPlans = [...state.plans].sort((a, b) => planOrder.indexOf(a.key) - planOrder.indexOf(b.key));
  const mainPlans = sortedPlans.filter(p => p.key !== 'enterprise');
  const enterprisePlan = sortedPlans.find(p => p.key === 'enterprise');

  function buildPlanCard(plan, wide = false) {
    const featureConfig = parseFeatures(plan.features);
    const highlights = Array.isArray(featureConfig.highlights) ? featureConfig.highlights : null;
    const rawFeatures = highlights || (Array.isArray(featureConfig) ? featureConfig : Object.keys(featureConfig).filter((k) => featureConfig[k]));
    const fallbackConvs = plan.max_conversations_per_month === -1 ? t('unlimited') : formatNumber(plan.max_conversations_per_month);
    const features = rawFeatures.length ? rawFeatures : [
      `${plan.max_agents === -1 ? t('unlimited') : plan.max_agents} ${t('billing.feat.agents')}`,
      `${fallbackConvs} ${t('billing.feat.convs_per_month')}`,
    ];
    // Plan description: prefer translated key, fallback to DB value
    const description = t(`billing.plan_desc.${plan.key}`) !== `billing.plan_desc.${plan.key}`
      ? t(`billing.plan_desc.${plan.key}`)
      : (featureConfig.description || plan.description || '');
    const isCustom = !!featureConfig.custom_pricing;
    const isCurrent = plan.key === currentKey;
    const isPopular = plan.key === 'pro';
    const hasTrial = !!plan.free_trial_eligible && !isCustom;

    // eyebrow badge
    let eyebrowHtml = '';
    if (isCurrent && isTrial) {
      const trialLabel = trialEnds ? ` · ${t('billing.trial_ends')} ${formatDate(trialEnds)}` : '';
      eyebrowHtml = `<div class="billing-plan-eyebrow is-trial">${t('billing.trial_active_label')}${trialLabel}</div>`;
    } else if (isCurrent) {
      eyebrowHtml = `<div class="billing-plan-eyebrow is-current">${t('billing.active_plan_label')}</div>`;
    } else if (isPopular) {
      eyebrowHtml = `<div class="billing-plan-eyebrow is-popular">${t('billing.popular')}</div>`;
    } else {
      eyebrowHtml = `<div class="billing-plan-eyebrow" style="visibility:hidden">—</div>`;
    }

    // free trial badge — only for eligible non-current plans
    const trialBadge = hasTrial && !isCurrent
      ? `<div class="billing-trial-badge">${t('billing.trial_badge')}</div>`
      : '';

    // Paket custom (Enterprise): tampil "Custom" + anchor "mulai Rp…/bln"
    // bila ada harga lantai, supaya prospek punya referensi harga.
    const customSub = plan.price_monthly_idr > 0
      ? `${t('billing.starting_from')} ${idr(plan.price_monthly_idr)}${t('billing.per_month_short')}`
      : t('billing.contact_sales_label');
    // Grandfathering: paket aktif dengan harga terkunci → tampil harga locked
    // + harga list (dicoret) + badge, supaya pelanggan lama paham mereka dapat
    // harga lama meski daftar harga sudah naik.
    const sub = state.subscription?.subscription;
    const grandfathered = isCurrent && !isCustom && sub?.is_grandfathered
      && sub?.effective_price_monthly_idr != null;
    let priceHtml;
    if (isCustom) {
      priceHtml = `<div class="billing-plan-price"><strong>${t('billing.custom_price_label')}</strong><span>${customSub}</span></div>`;
    } else if (grandfathered) {
      priceHtml = `<div class="billing-plan-price">`
        + `<strong>${idr(sub.effective_price_monthly_idr)}</strong><span>${t('billing.per_month_short')}</span>`
        + `<div class="billing-plan-locked" title="${esc(t('billing.grandfathered_hint'))}">`
        + `<s>${idr(plan.price_monthly_idr)}</s> · 🔒 ${t('billing.grandfathered_badge')}</div>`
        + `</div>`;
    } else {
      priceHtml = `<div class="billing-plan-price"><strong>${idr(plan.price_monthly_idr)}</strong><span>${t('billing.per_month_short')}</span></div>`;
    }

    const featureListHtml = features.slice(0, wide ? 6 : 8).map(feat =>
      `<li><span class="billing-feature-check">✓</span>${esc(translateFeature(String(feat).replace(/_/g, ' ')))}</li>`
    ).join('');

    let btnLabel, btnAction;
    if (isCurrent) {
      btnLabel = t('billing.btn_current'); btnAction = '';
    } else if (isCustom) {
      // P0-4: JANGAN checkout self-serve; buka quote flow "Hubungi Sales".
      btnLabel = t('billing.btn_contact_sales'); btnAction = `data-contact-sales="${esc(plan.key)}"`;
    } else if (hasTrial) {
      btnLabel = t('billing.btn_start_trial'); btnAction = `data-checkout-trial="${esc(plan.key)}"`;
    } else if (plan.key === 'free') {
      btnLabel = t('billing.btn_start_free'); btnAction = `data-checkout-plan="${esc(plan.key)}"`;
    } else {
      btnLabel = t('billing.btn_choose'); btnAction = `data-checkout-plan="${esc(plan.key)}"`;
    }

    const btnClass = isCurrent ? 'button' : 'button button-primary';
    const wideStyle = wide ? 'grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr 1fr auto;align-items:center;gap:24px' : '';
    const wideFeat = wide ? `<ul class="billing-feature-list" style="columns:2;gap:0 24px;margin:0">${featureListHtml}</ul>` : `<ul class="billing-feature-list">${featureListHtml}</ul>`;

    return `<article class="card billing-plan-card ${isCurrent ? 'is-current' : ''} ${isPopular && !isCurrent ? 'is-popular' : ''}" style="${wideStyle}">
      <div>
        ${eyebrowHtml}
        <h3 class="billing-plan-name">${esc(plan.name)}</h3>
        <p class="billing-plan-desc">${esc(description)}</p>
      </div>
      <div>
        ${priceHtml}
        ${trialBadge}
      </div>
      ${wideFeat}
      <div style="min-width:160px">
        <button class="${btnClass}" style="width:100%;margin-bottom:${hasTrial && !isCurrent && !isCustom ? '6px' : '0'}" ${isCurrent ? 'disabled' : ''} ${btnAction}>${btnLabel}</button>
        ${hasTrial && !isCurrent ? `<button class="button" style="width:100%;font-size:11px" data-checkout-plan="${esc(plan.key)}">${t('billing.btn_subscribe')}</button>` : ''}
      </div>
    </article>`;
  }

  const mainPlanCards = mainPlans.map(p => buildPlanCard(p)).join('');
  const enterpriseCard = enterprisePlan ? buildPlanCard(enterprisePlan, true) : '';
  const pricingNote = `<p style="font-size:11px;color:#6e6e6e;text-align:center;margin:4px 0 20px">${t('billing.pricing_note')}</p>`;

  // ── Addon Conversation Balance section ─────────────────────────────────
  // balance = jumlah percakapan tambahan, BUKAN Rupiah
  const addonBalance = Number(credits.addon_conversation_balance ?? credits.balance ?? 0);
  // Sumber utama = API (billing.TOPUP_PACKAGES). Fallback HARUS sinkron dengan
  // backend (P0-1 repricing) supaya tidak menampilkan nominal lama yang ditolak.
  const topupPackages = (credits.topup_packages || [
    {amount_idr:50000,conversations:350,label:"Rp50.000"},
    {amount_idr:150000,conversations:1100,label:"Rp150.000"},
    {amount_idr:350000,conversations:2700,label:"Rp350.000"},
    {amount_idr:750000,conversations:6000,label:"Rp750.000"},
  ]);
  const creditHistoryRows = (credits.history || []).map(h => {
    const convCount = Number(h.conversations ?? 0);
    const isPaid = h.kind === 'topup' || h.kind === 'bonus';
    return `<tr>
      <td>${statusBadge(isPaid ? 'active' : 'pending', h.kind)}</td>
      <td>${esc(h.description)}</td>
      <td>${idr(h.amount_idr)}</td>
      <td style="font-weight:600;color:${convCount>0?'#2e9e73':'#d64550'}">${convCount>0?'+':''}${formatNumber(convCount)} ${t('billing.conversations_unit')}</td>
      <td>${formatDate(h.created_at)}</td>
      <td>${statusBadge(isPaid ? 'active' : 'pending', isPaid ? 'Paid' : 'Pending')}</td>
    </tr>`;
  }).join('');
  const topupButtons = topupPackages.map(pkg =>
    `<button class="button" style="padding:10px 18px;font-size:13px;font-weight:600;line-height:1.4;text-align:center" data-topup="${pkg.amount_idr}" data-topup-conv="${pkg.conversations}">
      <span style="display:block">${esc(pkg.label)}</span>
      <span style="display:block;font-size:11px;font-weight:400;color:var(--text-3)">+${formatNumber(pkg.conversations)} ${t('billing.conversations_unit')}</span>
    </button>`
  ).join('');
  const creditSection = `
  <div class="grid grid-2" style="margin-bottom:20px">
    <div class="card">
      <div class="card-head"><h3>${t('billing.credits_balance')}</h3></div>
      <div style="padding:0 20px 20px">
        <div style="font-size:36px;font-weight:700;color:var(--text);margin-bottom:2px">${formatNumber(addonBalance)}</div>
        <div style="font-size:13px;color:var(--text-2);margin-bottom:12px">${t('billing.conversations_unit')}</div>
        <p style="font-size:12px;color:var(--text-2);margin:0 0 8px">${t('billing.credits_desc')}</p>
        <p style="font-size:11px;color:var(--text-3);margin:0">${t('billing.credits_hint')}</p>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>${t('billing.credits_buy')}</h3></div>
      <div style="padding:0 20px 20px">
        <p style="font-size:12px;color:var(--text-2);margin:0 0 12px">${t('billing.credits_choose')}</p>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">${topupButtons}</div>
        <p style="font-size:11px;color:var(--text-3);margin:0">${t('billing.credits_note')}</p>
      </div>
    </div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-head"><h3>${t('billing.credits_history')}</h3></div>
    ${creditHistoryRows
      ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('billing.credits_col_type')}</th><th>${t('billing.credits_col_desc')}</th><th>${t('billing.credits_col_amount')}</th><th>${t('billing.credits_col_credits')}</th><th>${t('billing.credits_col_date')}</th><th>${t('billing.credits_col_status')}</th></tr></thead><tbody>${creditHistoryRows}</tbody></table></div>`
      : `<div style="padding:20px">${emptyState(t('billing.credits_empty'), t('billing.credits_empty_sub'), `<button class="button button-primary" data-topup="50000">${t('billing.credits_empty_btn')}</button>`, 'billing')}</div>`
    }
  </div>`;

  // ── Add-on kapasitas section ────────────────────────────────────────────
  // Beli slot agent/anggota/channel/dokumen tambahan di atas limit paket.
  const addonCatalog = addonsData.catalog || [];
  const addonOwned = addonsData.owned || {};
  const addonCards = addonCatalog.map(a => {
    const owned = Number(addonOwned[a.key]?.quantity || 0);
    const nameKey = `billing.addon.${a.key}`;
    const name = t(nameKey) !== nameKey ? t(nameKey) : a.label;
    const unitNote = a.unit > 1 ? ` · +${formatNumber(a.unit)}/${t('billing.addon_unit')}` : '';
    const ownedNote = owned > 0
      ? `<div style="font-size:11px;color:#2e9e73;margin-top:4px">${t('billing.addon_owned')}: +${formatNumber(owned)}</div>` : '';
    return `<div class="card" style="padding:16px">
      <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:6px">${esc(name)}</div>
      <div class="billing-plan-price" style="margin:0 0 10px"><strong style="font-size:20px">${idr(a.price_idr)}</strong><span>${unitNote}</span></div>
      <button class="button button-primary" style="width:100%;font-size:12px" data-addon-buy="${esc(a.key)}">${t('billing.addon_buy')}</button>
      ${ownedNote}
    </div>`;
  }).join('');
  const addonSection = addonCatalog.length ? `
  <div class="card" style="margin-bottom:20px">
    <div class="card-head"><h3>${t('billing.addons_title')}</h3></div>
    <div style="padding:0 20px 20px">
      <p style="font-size:12px;color:var(--text-2);margin:0 0 14px">${t('billing.addons_desc')}</p>
      <div class="grid grid-4" style="gap:12px">${addonCards}</div>
    </div>
  </div>` : '';

  // ── Usage section ───────────────────────────────────────────────────────
  const usageEntries = Object.entries(state.usage || {});
  const usageHtml = usageEntries.length ? usageEntries.map(([key, item]) => {
    const limit = Number(item.limit);
    const used = Number(item.used || 0);
    const isUnlimited = limit === -1;
    const pct = isUnlimited ? 8 : Math.min(100, Math.round((used / Math.max(1, limit)) * 100));
    const nearLimit = !isUnlimited && pct >= 80;
    const atLimit = !isUnlimited && pct >= 100;
    return `<div class="billing-usage-item ${atLimit ? 'at-limit' : nearLimit ? 'near-limit' : ''}">
      <div class="billing-usage-head"><span>${esc(key.replace(/_/g, ' '))}</span><b>${formatNumber(used)} / ${isUnlimited ? '∞' : formatNumber(limit)}</b></div>
      <div class="billing-usage-bar"><span style="width:${pct}%"></span></div>
      ${atLimit ? `<div style="font-size:11px;color:#d64550;margin-top:4px">${t('billing.quota_full')} <button class="button" style="font-size:11px;padding:2px 8px" data-topup="50000">${t('billing.buy_credits_btn')}</button></div>` : ''}
    </div>`;
  }).join('') : emptyState(t('billing.usage_empty'), t('billing.usage_empty_sub'), '', 'analytics');

  // P1-6: eksposur biaya WhatsApp (Meta pass-through) — info, bukan quota bar.
  const waCount = Number((state.channelUsage || {}).whatsapp || 0);
  const waUsageHtml = waCount > 0
    ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:12px;color:var(--text-2)">
         💬 ${t('billing.whatsapp_usage')}: <b>${formatNumber(waCount)}</b> ${t('billing.conversations_unit')}
       </div>`
    : '';

  // ── Invoice table ───────────────────────────────────────────────────────
  const invoiceRows = state.invoices.map((inv) => {
    // P2-9: tampilkan breakdown PPN bila invoice punya pajak (harga inclusive).
    const taxNote = Number(inv.tax_idr) > 0
      ? `<div class="subtle" style="font-size:10px;margin-top:2px">${t('billing.incl_tax')} ${idr(inv.tax_idr)}</div>`
      : '';
    // NPWP pembeli yang tersnapshot di faktur (bila diisi saat invoice terbit).
    const npwpNote = inv.buyer_npwp
      ? `<div class="subtle mono" style="font-size:10px;margin-top:2px">NPWP: ${esc(inv.buyer_npwp)}</div>`
      : '';
    return `<tr><td class="table-title mono">${esc(inv.invoice_number)}${npwpNote}</td><td>${esc(inv.description || 'Subscription')}</td><td>${idr(inv.amount_idr)}${taxNote}</td><td>${statusBadge(inv.status, inv.status)}</td><td>${formatDate(inv.created_at)}</td></tr>`;
  }).join('');

  // ── Identitas Pajak Pembeli (faktur pajak) ──────────────────────────────
  const bt = buyerTax || {};
  const taxProfileCard = `<div class="card" style="margin-bottom:20px">
    <div class="card-head"><h3>${t('billing.tax_profile_title')}</h3></div>
    <div style="padding:0 20px 20px">
      <p style="font-size:12px;color:var(--text-2);margin:0 0 14px">${t('billing.tax_profile_desc')}</p>
      <form id="tax-profile-form" class="auth-form" style="gap:10px;max-width:520px">
        <label>${t('billing.tax_name')}<input name="tax_name" value="${esc(bt.tax_name || '')}" placeholder="PT Contoh Sejahtera"></label>
        <label>${t('billing.tax_npwp')}<input name="tax_npwp" value="${esc(bt.tax_npwp || '')}" placeholder="00.000.000.0-000.000" inputmode="numeric"></label>
        <label>${t('billing.tax_address')}<textarea name="tax_address" rows="2" placeholder="Alamat sesuai NPWP">${esc(bt.tax_address || '')}</textarea></label>
        <label style="flex-direction:row;align-items:center;gap:6px;font-size:13px"><input type="checkbox" name="is_pkp" ${bt.is_pkp ? 'checked' : ''} style="width:auto"> ${t('billing.tax_pkp')}</label>
        <p class="form-error" data-form-error></p>
        <div><button class="button button-primary button-sm" type="submit">${t('billing.tax_save')}</button></div>
      </form>
    </div>
  </div>`;

  const trialBanner = isTrial && trialEnds
    ? `<div style="margin-bottom:16px;padding:12px 16px;background:#111111;border:1px solid #2e9e73;border-radius:8px;font-size:13px;color:var(--text-2)">
         <strong style="color:var(--text)">${t('billing.trial_banner_prefix')}${currentKey.charAt(0).toUpperCase()+currentKey.slice(1)}</strong> ${t('billing.trial_banner_suffix')} <strong style="color:var(--text)">${formatDate(trialEnds)}</strong>. ${t('billing.trial_banner_note')} <a href="#" style="color:#2e9e73;font-weight:600" data-checkout-plan="${currentKey}">${t('billing.trial_banner_activate')}</a>
       </div>`
    : '';

  // Set MIDTRANS_GATEWAY_APPROVED to true (or delete this banner) once Midtrans
  // finishes the merchant business review and real payment channels are live.
  const gatewayStatusBanner = !MIDTRANS_GATEWAY_APPROVED
    ? `<div style="margin-bottom:16px;padding:12px 16px;background:#111111;border:1px solid #c99a3e;border-radius:8px;font-size:13px;color:#c99a3e">
         <strong>${esc(t('billing.gateway_status_title'))}</strong><br>${esc(t('billing.gateway_status_sub'))}
       </div>`
    : '';

  setPage(`${pageHeader(t('billing.title'), t('billing.subtitle'), `${planBadge(currentKey)} <span class="status-badge ${isTrial ? 'pending' : currentStatus === 'active' ? 'active' : 'pending'}">${esc(isTrial ? 'trial' : currentStatus)}</span>`)}
  ${paymentBanner}
  ${gatewayStatusBanner}
  ${trialBanner}
  <div style="margin-bottom:8px;font-size:13px;font-weight:600;color:var(--text-2)">${t('billing.plan_section')}</div>
  <div class="billing-plans-grid" style="grid-template-columns:repeat(4,1fr)">${mainPlanCards}</div>
  ${enterpriseCard ? `<div style="margin-top:8px">${enterpriseCard}</div>` : ''}
  ${pricingNote}
  ${creditSection}
  ${addonSection}
  ${taxProfileCard}
  <div class="grid grid-2">
    <div class="card">
      <div class="card-head"><h3>${t('billing.usage_title')}</h3><span class="subtle mono" style="font-size:9px">${esc(currentKey.toUpperCase())}</span></div>
      <div class="card-body">${usageHtml}${waUsageHtml}</div>
    </div>
    <div class="card">
      <div class="card-head"><h3>${t('billing.invoices_title')}</h3></div>
      ${invoiceRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>${t('billing.invoice_num')}</th><th>${t('billing.invoice_desc')}</th><th>${t('billing.invoice_amount')}</th><th>${t('billing.invoice_status')}</th><th>${t('billing.invoice_date')}</th></tr></thead><tbody>${invoiceRows}</tbody></table></div>` : emptyState(t('billing.invoices_empty'), t('billing.invoices_empty_sub'), '', 'billing')}
    </div>
  </div>`);
}

async function renderSecurity() {
  loadingPage("Security Dashboard","Audit logs, active sessions, suspicious logins, and API key management.");
  const [dashResult, riskAlertsResult, reportsResult] = await Promise.all([
    settle("security", api.securityDashboard()),
    settle("riskAlerts", api.securityRiskAlerts({ status_filter: "open", limit: 50 })),
    settle("reports", api.securityReports({ limit: 10 })),
  ]);
  if (!dashResult.ok) { setPage(`${pageHeader("Security Dashboard","Audit logs, active sessions, suspicious logins, and API key management.")}${errorState(dashResult.error.message)}`); return; }
  state.security = dashResult.data;
  state.securityRiskAlerts = riskAlertsResult.ok ? (riskAlertsResult.data.alerts || []) : [];
  state.securityReports = reportsResult.ok ? (reportsResult.data.reports || []) : [];
  const sec = state.security;
  const riskLevel = sec.risk_level || "—";
  const riskBadgeKind = riskLevel === "low" ? "active" : (riskLevel === "medium" ? "pending" : "error");

  const riskAlertRows = state.securityRiskAlerts.map((a) => `<tr>
    <td>${statusBadge(a.severity==='critical'||a.severity==='high'?'error':a.severity==='medium'?'pending':'active', a.severity)}</td>
    <td><span class="table-title">${esc(a.category.replace(/_/g,' '))}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(a.message)}</div></td>
    <td>${relativeTime(a.created_at)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-security-alert-status="${esc(a.id)}:acknowledged">Acknowledge</button>
      <button class="button button-primary" data-security-alert-status="${esc(a.id)}:resolved">Resolve</button>
    </div></td>
  </tr>`).join("");

  const securityReportRows = state.securityReports.map((r) => `<tr>
    <td>${statusBadge('default', r.report_type)}</td>
    <td>${esc((r.summary||'').slice(0,100))}${(r.summary||'').length>100?'…':''}</td>
    <td>${relativeTime(r.created_at)}</td>
  </tr>`).join("");

  const sessionRows = (sec.active_sessions||[]).map((session) => `<tr><td><span class="table-title">${esc(session.user_email)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(session.user_agent||'—')}</div></td><td class="mono">${esc(session.ip_address||'—')}</td><td>${session.is_suspicious?statusBadge('error','Suspicious'):statusBadge('active','Normal')}</td><td>${relativeTime(session.last_seen_at)}</td><td>${formatDate(session.expires_at)}</td><td><button class="button button-danger" data-revoke-session="${esc(session.id)}">Revoke</button></td></tr>`).join("");

  const auditRows = (sec.audit_logs||[]).map((log) => `<tr><td>${formatDate(log.created_at,{hour:'2-digit',minute:'2-digit'})}</td><td>${esc(log.actor_email||'system')}</td><td><span class="status-badge ready">${esc(log.action)}</span></td><td>${esc(log.resource_type)}${log.resource_id?` <span class="subtle mono" style="font-size:9px">${esc(String(log.resource_id).slice(0,8))}</span>`:''}</td><td class="mono">${esc(log.ip_address||'—')}</td></tr>`).join("");

  const eventRows = (sec.security_events||[]).map((event) => `<tr><td>${formatDate(event.created_at,{hour:'2-digit',minute:'2-digit'})}</td><td>${esc(event.actor_email||'system')}</td><td><span class="status-badge error">${esc(event.action)}</span></td><td class="mono">${esc(event.ip_address||'—')}</td></tr>`).join("");

  const apiKeyRows = (sec.api_keys||[]).map((key) => `<tr><td><span class="table-title">${esc(key.name)}</span><div class="subtle mono" style="font-size:9px;margin-top:3px">${esc(key.key_prefix)}...</div></td><td>${(key.scopes||[]).map((scope)=>`<span class="status-badge ready" style="margin-right:4px">${esc(scope)}</span>`).join('')||'—'}</td><td>${formatNumber(key.usage_count)}</td><td>${relativeTime(key.last_used_at)}</td><td>${key.expires_at?formatDate(key.expires_at):'Never'}</td><td>${statusBadge(key.is_active?'active':'inactive',key.is_active?'Active':'Revoked')}</td><td style="display:flex;gap:6px;flex-wrap:wrap">${key.is_active?`<button class="button" data-rotate-api-key="${esc(key.id)}">Rotate</button><button class="button button-danger" data-revoke-api-key="${esc(key.id)}">Revoke</button>`:'—'}</td></tr>`).join("");

  const scan = state.securityScan;
  const scoreCard = metricCard("Security Score", scan?`${scan.score}/100`:'—', scan?`${scan.findings_count} findings (last scan)`:'Run a scan to compute', "security");
  const findingsCard = scan?.findings?.length ? `<div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Latest scan findings</h3></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Finding</th><th>Recommendation</th></tr></thead><tbody>${scan.findings.map((finding)=>`<tr><td>${statusBadge(finding.severity==='critical'||finding.severity==='high'?'error':finding.severity==='medium'?'pending':'active',finding.severity)}</td><td>${esc(finding.category)}</td><td>${esc(finding.title)}</td><td class="subtle" style="font-size:10px">${esc(finding.recommendation)}</td></tr>`).join('')}</tbody></table></div></div>` : '';

  setPage(`${pageHeader("Security Dashboard","Enterprise security posture: RBAC, audit trail, sessions, suspicious logins, and API keys.",`<div class="security-action-group"><button class="button button-primary" data-action="security-scan">${icon('refresh',14)} Run scan</button><button class="button" data-action="security-scan-and-alert">Scan &amp; alert</button><button class="button" data-action="security-generate-weekly">Weekly report</button><button class="button" data-action="security-generate-monthly">Monthly report</button><button class="button" data-action="create-api-key">${icon('plus',14)} New API key</button></div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${scoreCard}${metricCard("Risk Level",riskLevel.charAt(0).toUpperCase()+riskLevel.slice(1),`Score ${sec.score ?? '—'}/100`,"security",riskLevel==='low'?'trend-up':riskLevel==='high'||riskLevel==='critical'?'trend-down':'')}${metricCard("Open Alerts",formatNumber(state.securityRiskAlerts.length),`${formatNumber((sec.open_security_alerts_by_severity||{}).critical||0)} critical`,"security",state.securityRiskAlerts.length?'trend-down':'trend-up')}${metricCard("Suspicious Logins",formatNumber(sec.suspicious_sessions_count),"New IP detected (30d)","security",sec.suspicious_sessions_count?'trend-down':'trend-up')}</div>
  ${findingsCard}
  <div class="page-section-label">Threat detection</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Risk alerts</h3><span class="subtle">Open — Auto-detected by Security Agent</span></div><span class="status-badge ${state.securityRiskAlerts.length?'error':'active'}">${formatNumber(state.securityRiskAlerts.length)} open</span></div>${riskAlertRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Alert</th><th>Time</th><th style="width:160px"></th></tr></thead><tbody>${riskAlertRows}</tbody></table></div>`:emptyState("No open risk alerts","Run \"Scan & alert\" to detect threats, API abuse, and tenant isolation issues.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Security reports</h3><span class="subtle">Weekly and monthly AI-generated reports</span></div>${securityReportRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Summary</th><th>Created</th></tr></thead><tbody>${securityReportRows}</tbody></table></div>`:emptyState("No reports yet","Generate a weekly or monthly security report from the action buttons above.")}</div>
  <div class="page-section-label">Session management</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Active sessions</h3><span class="subtle">JWT sessions with IP and expiry tracking</span></div></div>${sessionRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>User</th><th>IP address</th><th>Status</th><th>Last seen</th><th>Expires</th><th style="width:80px"></th></tr></thead><tbody>${sessionRows}</tbody></table></div>`:emptyState("No active sessions","Sessions appear here after users log in.")}</div>
  <div class="page-section-label">API access</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>API keys</h3><span class="subtle">Rotation and usage tracking per key</span></div></div>${apiKeyRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Key</th><th>Scopes</th><th>Usage</th><th>Last used</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${apiKeyRows}</tbody></table></div>`:emptyState("No API keys","Create an API key to access BotNesia programmatically.")}</div>
  <div class="page-section-label">Audit trail</div>
  <div class="grid grid-2">
    <div class="card"><div class="card-head"><div><h3>Security events</h3><span class="subtle">Login failures, permission denials, suspicious logins</span></div></div>${eventRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Event</th><th>IP</th></tr></thead><tbody>${eventRows}</tbody></table></div>`:emptyState("No security events","Failed logins and suspicious activity appear here.")}</div>
    <div class="card"><div class="card-head"><div><h3>Audit log</h3><span class="subtle">All config, billing, and auth changes</span></div></div>${auditRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>IP</th></tr></thead><tbody>${auditRows}</tbody></table></div>`:emptyState("No audit entries","Login, billing, and configuration changes are recorded here.")}</div>
  </div>`);
}

function showCreateApiKey() {
  el("#modal-root").innerHTML = modal({title:t('modal.apikey.title'),body:`<form id="create-api-key-form"><div class="form-grid"><label class="field full"><span>${t('modal.apikey.name')}</span><input name="name" required placeholder="${t('modal.apikey.name_ph')}"></label><label class="field"><span>${t('modal.apikey.expires')}</span><input name="expires_in_days" type="number" min="1" placeholder="${t('modal.apikey.never')}"></label></div></form>`,footer:`<button class="button" data-action="close-modal">${t('cancel')}</button><button class="button button-primary" data-action="submit-create-api-key">${t('modal.apikey.create')}</button>`});
}

async function submitCreateApiKey() {
  const form = el("#create-api-key-form"); if(!form || !form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  const body = {name: data.name};
  if (data.expires_in_days) body.expires_in_days = Number(data.expires_in_days);
  const button = el("[data-action=submit-create-api-key]"); button.disabled = true;
  try {
    const result = await api.createApiKey(body);
    el("#modal-root").innerHTML = modal({title:"API key created",body:`<p class="subtle" style="font-size:11px">Simpan key ini sekarang — hanya ditampilkan sekali.</p><div class="form-grid"><label class="field full"><span>API key</span><input value="${esc(result.key)}" readonly onclick="this.select()"></label></div>`,footer:`<button class="button button-primary" data-action="close-modal">Done</button>`});
    toast("API key created.","success");
    await renderSecurity();
  } catch(error) { toast(error.message,"error"); button.disabled = false; }
}

async function renderChannels() {
  loadingPage(t('page.channels.title'), t('page.channels.subtitle'));
  const [statusResult, analyticsResult, whatsappResult, metaResult] = await Promise.all([
    settle("status",api.channelStatus()),
    settle("analytics",api.channelAnalytics(30)),
    settle("whatsapp",api.whatsappEmbeddedStatus()),
    settle("metaOAuth",api.metaOAuthStatus()),
  ]);
  state.channels = statusResult.ok ? statusResult.data.channels || [] : [];
  state.channelAnalytics = analyticsResult.ok ? analyticsResult.data : {};
  state.whatsappAccounts = whatsappResult.ok ? whatsappResult.data.accounts || [] : [];
  state.metaOAuth = metaResult.ok ? metaResult.data : {};
  const CID = { whatsapp:'cid-whatsapp', telegram:'cid-telegram', instagram:'cid-instagram', facebook:'cid-facebook', website:'cid-website' };
  const channelDot = (key, text) => `<span class="channel-icon-dot ${CID[key]||'cid-default'}" aria-hidden="true">${text}</span>`;
  const catalog = [
    ["whatsapp","WhatsApp","Meta Cloud API"],["telegram","Telegram","Telegram Bot API"],
    ["instagram","Instagram","Instagram Messaging API"],["facebook","Facebook Messenger","Messenger Platform"],
    ["website","Website Chat","Embeddable BotNesia widget"],
  ];
  const cards = catalog.map(([key,label,provider]) => {
    if (key === "whatsapp") {
      const accounts = state.whatsappAccounts || [];
      const connected = accounts.filter((account) => account.connected);
      const errors = accounts.filter((account) => account.connection_status === "error");
      const status = connected.length ? "connected" : (errors.length ? "error" : "disconnected");
      const accountRows = accounts.length
        ? accounts.map((account) => {
            const bot = state.bots.find((item) => item.id === account.bot_id);
            return `<div class="channel-stat"><span>${esc(bot?.name || "AI agent")}</span><strong>${esc(account.phone_number_id || "Setup incomplete")}</strong></div>`;
          }).join("")
        : `<div class="channel-stat"><span>Connection</span><strong>Not configured</strong></div>`;
      const accountActions = connected.map((account) => `<button class="button button-danger" data-disconnect-whatsapp-bot="${esc(account.bot_id)}">Disconnect ${esc(state.bots.find((bot) => bot.id === account.bot_id)?.name || "agent")}</button>`).join("");
      return `<article class="card channel-card"><div class="card-head"><div class="channel-title">${channelDot('whatsapp','WA')}<div><h3>WhatsApp</h3><span class="subtle">Meta Embedded Signup · no token copy-paste</span></div></div>${statusBadge(status,status.charAt(0).toUpperCase()+status.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Connected agents</span><strong>${formatNumber(connected.length)}</strong></div>${accountRows}<div class="channel-actions"><button class="button button-primary" data-action="connect-whatsapp">Connect agent</button>${accountActions}</div></div></article>`;
    }
    const item = state.channels.find((row)=>row.channel_type===key && row.status!=="disconnected") || state.channels.find((row)=>row.channel_type===key);
    if (key === "facebook" || key === "instagram") {
      const oauth = state.metaOAuth || {};
      const selected = oauth.selected || {};
      const channelSelection = selected[key] || {};
      const connected = item?.status === "connected";
      const assetName = key === "facebook" ? channelSelection.page_name : channelSelection.instagram_username;
      const oauthStatus = oauth.status === "reauth_required" ? "error" : (connected ? "connected" : "disconnected");
      return `<article class="card channel-card"><div class="card-head"><div class="channel-title">${channelDot(key,initials(label))}<div><h3>${esc(label)}</h3><span class="subtle">Meta OAuth · tenant-owned account</span></div></div>${statusBadge(oauthStatus,oauthStatus.charAt(0).toUpperCase()+oauthStatus.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Account</span><strong>${esc(assetName||item?.display_name||"Not selected")}</strong></div><div class="channel-stat"><span>Token expiry</span><strong>${oauth.token_expires_at?formatDate(oauth.token_expires_at):"Not connected"}</strong></div><div class="channel-stat"><span>Agent</span><strong>${esc(state.bots.find((bot)=>bot.id===(item?.bot_id||channelSelection.bot_id))?.name||"Not assigned")}</strong></div><div class="channel-actions">${connected?`<button class="button" data-action="refresh-meta-token">Refresh access</button><button class="button button-danger" data-disconnect-channel="${esc(item.id)}">Disconnect</button>`:`<button class="button button-primary" data-connect-meta-channel="${key}">${key==='facebook'?'Connect Facebook':'Connect Instagram Business'}</button>`}</div></div></article>`;
    }
    const status = item?.status || "disconnected";
    return `<article class="card channel-card"><div class="card-head"><div class="channel-title">${channelDot(key,initials(label))}<div><h3>${esc(label)}</h3><span class="subtle">${esc(provider)}</span></div></div>${statusBadge(status,status.charAt(0).toUpperCase()+status.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Last activity</span><strong>${relativeTime(item?.last_activity_at||item?.connected_at)}</strong></div><div class="channel-stat"><span>Messages</span><strong>${formatNumber(item?.message_count||0)}</strong></div><div class="channel-stat"><span>Display name</span><strong>${esc(item?.display_name||"Not configured")}</strong></div><div class="channel-actions">${status==="connected"?`<button class="button" data-action="refresh-channel-health">Health check</button><button class="button button-danger" data-disconnect-channel="${esc(item.id)}">Disconnect</button>`:`<button class="button button-primary" data-connect-channel-type="${key}">Connect ${esc(label)}</button>`}</div></div></article>`;
  }).join("");
  const a = state.channelAnalytics || {};
  const connectedCount = state.channels.filter((ch) => ch.status === 'connected').length;
  const usage = (a.channel_usage||[]).map((row) => `<tr><td><div class="channel-title" style="gap:8px">${channelDot(row.channel,initials(row.channel))}<span class="table-title">${esc(row.channel)}</span></div></td><td>${formatNumber(row.messages)}</td><td>${formatNumber(row.active_users)}</td></tr>`).join("");
  setPage(`${pageHeader(t('page.channels.title'), t('page.channels.subtitle'),`<button class="button" data-action="refresh-channel-health">${icon('refresh',14)} Health check</button><button class="button button-primary" data-action="connect-channel">${icon('plus',14)} ${t('page.channels.connect_btn')}</button>`)}
  <div class="grid grid-4">${metricCard("Total Messages",formatNumber(a.total_messages),"Last 30 days","chat")}${metricCard("Active Users",formatNumber(a.active_users),"Unique channel users","team")}${metricCard("Avg Response",`${Number(a.response_time_ms||0).toFixed(0)}ms`,"Channel delivery time","analytics")}${metricCard("Connected",formatNumber(connectedCount),`of ${catalog.length} channels`,"channels",connectedCount>0?'trend-up':'')}</div>
  <div class="page-section-label">Channel status</div>
  <div class="grid channel-grid">${cards}</div>
  <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Channel usage</h3><span class="subtle">Per-tenant message and active-user distribution</span></div></div>${usage?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Messages</th><th>Active Users</th></tr></thead><tbody>${usage}</tbody></table></div>`:emptyState("No channel traffic","Usage appears after the first inbound message.")}</div>`);
  const params=new URLSearchParams(location.search);
  if(params.get("meta_oauth")==="success"){
    const channel=params.get("meta_channel")||"facebook";
    history.replaceState(null,"",location.pathname+"#channels");
    setTimeout(()=>showMetaAssetSelection(channel),0);
  } else if(params.get("meta_oauth") && params.get("meta_oauth")!=="success"){
    const metaError=params.get("meta_error");
    toast(metaError?`Meta login failed: ${metaError}`:"Meta login was not completed.","error");
    history.replaceState(null,"",location.pathname+"#channels");
  }
}

const COMM_CENTER_PERIODS = [["1","Today"],["7","7 Days"],["30","30 Days"],["90","90 Days"],["365","1 Year"]];

async function renderCommunicationCenter() {
  loadingPage("Communication Center", "Status koneksi dan performa AI lintas semua channel pelanggan.");
  const days = state.commCenterDays || 30;
  const [statusResult, analyticsResult, gmailResult] = await Promise.all([
    settle("status", api.channelStatus()),
    settle("analytics", api.channelAnalytics(days)),
    settle("gmail", api.gmailPoller()),
  ]);
  const channels = statusResult.ok ? statusResult.data.channels || [] : [];
  const a = analyticsResult.ok ? analyticsResult.data : {};
  const gmail = gmailResult.ok ? gmailResult.data : {};
  const usageByChannel = Object.fromEntries((a.channel_usage || []).map((row) => [row.channel, row]));

  const periodTabs = COMM_CENTER_PERIODS.map(([value, label]) => `<button class="button ${days===Number(value)?'button-primary':''}" data-comm-period="${value}">${label}</button>`).join("");

  const catalog = [
    ["whatsapp", "WhatsApp"], ["telegram", "Telegram"], ["instagram", "Instagram"],
    ["facebook", "Facebook Messenger"], ["website", "Website Chat"],
  ];
  const CID2 = { whatsapp:'cid-whatsapp', telegram:'cid-telegram', instagram:'cid-instagram', facebook:'cid-facebook', website:'cid-website' };
  const channelCards = catalog.map(([key, label]) => {
    const item = channels.find((row) => row.channel_type === key && row.status !== "disconnected") || channels.find((row) => row.channel_type === key);
    const status = item?.status || "disconnected";
    const usage = usageByChannel[key] || {};
    return `<article class="card channel-card"><div class="card-head"><div class="channel-title"><span class="channel-icon-dot ${CID2[key]||'cid-default'}" aria-hidden="true">${initials(label)}</span><div><h3>${esc(label)}</h3></div></div>${statusBadge(status, status.charAt(0).toUpperCase()+status.slice(1))}</div><div class="card-body">
      <div class="channel-stat"><span>Messages</span><strong>${formatNumber(usage.messages||0)}</strong></div>
      <div class="channel-stat"><span>Response rate</span><strong>${usage.response_rate_pct!=null?`${usage.response_rate_pct}%`:'—'}</strong></div>
      <div class="channel-stat"><span>Response time</span><strong>${usage.response_time_ms!=null?`${Number(usage.response_time_ms).toFixed(0)}ms`:'—'}</strong></div>
      <div class="channel-stat"><span>Satisfaction</span><strong>${usage.satisfaction_avg!=null?`${usage.satisfaction_avg}/5`:'—'}</strong></div>
      <div class="channel-stat"><span>AI resolution</span><strong>${usage.ai_resolution_rate_pct!=null?`${usage.ai_resolution_rate_pct}%`:'—'}</strong></div>
    </div></article>`;
  }).join("");

  const gmailStatus = gmail.enabled && gmail.running ? "connected" : (gmail.enabled ? "pending" : "disconnected");
  const gmailCard = `<article class="card channel-card"><div class="card-head"><div class="channel-title"><span class="channel-icon-dot cid-email" aria-hidden="true">GM</span><div><h3>Email (Gmail)</h3></div></div>${statusBadge(gmailStatus, gmailStatus.charAt(0).toUpperCase()+gmailStatus.slice(1))}</div><div class="card-body">
    <div class="channel-stat"><span>Polling interval</span><strong>${formatNumber(gmail.interval_seconds||0)}s</strong></div>
    <div class="channel-stat"><span>Max per poll</span><strong>${formatNumber(gmail.max_messages||0)}</strong></div>
    <div class="channel-stat"><span>Catatan</span><strong style="font-size:10px">Email memakai jalur polling terpisah dari channel lain — metrik response/satisfaction belum tersedia.</strong></div>
  </div></article>`;

  const breakdownRows = (a.channel_usage || []).map((row) => `<tr>
    <td><span class="table-title">${esc(row.channel)}</span></td>
    <td>${formatNumber(row.messages)}</td>
    <td>${row.response_rate_pct!=null?`${row.response_rate_pct}%`:"—"}</td>
    <td>${row.response_time_ms!=null?`${Number(row.response_time_ms).toFixed(0)}ms`:"—"}</td>
    <td>${row.satisfaction_avg!=null?`${row.satisfaction_avg}/5`:"—"}</td>
    <td>${row.ai_resolution_rate_pct!=null?`${row.ai_resolution_rate_pct}%`:"—"}</td>
  </tr>`).join("");

  setPage(`${pageHeader("Communication Center", "Satu pandangan untuk semua channel komunikasi pelanggan — status koneksi, kecepatan respons, kepuasan, dan tingkat penyelesaian oleh AI.", `<div class="business-quick-actions">${periodTabs}</div>`)}
  <div class="grid grid-4" style="margin:16px 0">
    ${metricCard("Total Messages", formatNumber(a.total_messages||0), `${days===1?"Today":days+" hari terakhir"}`, "communication-center")}
    ${metricCard("Response Rate", a.response_rate_pct!=null?`${a.response_rate_pct}%`:"—", "Pesan terjawab / pesan masuk", "channels", a.response_rate_pct>=90?"trend-up":"")}
    ${metricCard("Customer Satisfaction", a.satisfaction_avg!=null?`${a.satisfaction_avg}/5`:"Belum ada data", "Rating rata-rata percakapan", "handoffs")}
    ${metricCard("AI Resolution Rate", a.ai_resolution_rate_pct!=null?`${a.ai_resolution_rate_pct}%`:"Belum ada data", "Selesai tanpa human handoff", "executive", a.ai_resolution_rate_pct>=80?"trend-up":"")}
  </div>
  <div class="grid channel-grid">${channelCards}${gmailCard}</div>
  <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Breakdown per Channel</h3><span class="subtle">${days===1?"Today":days+" hari terakhir"}</span></div></div>${breakdownRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Messages</th><th>Response Rate</th><th>Response Time</th><th>Satisfaction</th><th>AI Resolution</th></tr></thead><tbody>${breakdownRows}</tbody></table></div>`:emptyState("Belum ada data","Data muncul setelah ada pesan masuk dari channel manapun.")}</div>`);
}

async function renderAbout() {
  setPage(`<section class="business-command">
    <section class="business-hero">
      <div class="business-hero-copy">
        <img class="business-hero-logo" src="/assets/brand/botnesia-clean-logo.png" alt="BotNesia logo">
        <span class="eyebrow">ABOUT BOTNESIA</span>
        <h2>AI Workforce untuk Setiap Bisnis Indonesia</h2>
        <p>BotNesia membangun tim AI — Customer Service, Sales, Marketing, Finance, HR, Operations, Security, hingga Executive Assistant — yang bekerja 24/7 untuk bisnis Anda, tanpa perlu tim teknologi mahal.</p>
      </div>
    </section>
    <section class="business-main-grid">
      <div class="business-panel"><div class="business-section-head"><div><span class="eyebrow">VISION</span><h3>Visi Kami</h3></div></div>
        <div style="padding:20px"><p style="margin:0;color:var(--text-2);line-height:1.7;font-size:13px">Menjadi platform AI Workforce nomor satu di Indonesia — tempat setiap UMKM hingga perusahaan besar bisa memiliki tim AI selengkap perusahaan teknologi besar, tanpa harus membangun tim engineering sendiri.</p></div></div>
      <div class="business-panel"><div class="business-section-head"><div><span class="eyebrow">MISSION</span><h3>Misi Kami</h3></div></div>
        <div style="padding:20px"><p style="margin:0;color:var(--text-2);line-height:1.7;font-size:13px">Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal — cukup satu platform, BotNesia menghadirkan tenaga kerja AI yang siap bekerja di berbagai fungsi bisnis sekaligus.</p></div></div>
    </section>
    <section class="business-panel">
      <div class="business-section-head"><div><span class="eyebrow">WHY BOTNESIA EXISTS</span><h3>Mengapa BotNesia Dibangun</h3></div></div>
      <div style="padding:20px"><p style="margin:0 0 12px;color:var(--text-2);line-height:1.7;font-size:13px">Sebagian besar bisnis di Indonesia — dari toko online kecil hingga perusahaan menengah — tidak punya akses ke tim data scientist atau engineer AI seperti perusahaan besar. Software enterprise yang ada pun sering terlalu mahal dan rumit untuk skala mereka.</p>
      <p style="margin:0;color:var(--text-2);line-height:1.7;font-size:13px">BotNesia hadir untuk menutup jarak itu: satu platform yang menggabungkan AI Customer Service, Sales, Marketing, Finance, HR, Operations, Security, dan Executive Assistant — semuanya terhubung, semuanya bisa dipantau dan disetujui manusia, dan semuanya bisa dijalankan tanpa tim teknologi internal.</p></div>
    </section>
  </section>`);
}

async function renderFounderStory() {
  setPage(`<section class="business-command">
    <section class="business-hero">
      <div class="business-hero-copy">
        <span class="eyebrow">FOUNDER STORY</span>
        <h2>Cerita di Balik BotNesia</h2>
        <p>Dibangun oleh seseorang yang percaya bahwa AI seharusnya bisa diakses semua bisnis — bukan hanya yang punya tim teknologi besar.</p>
      </div>
      <div class="business-health-card">
        <span>Founder</span>
        <strong style="font-size:32px">Asrori</strong>
        <p>Pendiri BotNesia</p>
      </div>
    </section>
    <section class="business-panel">
      <div class="business-section-head"><div><span class="eyebrow">MISI PENDIRI</span><h3>Mengapa BotNesia Dibangun</h3></div></div>
      <div style="padding:20px"><p style="margin:0;color:var(--text-2);line-height:1.85;font-size:14px">"Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal."</p></div>
    </section>
    <section class="business-panel" style="margin-top:16px">
      <div class="business-section-head"><div><span class="eyebrow">CERITA</span><h3>Dari Mana BotNesia Dimulai</h3></div></div>
      <div style="padding:20px"><p style="margin:0 0 12px;color:var(--text-2);line-height:1.7;font-size:13px">Asrori melihat dari dekat betapa besar jarak antara bisnis kecil-menengah dengan teknologi AI yang sebenarnya bisa membantu mereka tumbuh — bukan karena teknologinya tidak ada, tapi karena terlalu mahal dan rumit untuk dipasang sendiri.</p>
      <p style="margin:0;color:var(--text-2);line-height:1.7;font-size:13px">BotNesia dibangun sebagai jawaban atas masalah itu: AI Workforce yang siap pakai, terjangkau, dan tetap mengutamakan kendali manusia di setiap keputusan penting — supaya pemilik bisnis tetap memegang kendali, bukan AI yang berjalan sendiri tanpa pengawasan.</p></div>
    </section>
  </section>`);
}

const INVESTOR_DEMO_STEPS = ["Collecting Data","Analyzing Revenue","Analyzing Customers","Analyzing Operations","Finding Root Cause","Generating Recommendations","Creating Action Plan","Generating Executive Report","Predicting Business Growth","Executive Conclusion"];

function investorDemoStepperHtml(doneUpTo, activeIndex) {
  return `<ul class="demo-stepper">${INVESTOR_DEMO_STEPS.map((label, i) => `<li class="${i < doneUpTo ? "done" : ""} ${i === activeIndex ? "active" : ""}"><span class="step-dot">${i < doneUpTo ? "✓" : i + 1}</span><span class="step-label">${esc(label)}</span></li>`).join("")}</ul>`;
}

async function renderInvestorDemo() {
  setPage(`<section class="business-command">
    <section class="business-hero">
      <div class="business-hero-copy">
        <span class="eyebrow">INVESTOR DEMO MODE</span>
        <h2>Lihat AI Workforce Bekerja, Live</h2>
        <p>Simulasi perusahaan yang sedang mengalami penurunan — AI akan menganalisis data, menemukan root cause, memberi rekomendasi, menyusun action plan, dan memprediksi pemulihan. Semua dijalankan live oleh AI yang sama dengan AI Business Analyst di Executive Center.</p>
        <div class="business-quick-actions"><button class="button button-primary" data-action="run-investor-demo">${icon("executive",14)} Run Investor Demo</button></div>
      </div>
      <div class="business-health-card">
        <span>Skenario Demo</span>
        <strong style="font-size:30px">Revenue -15%</strong>
        <p>Customer -8% &middot; Hot leads turun tajam &middot; Operations &amp; Security menurun</p>
      </div>
    </section>
    <section class="business-panel" id="investor-demo-stepper-panel" style="display:none">
      <div class="business-section-head"><div><span class="eyebrow">AI WORKING</span><h3>Proses Analisis</h3></div></div>
      <div style="padding:18px 22px"><div id="investor-demo-stepper"></div></div>
    </section>
    <div id="investor-demo-result"></div>
  </section>`);
}

function renderInvestorDemoResult(result) {
  if (!result || result.error) return errorState(result?.error || "Demo gagal dijalankan.");
  const predicted = result.predicted_improvement || {};
  return `<div class="demo-banner">${icon("about",14)} Mode Simulasi — seluruh data di bawah ini adalah skenario demo, bukan data bisnis nyata.</div>
  ${renderBusinessAnalysis(result)}
  <div class="business-panel" style="margin-top:0">
    <div class="business-section-head"><div><span class="eyebrow">PREDICTED IMPROVEMENT</span><h3>Prediksi Pemulihan Bisnis</h3></div></div>
    <div style="padding:20px"><p style="margin:0 0 6px;font-size:28px;font-weight:800;color:var(--green)">+${esc(predicted.revenue_recovery_pct ?? "—")}% Revenue</p>
    <p style="margin:0 0 10px;color:var(--text-2);font-size:13px">Estimasi dalam ${esc(predicted.timeframe_days ?? "90")} hari jika rekomendasi di atas diterapkan secara konsisten.</p>
    <p style="margin:0;color:var(--text-3);font-size:11px">${esc(predicted.note || "")}</p></div>
  </div>`;
}

async function runInvestorDemoSequence() {
  const panel = el("#investor-demo-stepper-panel");
  const stepperEl = el("#investor-demo-stepper");
  const resultEl = el("#investor-demo-result");
  if (!panel || !stepperEl || !resultEl) return;
  panel.style.display = "block";
  resultEl.innerHTML = "";
  stepperEl.innerHTML = investorDemoStepperHtml(0, 0);
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const demoPromise = api.investorDemo().catch((error) => ({ error: error.message }));
  const pacing = [550, 650, 650, 600];
  for (let i = 0; i < pacing.length; i++) { await sleep(pacing[i]); stepperEl.innerHTML = investorDemoStepperHtml(i + 1, i + 1); }

  const result = await demoPromise;

  const remainingSteps = [4, 5, 6, 7, 8, 9];
  for (const i of remainingSteps) { await sleep(480); stepperEl.innerHTML = investorDemoStepperHtml(i + 1, i + 1); }
  await sleep(300);
  stepperEl.innerHTML = investorDemoStepperHtml(INVESTOR_DEMO_STEPS.length, -1);

  resultEl.innerHTML = renderInvestorDemoResult(result);
}

async function renderSettings() {
  loadingPage(t('settings.title'), t('settings.subtitle'));
  const [integrationResult, ssoResult] = await Promise.all([
    settle("integrations", api.integrations()),
    settle("ssoConfig", api.ssoConfig()),
  ]);
  state.integrations = integrationResult.ok ? integrationResult.data : {};
  const gmail = state.integrations?.gmail || {};
  const gmailConnected = !!gmail.connected;
  const ssoData = ssoResult.ok ? ssoResult.data : { configured: false, config: null, sso_enabled: true };

  // ── Section: Workspace Identity ─────────────────────────────────────────
  const workspaceSection = settingSection(
    t('settings.workspace_title'), t('settings.workspace_desc'),
    readonlyField(t('settings.org_name'), state.org?.name || '') +
    readonlyField(t('settings.slug'), state.org?.slug || '') +
    readonlyField(t('settings.url'), location.origin)
  );

  // ── Section: System Status ──────────────────────────────────────────────
  const systemSection = settingSection(
    t('settings.system_title'), t('settings.system_desc'),
    settingRow(t('settings.backend'), t('settings.backend_desc'), statusBadge(state.health?.db ? 'active' : 'error', state.health?.db ? 'Connected' : 'Unavailable')) +
    settingRow(t('settings.postgres'), t('settings.postgres_desc'), statusBadge(state.health?.schema ? 'active' : 'error', state.health?.schema ? 'Schema ready' : 'Schema issue')) +
    settingRow(t('settings.ai_provider'), `${t('settings.ai_provider_desc')} · ${esc(state.health?.ai?.model || 'Not configured')}`, statusBadge(state.health?.ai?.configured ? 'active' : 'error', state.health?.ai?.configured ? 'Ready' : 'Not configured'))
  );

  // ── Section: Integrations ───────────────────────────────────────────────
  const gmailActions = `<div style="display:flex;gap:8px;flex-wrap:wrap">
    <button class="button button-primary button-sm" data-action="gmail-start">${gmailConnected ? t('settings.reconnect_gmail') : t('settings.connect_gmail')}</button>
    ${gmailConnected ? `<button class="button button-sm" data-action="gmail-map">${t('settings.map_agent')}</button><button class="button button-sm" data-action="gmail-poll">${t('settings.poll_now')}</button><button class="button button-danger button-sm" data-disconnect-integration="gmail">${t('settings.disconnect')}</button>` : ''}
  </div>`;
  const integrationsSection = `<section class="settings-section">
    <div class="settings-section-head"><h3>${t('settings.integrations_title')}</h3><p>${t('settings.integrations_desc')}</p></div>
    <div class="setting-row">
      <div class="setting-row-left"><strong>${t('settings.gmail_title')}</strong><p>${esc(gmail.email || t('settings.gmail_disconnected'))}</p></div>
      <div class="setting-row-control">${statusBadge(gmailConnected ? 'active' : 'inactive', gmailConnected ? t('settings.gmail_connected') : t('settings.gmail_disconnected'))}</div>
    </div>
    <div style="padding:14px 18px">${gmailActions}</div>
  </section>`;

  // ── Section: SSO Enterprise (OIDC) ──────────────────────────────────────
  const ssoConf = ssoData.config || {};
  const ssoConfigured = !!ssoData.configured;
  const ssoSlug = state.org?.slug || '';
  const callbackUrl = `${location.origin}/auth/sso/callback`;
  const loginUrl = ssoSlug ? `${location.origin}/auth/sso/${ssoSlug}/login` : '';
  const ssoSection = ssoData.sso_enabled === false
    ? settingSection(t('settings.sso_title'), t('settings.sso_desc'),
        `<div class="setting-row"><div class="setting-row-left"><p>${t('settings.sso_platform_off')}</p></div></div>`)
    : `<section class="settings-section">
      <div class="settings-section-head"><h3>${t('settings.sso_title')}</h3><p>${t('settings.sso_desc')}</p></div>
      <div style="padding:14px 18px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          ${statusBadge(ssoConfigured && ssoConf.enabled ? 'active' : 'inactive', ssoConfigured && ssoConf.enabled ? t('settings.sso_active') : t('settings.sso_inactive'))}
          ${ssoConfigured ? `<span class="subtle" style="font-size:11px">${esc(ssoConf.issuer || '')}</span>` : ''}
        </div>
        <div style="background:var(--surface-2,#111);border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:11px;color:var(--text-2)">
          <div style="margin-bottom:4px">${t('settings.sso_callback_hint')}</div>
          <code style="font-size:11px;word-break:break-all;color:var(--text)">${esc(callbackUrl)}</code>
          ${loginUrl ? `<div style="margin-top:8px">${t('settings.sso_login_url')}</div><code style="font-size:11px;word-break:break-all;color:var(--text)">${esc(loginUrl)}</code>` : ''}
        </div>
        <form id="sso-config-form" class="auth-form" style="gap:10px">
          <label>${t('settings.sso_issuer')}<input name="issuer" value="${esc(ssoConf.issuer || '')}" placeholder="https://idp.example.com" required></label>
          <label>${t('settings.sso_client_id')}<input name="client_id" value="${esc(ssoConf.client_id || '')}" required></label>
          <label>${t('settings.sso_client_secret')}<input name="client_secret" type="password" placeholder="${ssoConf.has_secret ? '••••••• ('+t('settings.sso_secret_keep')+')' : ''}"></label>
          <label>${t('settings.sso_domains')}<input name="allowed_domains" value="${esc((ssoConf.allowed_domains||[]).join(', '))}" placeholder="example.com, corp.example.com"></label>
          <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">
            <label style="flex-direction:row;align-items:center;gap:6px;font-size:13px"><input type="checkbox" name="jit_enabled" ${ssoConf.jit_enabled!==false?'checked':''} style="width:auto"> ${t('settings.sso_jit')}</label>
            <label style="flex-direction:row;align-items:center;gap:6px;font-size:13px">${t('settings.sso_default_role')}
              <select name="default_role" style="width:auto"><option value="member" ${ssoConf.default_role!=='admin'?'selected':''}>member</option><option value="admin" ${ssoConf.default_role==='admin'?'selected':''}>admin</option></select></label>
            <label style="flex-direction:row;align-items:center;gap:6px;font-size:13px"><input type="checkbox" name="enabled" ${ssoConf.enabled?'checked':''} style="width:auto"> ${t('settings.sso_enable')}</label>
          </div>
          <p class="form-error" data-form-error></p>
          <div style="display:flex;gap:8px">
            <button class="button button-primary button-sm" type="submit">${t('settings.sso_save')}</button>
            ${ssoConfigured ? `<button class="button button-danger button-sm" type="button" data-action="sso-delete">${t('settings.sso_delete')}</button>` : ''}
          </div>
        </form>
      </div>
    </section>`;

  // ── Section: Appearance & Language ──────────────────────────────────────
  const appearanceSection = settingSection(
    t('settings.appearance_title'), t('settings.appearance_desc'),
    settingRow(
      t('settings.language'), t('settings.language_desc'),
      `<div class="lang-switcher"><button class="${getLang() === 'id' ? 'active' : ''}" data-set-lang="id">ID · Bahasa</button><button class="${getLang() === 'en' ? 'active' : ''}" data-set-lang="en">EN · English</button></div>`
    )
  );

  // ── Section: Session & Security ─────────────────────────────────────────
  const sessionSection = settingSection(
    t('settings.session_title'), t('settings.session_desc'),
    settingRow(t('settings.signout'), t('settings.signout_desc'), `<button class="button button-danger button-sm" data-action="logout">${t('signout')}</button>`)
  );

  // ── Sidebar nav ─────────────────────────────────────────────────────────
  const navItems = [
    ['workspace', t('settings.workspace_title'), 'settings'],
    ['system', t('settings.system_title'), 'observability'],
    ['integrations', t('settings.integrations_title'), 'channels'],
    ['sso', t('settings.sso_title'), 'security'],
    ['appearance', t('settings.appearance_title'), 'about'],
    ['session', t('settings.session_title'), 'security'],
  ].map(([key, label, ico]) =>
    `<button class="settings-nav-item" data-settings-section="${key}">${icon(ico, 14)}<span>${label}</span></button>`
  ).join('');

  setPage(`${pageHeader(t('settings.title'), t('settings.subtitle'), `<button class="button button-sm" data-action="security-scan">${icon('refresh', 13)} ${t('settings.security_scan')}</button>`)}
  <div class="settings-layout">
    <aside class="settings-sidebar">
      <nav class="settings-nav">
        <div class="settings-search-wrap">${icon('search', 14)}<input placeholder="${t('settings.search')}" data-settings-search></div>
        ${navItems}
      </nav>
    </aside>
    <div class="settings-content" id="settings-content">
      ${workspaceSection}
      ${systemSection}
      ${integrationsSection}
      ${ssoSection}
      ${appearanceSection}
      ${sessionSection}
    </div>
  </div>`);

  // Settings search filter
  const searchInput = el('[data-settings-search]');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const query = searchInput.value.toLowerCase();
      els('.settings-section').forEach((sec) => {
        sec.hidden = query.length > 0 && !sec.textContent.toLowerCase().includes(query);
      });
    });
  }
}

// ─── WhatsApp Embedded Signup (Meta) ────────────────────────────

function loadFacebookSdk(appId, version) {
  return new Promise((resolve, reject) => {
    if (window.FB) { window.FB.init({ appId, version, xfbml: false }); return resolve(); }
    window.fbAsyncInit = () => { window.FB.init({ appId, version, xfbml: false }); resolve(); };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.onerror = () => reject(new Error("Failed to load Facebook SDK."));
    document.body.appendChild(script);
  });
}

function waitForEmbeddedSignupMessage() {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { window.removeEventListener("message", handler); reject(new Error("Timed out waiting for WhatsApp signup data.")); }, 120000);
    function handler(event) {
      if (!String(event.origin || "").includes("facebook.com")) return;
      let payload = event.data;
      try { payload = typeof payload === "string" ? JSON.parse(payload) : payload; } catch (_e) { return; }
      if (payload?.type === "WA_EMBEDDED_SIGNUP" && payload?.event === "FINISH") {
        clearTimeout(timeout);
        window.removeEventListener("message", handler);
        resolve(payload.data || {});
      }
    }
    window.addEventListener("message", handler);
  });
}

async function connectWhatsAppEmbedded(botId = state.selectedBotId) {
  if (!botId) return toast("Create an AI agent first.", "error");
  try {
    const config = await api.whatsappEmbeddedConnect(botId);
    await loadFacebookSdk(config.app_id, config.graph_api_version);
    const fbResponse = await new Promise((resolve) => {
      window.FB.login((response) => resolve(response), {
        config_id: config.config_id,
        response_type: "code",
        override_default_response_type: true,
        extras: { setup: {}, sessionInfoVersion: "3" },
      });
    });
    if (!fbResponse?.authResponse?.code) return toast("WhatsApp connection was cancelled.", "error");
    const signupData = await waitForEmbeddedSignupMessage();
    await api.whatsappEmbeddedCallback({
      state: config.state,
      code: fbResponse.authResponse.code,
      waba_id: signupData.waba_id,
      phone_number_id: signupData.phone_number_id,
      business_id: signupData.business_id,
    });
    toast("WhatsApp connected successfully.", "success");
    await renderChannels();
  } catch (error) { toast(error.message, "error"); }
}

async function disconnectWhatsAppEmbedded(botId = state.selectedBotId) {
  if (!botId || !confirm("Disconnect WhatsApp for this agent?")) return;
  try { await api.whatsappEmbeddedDisconnect(botId); toast("WhatsApp disconnected.", "success"); await renderChannels(); }
  catch (error) { toast(error.message, "error"); }
}

function settingRowStyles() { /* styles now in styles.css */ }

function showInviteMember() {
  const roleOptions = (state.roles.length ? state.roles : [{key:"admin",name:"Admin"},{key:"manager",name:"Manager"},{key:"agent",name:"Agent"},{key:"viewer",name:"Viewer"}])
    .filter((role) => role.key !== "owner").map((role) => `<option value="${esc(role.key)}">${esc(role.name || role.key)}</option>`).join("");
  el("#modal-root").innerHTML = modal({title:"Add workspace member",body:`<form id="invite-member-form"><div class="form-grid"><label class="field"><span>Full name</span><input name="full_name" required></label><label class="field"><span>Role</span><select name="role_key">${roleOptions}</select></label><label class="field full"><span>Email</span><input type="email" name="email" required></label><label class="field full"><span>Temporary password</span><input type="password" name="password" minlength="8" required></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-invite-member">Add member</button>`});
}

async function submitInviteMember() {
  const form=el("#invite-member-form"); if(!form || !form.reportValidity()) return;
  const button=el("[data-action=submit-invite-member]"); button.disabled=true;
  try { await api.inviteMember(Object.fromEntries(new FormData(form))); bustCache("team"); el("#modal-root").innerHTML=""; toast("Team member added.","success"); await renderTeam(); renderChrome(); }
  catch(error){ toast(error.message,"error"); button.disabled=false; }
}

function showMemberRole(userId) {
  const member=state.team.find((item)=>String(item.id)===String(userId)); if(!member)return;
  const currentRoles=member.roles||[];
  const rolesList=currentRoles.length
    ? `<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px">${currentRoles.map((roleKey)=>{
        const roleInfo=state.roles.find((role)=>role.key===roleKey);
        return `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px"><span class="status-badge ready">${esc(roleInfo?.name||roleKey)}</span><button type="button" class="button button-danger" data-revoke-member-role="${esc(roleKey)}" data-user-id="${esc(member.id)}">Hapus</button></div>`;
      }).join("")}</div>`
    : `<p class="subtle" style="font-size:11px">Anggota ini belum punya role.</p>`;
  const assignableRoles=state.roles.filter((role)=>!currentRoles.includes(role.key));
  const addForm=assignableRoles.length
    ? `<form id="member-role-form" data-user-id="${esc(member.id)}"><label class="field"><span>Add role</span><select name="role_key">${assignableRoles.map((role)=>`<option value="${esc(role.key)}">${esc(role.name||role.key)}</option>`).join("")}</select></label></form>`
    : `<p class="subtle" style="font-size:11px">Semua role sudah ditugaskan ke anggota ini.</p>`;
  el("#modal-root").innerHTML=modal({title:`Manage access - ${member.full_name||member.email}`,body:`<div><span class="eyebrow">CURRENT ROLES</span>${rolesList}</div>${addForm}`,footer:`<button class="button" data-action="close-modal">Cancel</button>${assignableRoles.length?`<button class="button button-primary" data-action="submit-member-role">Assign role</button>`:''}`});
}

async function submitMemberRole() {
  const form=el("#member-role-form"); if(!form)return; const role=form.elements.role_key.value;
  try { await api.assignRole(form.dataset.userId,role); el("#modal-root").innerHTML=""; toast("Member role updated.","success"); await renderTeam(); }
  catch(error){ toast(error.message,"error"); }
}

function exportTeam() {
  const lines=[["name","email","roles","active"],...state.team.map((m)=>[m.full_name||"",m.email,(m.roles||[]).join("|"),m.is_active])];
  const csv=lines.map((row)=>row.map((value)=>`"${String(value).replace(/"/g,'""')}"`).join(",")).join("\n");
  const link=document.createElement("a"); link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"})); link.download="botnesia-team.csv"; link.click(); URL.revokeObjectURL(link.href);
}

function showConnectChannel(preselected = "website") {
  const bots=state.bots.map((bot)=>`<option value="${esc(bot.id)}">${esc(bot.name)}</option>`).join("");
  const options=[["telegram","Telegram"],["website","Website Chat"]].map(([value,label])=>`<option value="${value}" ${value===preselected?'selected':''}>${label}</option>`).join("");
  el("#modal-root").innerHTML=modal({title:t('modal.channel.title'),body:`<form id="connect-channel-form"><div class="form-grid"><label class="field"><span>${t('modal.channel.agent')}</span><select name="bot_id">${bots}</select></label><label class="field"><span>${t('modal.channel.channel')}</span><select name="channel_type">${options}</select></label><label class="field full"><span>${t('modal.channel.display')}</span><input name="display_name" required placeholder="${t('modal.channel.display_ph')}"></label><label class="field full"><span>${t('modal.channel.domain')}</span><input name="domain" placeholder="${t('modal.channel.domain_ph')}"></label><p class="subtle full">${t('modal.channel.note')}</p></div></form>`,footer:`<button class="button" data-action="close-modal">${t('cancel')}</button><button class="button button-primary" data-action="submit-connect-channel">${t('modal.channel.connect')}</button>`});
}

async function showMetaConnect(channel) {
  if (!state.bots.length) return toast("Buat AI agent terlebih dahulu.", "error");
  if (!(state.metaOAuth?.pages || []).length) {
    const botId = state.selectedBotId || state.bots[0].id;
    try {
      const result = await api.metaOAuthStart(botId, channel);
      if (channel === "instagram") {
        state.pendingMetaAuthUrl = result.auth_url;
        el("#modal-root").innerHTML = modal({
          title: "Login lewat Facebook",
          body: `<p class="subtle">Instagram Messaging API tidak punya login sendiri dari Meta — akses ke pesan Instagram Business harus lewat <strong>Facebook Login</strong>, karena akun Instagram Business Anda perlu tertaut ke sebuah Facebook Page. Ini aturan resmi dari Meta, bukan kekurangan BotNesia.</p><p class="subtle" style="margin-top:10px">Setelah login, Anda akan diminta memilih akun Instagram Business yang ingin dihubungkan ke agent ini.</p>`,
          footer: `<button class="button" data-action="close-modal">Batal</button><button class="button button-primary" data-action="confirm-meta-redirect">Lanjutkan ke Facebook</button>`,
        });
        return;
      }
      location.href = result.auth_url;
    } catch (error) { toast(error.message,"error"); }
    return;
  }
  showMetaAssetSelection(channel);
}

function showMetaAssetSelection(channel) {
  const pages = state.metaOAuth?.pages || [];
  const usable = channel === "instagram" ? pages.filter((page)=>page.instagram?.id) : pages;
  if (!usable.length) return toast(channel === "instagram" ? "Tidak ada akun Instagram Business yang tertaut ke Facebook Page Anda." : "Tidak ada Facebook Page yang tersedia.", "error");
  const bots = state.bots.map((bot)=>`<option value="${esc(bot.id)}">${esc(bot.name)}</option>`).join("");
  const assets = usable.map((page)=>`<option value="${esc(page.id)}" data-instagram-id="${esc(page.instagram?.id||'')}">${esc(channel==='instagram' ? `${page.instagram?.username || 'Instagram'} - ${page.name}` : page.name)}</option>`).join("");
  const helpText = channel === "instagram"
    ? "Page ditampilkan karena Instagram Business API mengharuskan akun Instagram tertaut ke Facebook Page (aturan Meta). Token disimpan terenkripsi per tenant."
    : "Login dilakukan melalui OAuth resmi Meta. Token disimpan terenkripsi per tenant.";
  el("#modal-root").innerHTML=modal({title:`Hubungkan ${channel==='instagram'?'Instagram Business':'Facebook Page'}`,body:`<form id="meta-asset-form" data-channel="${channel}"><div class="form-grid"><label class="field"><span>Agent</span><select name="bot_id">${bots}</select></label><label class="field"><span>${channel==='instagram'?'Akun Instagram Business':'Facebook Page'}</span><select name="page_id">${assets}</select></label></div><p class="subtle" style="margin-top:12px">${helpText}</p></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-meta-asset">Hubungkan</button>`});
}

async function submitMetaAssetSelection() {
  const form=el("#meta-asset-form"); if(!form)return;
  const channel=form.dataset.channel;
  const option=form.elements.page_id.selectedOptions[0];
  const body={bot_id:form.elements.bot_id.value,page_id:form.elements.page_id.value,channels:[channel]};
  if(channel==="instagram") body.instagram_id=option.dataset.instagramId;
  try { await api.metaOAuthSelect(body); el("#modal-root").innerHTML=""; toast(`${channel==='instagram'?'Instagram':'Facebook'} connected.`,"success"); await renderChannels(); }
  catch(error){ toast(error.message,"error"); }
}

function showWhatsAppConnect() {
  if (!state.bots.length) return toast("Create an AI agent first.", "error");
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}">${esc(bot.name)}</option>`).join("");
  el("#modal-root").innerHTML = modal({title:"Connect WhatsApp",body:`<form id="connect-whatsapp-form"><label class="field"><span>Route WhatsApp to agent</span><select name="bot_id">${options}</select></label><p class="subtle" style="margin-top:12px">You will sign in to Meta, choose the WhatsApp Business account and phone number, then BotNesia stores the connection securely. Users do not need to paste an access token.</p></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-connect-whatsapp">Continue with Meta</button>`});
}

async function submitWhatsAppConnect() {
  const form = el("#connect-whatsapp-form");
  if (!form) return;
  const botId = form.elements.bot_id.value;
  el("#modal-root").innerHTML = "";
  await connectWhatsAppEmbedded(botId);
}

async function submitConnectChannel() {
  const form=el("#connect-channel-form"); if(!form || !form.reportValidity())return; const data=Object.fromEntries(new FormData(form));
  const domain=data.domain; delete data.domain;
  data.credentials={}; data.config=domain?{domain}:{};
  try { const result=await api.connectChannel(data); el("#modal-root").innerHTML=""; toast("Channel connected.","success"); if(state.route==="channels") await renderChannels(); else await renderSettings(); if(data.channel_type==="website") showWidgetSnippet(result.channel); } catch(error){ toast(error.message,"error"); }
}

function showWidgetSnippet(channel) {
  const snippet=`<script src="${location.origin}/botnesia-widget.js" data-connection-id="${channel.id}"></script>\n<div id="botnesia-chat"></div>`;
  el("#modal-root").innerHTML=modal({title:"Website Chat ready",body:`<p class="subtle">Embed this snippet before the closing body tag.</p><label class="field"><span>Embed code</span><textarea readonly style="min-height:110px" onclick="this.select()">${esc(snippet)}</textarea></label>`,footer:`<button class="button button-primary" data-action="close-modal">Done</button>`});
}

async function startGmail() { try{const result=await api.gmailStart(); location.href=result.auth_url;}catch(error){toast(error.message,"error");} }
async function mapGmail() { const botId=state.selectedBotId||state.bots[0]?.id; if(!botId)return toast("Create an agent first.","error"); try{await api.gmailMapBot(botId); toast("Gmail mapped to selected agent.","success"); await renderSettings();}catch(error){toast(error.message,"error");} }
async function pollGmail() { try{const result=await api.gmailPoll(); toast(`Gmail poll complete: ${result.processed||0} messages.`,"success");}catch(error){toast(error.message,"error");} }
async function showNotifications(){const [queue,audit]=await Promise.all([settle("queue",api.handoffQueue({limit:5})),settle("audit",api.auditLogs({limit:8}))]);const q=queue.ok?(queue.data.queue||[]):[];const logs=audit.ok?(audit.data.logs||[]):[];const body=`<h4>Human handoff</h4>${q.length?q.map((item)=>`<div class="setting-row"><span>${esc(item.reason||'Escalated conversation')}</span>${statusBadge(item.status||'waiting')}</div>`).join(""):"<p class=subtle>No pending handoff.</p>"}<h4 style="margin-top:20px">Recent audit</h4>${logs.length?logs.map((item)=>`<div class="setting-row"><span>${esc(item.action)} - ${esc(item.resource_type)}</span><span class="subtle">${relativeTime(item.created_at)}</span></div>`).join(""):"<p class=subtle>No recent audit events.</p>"}`;el("#modal-root").innerHTML=modal({title:"Notifications",body,wide:true});}

function showMarketplaceInstall(templateKey) {
  const template = state.marketplace?.templates?.find((item) => item.key === templateKey);
  if (!template) return toast("Template tidak ditemukan.", "error");
  el("#modal-root").innerHTML = modal({title:`Install ${template.name}`,body:`<form id="marketplace-install-form" data-template-key="${esc(template.key)}"><div class="form-grid"><label class="field full"><span>Agent name</span><input name="bot_name" value="${esc(`${template.name} (Marketplace)`)}" required></label><div class="field full"><span>Template</span><div class="status-badge active">${esc(template.category)} · v${esc(template.version || '1.0.0')}</div></div><label class="field full"><span>Description</span><textarea readonly style="min-height:100px">${esc(template.description)}</textarea></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-marketplace-install">Install agent</button>`});
}

async function submitMarketplaceInstall() {
  const form = el("#marketplace-install-form");
  if (!form || !form.reportValidity()) return;
  const botName = form.elements.bot_name?.value?.trim() || null;
  const templateKey = form.dataset.templateKey;
  const button = el('[data-action="submit-marketplace-install"]');
  if (button) { button.disabled = true; button.textContent = "Installing..."; }
  try {
    const res = await api.installMarketplaceTemplate(templateKey, botName);
    // Template berbayar: arahkan ke pembayaran; bot dibuat setelah lunas.
    if (res && res.requires_payment && res.redirect_url) {
      el("#modal-root").innerHTML = "";
      toast("Mengarahkan ke pembayaran…", "success");
      location.href = res.redirect_url;
      return;
    }
    el("#modal-root").innerHTML = "";
    toast(res && res.paid ? "Template berbayar dibeli & terpasang." : "Agent marketplace installed.", "success");
    await renderMarketplace();
    await loadCore();
  } catch (error) {
    toast(error.message, "error");
    if (button) { button.disabled = false; button.textContent = "Install agent"; }
  }
}

// ── Publisher: buat/edit/publish template sendiri ──
function showTemplateEditor(key) {
  const existing = key ? (state.marketplace?.myTemplates || []).find((t) => t.key === key) : null;
  const cats = state.marketplace?.categories || [];
  const v = (x) => esc(x == null ? "" : String(x));
  el("#modal-root").innerHTML = modal({
    title: existing ? `Edit template — ${existing.name}` : "Buat template agent",
    wide: true,
    body: `<form id="mkt-template-form" ${existing ? `data-edit-key="${esc(existing.key)}"` : ""}>
      <div class="form-grid">
        <label class="field"><span>Nama</span><input name="name" required value="${v(existing?.name)}" placeholder="Agen Toko Kopi"></label>
        <label class="field"><span>Kategori</span><input name="category" required list="mkt-cats" value="${v(existing?.category)}" placeholder="Ecommerce"></label>
        <datalist id="mkt-cats">${cats.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
        <label class="field full"><span>Deskripsi</span><textarea name="description" style="min-height:60px" placeholder="Deskripsi singkat template">${v(existing?.description)}</textarea></label>
        <label class="field full"><span>Greeting</span><textarea name="greeting" style="min-height:60px" placeholder="Halo, ada yang bisa saya bantu?">${v(existing?.greeting)}</textarea></label>
        <label class="field full"><span>System prompt</span><textarea name="system_prompt" required style="min-height:130px" placeholder="Kamu adalah asisten...">${v(existing?.system_prompt)}</textarea></label>
        <label class="field"><span>Harga (Rp, 0 = gratis)</span><input name="price_idr" type="number" min="0" value="${existing?.price_idr || 0}"></label>
      </div>
      <p class="subtle" style="font-size:11px;margin-top:8px">Template berbayar: pembagian pendapatan 70% publisher (penagihan & payout menyusul). Setelah dibuat, klik <b>Publish</b> agar tampil di marketplace.</p>
    </form>`,
    footer: `<button class="button" data-action="close-modal">Batal</button><button class="button button-primary" data-action="submit-mkt-template">${existing ? "Simpan" : "Buat template"}</button>`,
  });
}

async function submitTemplateEditor() {
  const form = el("#mkt-template-form");
  if (!form || !form.reportValidity()) return;
  const raw = Object.fromEntries(new FormData(form));
  const data = {
    name: raw.name?.trim(), category: raw.category?.trim(),
    system_prompt: raw.system_prompt?.trim(), description: raw.description?.trim() || "",
    greeting: raw.greeting?.trim() || null, price_idr: Number(raw.price_idr || 0),
  };
  const editKey = form.dataset.editKey;
  const button = el('[data-action="submit-mkt-template"]');
  if (button) { button.disabled = true; button.textContent = "Menyimpan..."; }
  try {
    if (editKey) await api.updateMarketplaceTemplate(editKey, data);
    else await api.createMarketplaceTemplate(data);
    el("#modal-root").innerHTML = "";
    toast(editKey ? "Template diperbarui." : "Template dibuat (draft). Klik Publish untuk menayangkan.", "success");
    await renderMarketplace();
  } catch (error) {
    toast(error.message, "error");
    if (button) { button.disabled = false; button.textContent = editKey ? "Simpan" : "Buat template"; }
  }
}

async function marketplacePublish(key, publish) {
  try {
    if (publish) await api.publishMarketplaceTemplate(key);
    else await api.unpublishMarketplaceTemplate(key);
    toast(publish ? "Template dipublish ke marketplace." : "Template di-unpublish (kembali draft).", "success");
    await renderMarketplace();
  } catch (error) { toast(error.message, "error"); }
}

// Event "MarketplaceUninstalled": setelah backend menghapus bot+relasi secara
// atomik, sinkronkan SEMUA view yang menurunkan data dari agent/bot supaya tak
// ada data basi (agent yang sudah dihapus muncul di Pusat Agent / AI Workforce).
async function onMarketplaceUninstalled() {
  bustCache();               // bersihkan seluruh cache (workforce/dashboard/analytics/marketplace/agent-center)
  await loadCore();          // reload state.bots → halaman agents/AI Workforce + counter + subscription
  try { renderChrome(); } catch (_) {}   // sidebar + agent counter
  await renderMarketplace();  // katalog + Template Saya
  // Re-render halaman aktif jika sedang di view yang menampilkan agent.
  const r = state.route;
  try {
    if (r === "agents" && typeof renderAgents === "function") await renderAgents();
    else if ((r === "workforce" || r === "workforce-overview") && typeof route === "function") await route();
    else if (r === "dashboard" && typeof route === "function") await route();
  } catch (_) {}
}

function showCreateAgent() {
  el("#modal-root").innerHTML = modal({title:t('modal.agent.title'),body:`<form id="create-agent-form"><div class="form-grid"><label class="field"><span>${t('modal.agent.name')}</span><input name="name" required placeholder="${t('modal.agent.name_ph')}"></label><label class="field"><span>${t('modal.agent.language')}</span><select name="language"><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></label><label class="field full"><span>${t('agent.field.greeting')}</span><textarea name="greeting" style="min-height:80px" placeholder="Halo! Ada yang bisa saya bantu?"></textarea></label><label class="field full"><span>${t('agent.field.prompt')}</span><textarea name="system_prompt" placeholder="You are a professional customer success agent..."></textarea></label></div></form>`,footer:`<button class="button" data-action="close-modal">${t('cancel')}</button><button class="button button-primary" data-action="submit-create-agent">${t('modal.agent.deploy')}</button>`});
}

function showAgent(id) {
  const bot = state.bots.find((item) => item.id === id); if (!bot) return;
  const drawer = el("#detail-drawer"); drawer.innerHTML = agentDrawer(bot); drawer.classList.add("open"); drawer.setAttribute("aria-hidden","false");
}

function closeDrawer() { const drawer=el("#detail-drawer"); drawer.classList.remove("open"); drawer.setAttribute("aria-hidden","true"); }

function voiceStatus(container, message) {
  const status = container?.querySelector?.("[data-voice-status]");
  if (status) status.textContent = message;
}

async function stopSpeaking(container = document) {
  state.speechRunId += 1;
  window.speechSynthesis?.cancel();
  for (const source of state.speechSources) {
    try { source.stop(); } catch {}
  }
  state.speechSources.clear();
  if (state.speechAudio) {
    state.speechAudio.pause();
    state.speechAudio.src = "";
    state.speechAudio = null;
  }
  try { await api.stopSpeech(); } catch {}
  voiceStatus(container, "Suara dihentikan");
}

async function speechContext() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) throw new Error("Browser tidak mendukung audio buffering.");
  if (!state.speechContext) state.speechContext = new AudioContext({ latencyHint: "interactive" });
  if (state.speechContext.state === "suspended") await state.speechContext.resume();
  return state.speechContext;
}

async function decodeSpeechBlob(blob) {
  const context = await speechContext();
  return context.decodeAudioData(await blob.arrayBuffer());
}

function scheduleSpeechBuffer(buffer, runId, startAt) {
  const context = state.speechContext;
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  state.speechSources.add(source);
  const ended = new Promise((resolve) => {
    source.onended = () => {
      state.speechSources.delete(source);
      resolve();
    };
  });
  if (runId === state.speechRunId) source.start(startAt);
  return { ended, endAt: startAt + buffer.duration };
}

async function prepareSpeech(text, container = document) {
  if (!state.speakReplies) return null;
  const chunks = bufferSpeechSentences(text);
  if (!chunks.length) return null;
  voiceStatus(container, "Menyinkronkan tulisan dan suara...");
  const prefetchedBuffers = chunks.slice(0, 2).map((chunk) => api.synthesizeSpeech(chunk).then(decodeSpeechBlob));
  const firstBuffer = await prefetchedBuffers[0];
  return { chunks, firstBuffer, prefetchedBuffers };
}

async function speak(text, container = document, prepared = null) {
  if (!state.speakReplies) return;
  const chunks = prepared?.chunks || bufferSpeechSentences(text);
  if (!chunks.length) return;

  const runId = ++state.speechRunId;
  window.speechSynthesis?.cancel();
  if (state.speechAudio) state.speechAudio.pause();
  const context = await speechContext();
  const audioJobs = new Array(chunks.length);
  const ensureAudioJob = (index) => {
    if (index >= chunks.length) return null;
    if (!audioJobs[index]) {
      audioJobs[index] = prepared?.prefetchedBuffers?.[index]
        || (index === 0 && prepared?.firstBuffer
          ? Promise.resolve(prepared.firstBuffer)
          : api.synthesizeSpeech(chunks[index]).then(decodeSpeechBlob));
    }
    return audioJobs[index];
  };

  let nextStartAt = context.currentTime + 0.03;
  let finalEnded = Promise.resolve();
  ensureAudioJob(0);
  ensureAudioJob(1);
  for (let index = 0; index < chunks.length && runId === state.speechRunId; index += 1) {
    voiceStatus(container, `Gadis Neural membaca ${index + 1}/${chunks.length}...`);
    const buffer = await ensureAudioJob(index);
    if (runId !== state.speechRunId) break;
    const startAt = Math.max(nextStartAt, context.currentTime + 0.015);
    const scheduled = scheduleSpeechBuffer(buffer, runId, startAt);
    finalEnded = scheduled.ended;
    nextStartAt = scheduled.endAt + (segmentPauseMs(chunks[index]) / 1000);
    ensureAudioJob(index + 1);
    ensureAudioJob(index + 2);
  }
  await finalEnded;
  if (runId === state.speechRunId) voiceStatus(container, "Selesai membaca sampai akhir");
}

async function toggleRecording(button) {
  const container = button?.closest(".chat-page") || document;
  const form = button?.closest("form");
  const status = container.querySelector("[data-voice-status]");
  if (state.recorder?.state === "recording") { state.recorder.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast("Browser ini tidak mendukung perekaman mikrofon.","error"); return; }
  try {
    state.recordingStream = await navigator.mediaDevices.getUserMedia({audio:true});
    state.recordingChunks = []; state.recorder = new MediaRecorder(state.recordingStream);
    state.recorder.ondataavailable = (event) => { if (event.data.size) state.recordingChunks.push(event.data); };
    state.recorder.onstop = async () => {
      button?.classList.remove("recording"); if(status) status.textContent="Transcribing voice...";
      state.recordingStream?.getTracks().forEach((track)=>track.stop());
      try {
        const type = state.recorder.mimeType || "audio/webm";
        const result = await api.transcribeAudio(new Blob(state.recordingChunks,{type}), type.includes("ogg")?"recording.ogg":"recording.webm");
        const input = form?.querySelector('textarea[name="message"]'); if(input) input.value=result.text;
        if(status) status.textContent="Transcription ready · review and send";
      } catch(error) { if(status) status.textContent="Mic ready"; toast(error.message,"error"); }
    };
    state.recorder.start(); button.classList.add("recording"); if(status) status.textContent="Recording... tap mic to stop";
  } catch(error) { toast(error.name==="NotAllowedError"?"Izin mikrofon ditolak. Aktifkan izin mic pada browser.":error.message,"error"); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Casper Agentic Workflow — Buildathon 2026
// ─────────────────────────────────────────────────────────────────────────────
function casperStatusBadge(status) {
  const cfg = {
    confirmed: ['active', '✓ On-Chain'],
    pending:   ['warning', '⏳ Pending'],
    failed:    ['error', '✕ Failed'],
    demo:      ['info', '◎ Demo Mode'],
  };
  const [cls, label] = cfg[status] || ['', status];
  return `<span class="status-badge ${cls}" style="font-size:11px">${label}</span>`;
}

function casperActionCard(a) {
  const typeColors = {hire:'#51426b',price_change:'#7a334b',marketing:'#825f2b',finance:'#466847',sales:'#4a4a4a',hr:'#6a3b72',operations:'#555555',security:'#7e3530',customer_support:'#606060',general:'#6e6e6e'};
  const color = typeColors[a.action_type] || '#6e6e6e';
  const hash = a.deploy_hash ? `<code style="font-size:10px;word-break:break-all;color:var(--text-2)">${a.deploy_hash.startsWith('demo-') ? a.deploy_hash.slice(0,28)+'…(demo)' : a.deploy_hash.slice(0,32)+'…'}</code>` : '<span style="color:var(--text-3);font-size:11px">—</span>';
  const explorerLink = a.explorer_url && !a.deploy_hash?.startsWith('demo-')
    ? `<a href="${esc(a.explorer_url)}" target="_blank" rel="noopener" style="font-size:11px;color:#3d6791">View on cspr.live ↗</a>`
    : '';
  return `<article class="card casper-action-card" data-action-id="${esc(a.action_id)}" style="border-left:3px solid ${color};cursor:pointer">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px">
      <span style="background:${color}44;color:var(--text);font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.5px">${esc(a.action_type.replace('_',' '))}</span>
      ${casperStatusBadge(a.casper_status)}
    </div>
    <p style="margin:0 0 8px;font-size:13px;font-weight:600;line-height:1.4">${esc(a.action_summary.slice(0,140))}${a.action_summary.length>140?'…':''}</p>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
      <div style="flex:1">${hash}${explorerLink ? `<br>${explorerLink}` : ''}</div>
      <time style="font-size:11px;color:var(--text-3);white-space:nowrap">${formatDate(a.created_at,{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}</time>
    </div>
  </article>`;
}

async function renderCasperWorkflow() {
  setPage(`${pageHeader("Casper Agentic Workflow","AI business decisions anchored immutably to Casper Testnet — verifiable, audit-proof, decentralised.",`<button class="button" data-action="casper-demo">One-Click Demo</button><button class="button button-primary" data-action="casper-new-action">+ New Action</button>`)}<div class="skeleton" style="height:80px;margin-bottom:16px"></div>${skeletonCards(4)}`);
  try {
    const [stats, actions, cfg] = await Promise.all([
      api.casperStats().catch(() => ({ total_actions:0, anchored_on_chain:0, pending:0, failed:0, action_types:{} })),
      api.casperActions(20).catch(() => []),
      api.casperConfig().catch(() => null),
    ]);
    const topTypes = Object.entries(stats.action_types || {}).sort(([,a],[,b])=>b-a).slice(0,4).map(([k,v])=>`${k.replace('_',' ')}: <strong>${v}</strong>`).join(' · ') || '—';
    const statsBar = `<div class="grid grid-4" style="margin-bottom:24px">
      ${metricCard('Total Actions',formatNumber(stats.total_actions),'AI decisions recorded','agents')}
      ${metricCard('Anchored On-Chain',formatNumber(stats.anchored_on_chain),'Casper Testnet proofs','security')}
      ${metricCard('Pending',formatNumber(stats.pending),'Awaiting confirmation','observability')}
      ${metricCard('Failed',formatNumber(stats.failed),'Proof errors','costs')}
    </div>`;
    const envBanner = cfg && cfg.env && cfg.env.missing.length
      ? `<div style="margin-bottom:16px;padding:10px 14px;background:#111111;border:1px solid #c99a3e;border-radius:6px;font-size:12px;color:#c99a3e">
           <strong>◎ Demo Mode Active</strong> — missing env vars: <code>${cfg.env.missing.map(m=>m.split(' ')[0]).join(', ')}</code>. Proofs are deterministic hashes (not real Casper transactions). Add vars to .env and restart to enable real mode.
         </div>`
      : (cfg && cfg.real_mode_available
          ? `<div style="margin-bottom:16px;padding:8px 14px;background:#111111;border:1px solid #2e9e73;border-radius:6px;font-size:12px;color:#2e9e73">
               <strong>✓ Real Mode Active</strong> — CASPER_* env vars configured, Casper Testnet transactions enabled.
             </div>`
          : '');
    const contractInfo = `${envBanner}<div class="card" style="margin-bottom:20px;padding:14px 18px;border:1px solid var(--line-strong);background:var(--surface-2)">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div style="flex:1">
          <div style="font-size:11px;font-weight:700;color:var(--text-2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">AI Proof Registry Smart Contract · Casper Testnet</div>
          <code style="font-size:11px;color:var(--text);word-break:break-all">Package: 897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0</code>
        </div>
        <a href="https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0" target="_blank" rel="noopener" class="button" style="font-size:12px;white-space:nowrap">View Contract ↗</a>
      </div>
      <div style="font-size:11px;color:var(--text-3);margin-top:6px">Top action types: ${topTypes}</div>
    </div>`;
    const grid = actions.length
      ? `<div class="page-section-label">Recent AI Actions (${actions.length})</div><div class="grid grid-3" id="casper-actions-grid">${actions.map(casperActionCard).join('')}</div>`
      : `<div class="page-section-label">Recent AI Actions</div>${emptyState('No actions yet','Click "One-Click Demo" to record your first AI business decision on Casper Testnet.',`<button class="button" data-action="casper-demo">One-Click Demo</button>`)}`;
    setPage(`${pageHeader("Casper Agentic Workflow","AI business decisions anchored immutably to Casper Testnet — verifiable, audit-proof, decentralised.",`<button class="button" data-action="casper-demo">One-Click Demo</button><button class="button button-primary" data-action="casper-new-action">+ New Action</button>`)}${statsBar}${contractInfo}${grid}`);
  } catch(error) { setPage(`${pageHeader("Casper Agentic Workflow","AI business decisions anchored to Casper Testnet.")}${errorState(error.message)}`); }
}

function renderCasperNewActionModal() {
  const types = ['general','hire','price_change','marketing','finance','hr','sales','operations','security','customer_support'];
  el("#modal-root").innerHTML = `<div class="modal-overlay" data-dismiss-modal>
    <div class="modal" style="max-width:540px" role="dialog" aria-modal="true">
      <div class="modal-head"><h3>New AI Business Action</h3><button class="icon-button" data-dismiss-modal aria-label="Close">${icon('close',16)}</button></div>
      <form id="casper-action-form" style="padding:20px 24px">
        <label class="form-label" style="display:block;margin-bottom:12px">
          <span>Describe the business scenario or decision</span>
          <textarea name="user_message" class="input" rows="4" placeholder="e.g. Saya perlu merekrut 3 sales executive baru karena pipeline meningkat 200%..." required style="margin-top:6px;width:100%"></textarea>
        </label>
        <label class="form-label" style="display:block;margin-bottom:12px">
          <span>Action type</span>
          <select name="action_type" class="select" style="margin-top:6px;width:100%">
            ${types.map(t=>`<option value="${t}">${t.replace('_',' ')}</option>`).join('')}
          </select>
        </label>
        <label class="form-label" style="display:block;margin-bottom:20px">
          <span>Agent name</span>
          <input name="agent_name" class="input" type="text" value="BotNesia Supervisor" style="margin-top:6px;width:100%">
        </label>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button type="button" class="button" data-dismiss-modal>Cancel</button>
          <button type="submit" class="button button-primary">Anchor to Casper</button>
        </div>
      </form>
    </div>
  </div>`;
  el("#modal-root").querySelector("[data-dismiss-modal]").addEventListener("click", e => { if(e.target.closest(".modal") && !e.target.dataset.dismissModal) return; el("#modal-root").innerHTML=""; });
  el("#casper-action-form").addEventListener("submit", async e => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled=true; btn.textContent="Anchoring…";
    try {
      const result = await api.casperCreateAction(data);
      el("#modal-root").innerHTML="";
      toast(`Action anchored! ${result.casper_status === 'confirmed' ? '✓ On Casper Testnet' : '◎ Demo mode'}`, result.casper_status==='confirmed'?'success':'info');
      await renderCasperWorkflow();
    } catch(err) { toast(err.message,"error"); btn.disabled=false; btn.textContent="Anchor to Casper"; }
  });
}

const CE_SEVERITY_COLOR = { critical: "var(--red)", high: "var(--amber)", medium: "var(--cyan)", low: "var(--text-3)" };

function casperEngineerArtifact(d) {
  if (!d) return "";
  const plan = d.planning || {};
  const analysis = d.repository_analysis || {};
  const verif = d.self_verification || {};
  const critique = d.self_critique || {};
  const statusKind = { verified: "active", needs_review: "pending", degraded: "error" }[d.status] || "default";
  const li = (arr, fn) => (Array.isArray(arr) && arr.length ? `<ul style="margin:6px 0 0;padding-left:18px">${arr.map(fn).join("")}</ul>` : `<span class="subtle" style="font-size:11px">—</span>`);
  const subtasks = li(plan.subtasks, (s) => `<li style="font-size:12px;margin-bottom:4px"><strong>${esc(s.title || s)}</strong>${s.detail ? ` — ${esc(s.detail)}` : ""}</li>`);
  const risks = li(plan.risks, (r) => `<li style="font-size:12px;margin-bottom:4px"><span class="status-badge ${{critical:'error',high:'pending'}[r.severity]||'default'}" style="font-size:9px">${esc(r.severity || '')}</span> ${esc(r.risk || '')}${r.mitigation ? ` <span class="subtle">→ ${esc(r.mitigation)}</span>` : ""}</li>`);
  const issues = (critique.issues || []).map((i) => `<div class="card" style="padding:10px 12px;margin-bottom:8px;border-left:3px solid ${CE_SEVERITY_COLOR[i.severity] || 'var(--line-strong)'}">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:${CE_SEVERITY_COLOR[i.severity] || 'var(--text-2)'}">${esc(i.category || '')} · ${esc(i.severity || '')}</div>
    <div style="font-size:12px;margin-top:3px">${esc(i.detail || '')}</div>
    ${i.fix ? `<div style="font-size:12px;margin-top:3px;color:var(--text-2)"><strong>${t('casper_eng.fix')}:</strong> ${esc(i.fix)}</div>` : ""}</div>`).join("") || `<span class="subtle" style="font-size:11px">${t('casper_eng.no_issues')}</span>`;
  const improved = critique.improved_plan || {};
  const conf = d.confidence != null ? `${Math.round(d.confidence * 100)}%` : "—";
  const kv = (label, arr) => `<div style="margin-bottom:8px"><div class="subtle" style="font-size:10px;text-transform:uppercase">${esc(label)}</div>${li(arr, (x) => `<li style="font-size:12px">${esc(x)}</li>`)}</div>`;
  return `<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>${t('casper_eng.artifact')}</h3><span class="subtle">${esc(d.goal || '')}</span></div><div style="display:flex;gap:8px;align-items:center"><span class="status-badge ${statusKind}">${esc(d.status || '')}</span><span class="status-badge default" title="${t('casper_eng.confidence')}">${t('casper_eng.confidence')}: ${conf}</span></div></div><div class="card-body" style="display:grid;gap:16px">
    ${d.needs_repo_context ? `<div style="padding:8px 12px;background:var(--surface-2);border:1px solid var(--amber);border-radius:6px;font-size:12px;color:var(--amber)">${t('casper_eng.needs_repo')}</div>` : ""}
    <div><div class="page-section-label">1 · ${t('casper_eng.planning')}</div>${plan.understanding ? `<p style="font-size:12px;margin:4px 0 8px">${esc(plan.understanding)}</p>` : ""}<div class="subtle" style="font-size:10px;text-transform:uppercase">${t('casper_eng.subtasks')}</div>${subtasks}<div class="subtle" style="font-size:10px;text-transform:uppercase;margin-top:8px">${t('casper_eng.risks')}</div>${risks}</div>
    <div><div class="page-section-label">2 · ${t('casper_eng.repo_analysis')}</div>${analysis.structure ? `<p style="font-size:12px;margin:4px 0 8px">${esc(analysis.structure)}</p>` : ""}${kv(t('casper_eng.conventions'), analysis.conventions)}${kv(t('casper_eng.patterns'), analysis.existing_patterns)}${kv(t('casper_eng.integration'), analysis.integration_points)}${kv(t('casper_eng.constraints'), analysis.constraints)}</div>
    <div><div class="page-section-label">3 · ${t('casper_eng.verification')}</div><p style="font-size:12px;margin:4px 0">${verif.complete ? '✓' : '⚠'} ${esc(verif.reasoning || '')}</p>${kv(t('casper_eng.gaps'), verif.gaps)}</div>
    <div><div class="page-section-label">4 · ${t('casper_eng.self_critique')}</div>${issues}${improved.summary ? `<div style="margin-top:10px"><div class="subtle" style="font-size:10px;text-transform:uppercase">${t('casper_eng.improved_plan')}</div><p style="font-size:12px;margin:4px 0">${esc(improved.summary)}</p>${li(improved.steps, (s) => `<li style="font-size:12px">${esc(s)}</li>`)}</div>` : ""}</div>
  </div></div>`;
}

async function renderCasperEngineer() {
  const header = pageHeader(t('route.casper-engineer.title'), t('route.casper-engineer.desc'));
  const form = `<div class="card"><div class="card-body">
    <form id="casper-engineer-form" style="display:grid;gap:12px">
      <label class="field full"><span>${t('casper_eng.goal')}</span><textarea name="goal" rows="3" required minlength="3" placeholder="${t('casper_eng.goal_ph')}"></textarea></label>
      <label class="field full"><span>${t('casper_eng.repo_ctx')} <span class="subtle">(${t('common.optional')})</span></span><textarea name="repo_context" rows="4" placeholder="${t('casper_eng.repo_ctx_ph')}"></textarea></label>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer"><input type="checkbox" name="auto_repo" data-ce-auto> ${t('casper_eng.auto_repo')}</label>
        <input class="input" name="repo_path" value="." style="width:140px;display:none" data-ce-path placeholder="${t('casper_eng.repo_path')}">
        <span class="subtle" style="font-size:11px;flex:1" data-ce-auto-hint style="display:none">${t('casper_eng.auto_repo_hint')}</span>
      </div>
      <div style="display:flex;justify-content:flex-end"><button class="button button-primary" type="submit">${icon('agents',14)} ${t('casper_eng.run')}</button></div>
    </form></div></div>
    <div id="ce-result"></div>
    <div id="ce-recent" style="margin-top:20px"></div>`;
  setPage(`${header}<div style="padding:8px 14px;margin-bottom:14px;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:6px;font-size:12px;color:var(--text-2)">${t('casper_eng.intro')}</div>${form}`);

  async function loadRecent() {
    const runs = await api.casperEngineerRuns(10).catch(() => []);
    el("#ce-recent").innerHTML = runs.length
      ? `<div class="page-section-label">${t('casper_eng.recent')} (${runs.length})</div><div class="table-wrap"><table class="data-table"><thead><tr><th>${t('casper_eng.goal')}</th><th>Status</th><th>${t('casper_eng.confidence')}</th><th>${t('page.knowledge.col_updated')}</th></tr></thead><tbody>${runs.map((r) => `<tr data-ce-open="${esc(r.id)}" style="cursor:pointer"><td>${esc((r.goal || '').slice(0, 80))}</td><td><span class="status-badge ${{verified:'active',needs_review:'pending',degraded:'error'}[r.status]||'default'}">${esc(r.status)}</span></td><td>${r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—'}</td><td>${relativeTime(r.created_at)}</td></tr>`).join("")}</tbody></table></div>`
      : "";
  }
  loadRecent();

  el("#casper-engineer-form")?.addEventListener("change", (e) => {
    if (e.target.matches("[data-ce-auto]")) {
      const on = e.target.checked;
      const pathEl = el("[data-ce-path]"), hintEl = el("[data-ce-auto-hint]");
      if (pathEl) pathEl.style.display = on ? "" : "none";
      if (hintEl) hintEl.style.display = on ? "" : "none";
    }
  });

  el("#casper-engineer-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      goal: fd.get("goal"),
      repo_context: fd.get("repo_context") || null,
      auto_repo: !!fd.get("auto_repo"),
      repo_path: fd.get("repo_path") || ".",
    };
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true; btn.textContent = t('casper_eng.running');
    el("#ce-result").innerHTML = `<div class="skeleton" style="height:120px;margin-top:16px"></div>`;
    try {
      const result = await api.casperEngineerRun(body);
      el("#ce-result").innerHTML = casperEngineerArtifact(result);
      if (result.repo_ingest && result.repo_ingest.scanned) toast(`${t('casper_eng.repo_ingested')}: ${result.repo_ingest.project_type || '?'} · ${result.repo_ingest.total_files ?? '?'} file`, "info");
      toast(t('casper_eng.done'), result.status === 'degraded' ? 'error' : 'success');
      await loadRecent();
    } catch (err) {
      el("#ce-result").innerHTML = errorState(err?.data?.detail || err.message);
      toast(err?.data?.detail || err.message, "error");
    } finally {
      btn.disabled = false; btn.innerHTML = `${icon('agents', 14)} ${t('casper_eng.run')}`;
    }
  });

  el("#ce-recent")?.addEventListener("click", async (e) => {
    const row = e.target.closest("[data-ce-open]");
    if (!row) return;
    try {
      const detail = await api.casperEngineerRunDetail(row.getAttribute("data-ce-open"));
      el("#ce-result").innerHTML = casperEngineerArtifact(detail);
      el("#ce-result").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) { toast(err.message, "error"); }
  });
}

async function route() {
  closeObservabilityWs();   // tutup WS realtime saat pindah halaman
  state.route = currentRoute(); renderChrome(); closeMobileNav(); settingRowStyles();
  const renderers = {founder:renderFounder,dashboard:renderDashboard,agents:renderAgents,chat:renderChat,conversations:renderConversations,handoffs:renderHumanHandoff,analytics:renderAnalytics,"routing-logs":renderRoutingLogs,learning:renderFeedbackLearning,improvement:renderImprovement,observability:renderObservability,costs:renderCostIntelligence,channels:renderChannels,"communication-center":renderCommunicationCenter,marketplace:renderMarketplace,knowledge:renderKnowledge,"kb-builder":renderKnowledgeBuilder,"workflow-builder":renderWorkflowBuilder,finance:renderFinance,marketing:renderMarketing,hr:renderHR,operations:renderOperations,executive:renderExecutive,workforce:renderWorkforce,"self-learning":renderLearning,"workforce-overview":renderWorkforceOverview,"agent-center":renderAgentCenter,multimedia:renderMultimedia,team:renderTeam,billing:renderBilling,security:renderSecurity,settings:renderSettings,about:renderAbout,"founder-story":renderFounderStory,"investor-demo":renderInvestorDemo,"casper-agentic-workflow":renderCasperWorkflow,"casper-engineer":renderCasperEngineer};
  const fn = renderers[state.route] || renderDashboard;
  await fn();
}

async function submitCreateAgent() {
  const form = el("#create-agent-form"); if (!form || !form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  const button = el('[data-action="submit-create-agent"]'); button.disabled=true; button.textContent="Deploying...";
  try {
    await api.createBot({ name:data.name, language:data.language, greeting:data.greeting || "Halo! Ada yang bisa saya bantu?", system_prompt:data.system_prompt || null, primary_color:"#3d6791", status:"active" });
    bustCache("bots"); state.bots = await api.bots(); state.selectedBotId = state.bots[0]?.id || null; el("#modal-root").innerHTML=""; renderChrome(); toast("AI agent deployed successfully.","success"); await route();
  } catch (error) { toast(error.message,"error"); button.disabled=false; button.textContent="Deploy agent"; }
}

async function submitAgentDetail(form) {
  const id=form.dataset.agentId; const data=Object.fromEntries(new FormData(form));
  if('computer_agent_enabled' in data) data.computer_agent_enabled = data.computer_agent_enabled === 'true';
  const button=form.querySelector('button[type="submit"]'); button.disabled=true; button.textContent="Saving...";
  try { await api.updateBot(id,data); bustCache("bots"); state.bots=await api.bots(); closeDrawer(); renderChrome(); toast("Agent configuration saved.","success"); await route(); }
  catch(error){ toast(error.message,"error"); button.disabled=false; button.textContent="Save changes"; }
}

async function uploadDocument(input) {
  const file=input.files?.[0]; if(!file)return;
  toast(`Uploading ${file.name}...`);
  try { await api.uploadDocument(state.selectedBotId,file); toast("Document uploaded. Processing knowledge chunks.","success"); await renderKnowledge(); }
  catch(error){ toast(error.message,"error"); }
}

async function uploadKnowledgeUrl(form) {
  if (!form) return;
  const data = Object.fromEntries(new FormData(form));
  const url = (data.url || '').trim();
  const title = (data.title || '').trim() || null;
  if (!url) return;
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  toast(`Uploading URL ${url}...`);
  try { await api.uploadDocumentUrl(state.selectedBotId, url, title); form.reset(); toast("Website URL uploaded. Processing knowledge chunks.","success"); await renderKnowledge(); }
  catch(error){ toast(error.message,"error"); }
  finally { if (button) button.disabled = false; }
}

async function uploadFaqCsv(input) {
  const file=input.files?.[0]; if(!file)return;
  toast(`Mengimpor ${file.name}...`);
  try { const result = await api.importFaqCsv(state.selectedBotId,file); toast(`${result.imported} FAQ diimpor ke knowledge base.`,"success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
  finally { input.value = ""; }
}

async function bulkImportKnowledgeUrls(form) {
  const text = String(new FormData(form).get("urls") || "");
  const urls = text.split(/\r?\n/).map((line)=>line.trim()).filter(Boolean).map((url)=>({ url, category:"custom", priority:"normal", agent:"custom", language:"id", trusted:false }));
  if (!urls.length) return toast("Masukkan minimal satu URL.", "error");
  const button = form.querySelector('button[type="submit"]'); if(button) button.disabled = true;
  try { const result = await api.bulkKnowledgeUrls(state.selectedBotId, urls, true); form.reset(); toast(`${result.imported} URL masuk queue, ${result.skipped_duplicate} duplicate dilewati.`, "success"); await renderKnowledge(); }
  catch(error){ toast(error.message,"error"); }
  finally { if(button) button.disabled = false; }
}

async function seedKnowledge(kind) {
  try {
    let result;
    if (kind === "marketplace") result = await api.seedMarketplaceKnowledge(state.selectedBotId, false, false);
    else if (kind === "general") result = await api.seedKnowledgeGeneral(state.selectedBotId, true);
    else if (kind === "all") result = await api.seedKnowledgeAgents(state.selectedBotId, true);
    else result = await api.seedKnowledgeAgent(kind, state.selectedBotId, true);
    const imported = result.imported ?? Object.values(result.results || {}).reduce((n,item)=>n+(item.imported||0),0);
    toast(`${imported} URL seed masuk queue. Crawler background dijadwalkan terbatas.`, "success");
    await renderKnowledge();
  } catch(error) { toast(error.message,"error"); }
}

async function regenerateKb(docId) {
  try { await api.kbRegenerate(state.selectedBotId,docId); toast("Knowledge Builder dijadwalkan ulang untuk dokumen ini.","success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
}

async function kbFaqAction(faqId, status) {
  try { await api.kbUpdateFaq(faqId,{status}); toast("FAQ diperbarui.","success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
}

async function editKbFaq(faqId) {
  const faq = state.kbFaqs.find((item) => String(item.id)===String(faqId)); if(!faq) return;
  const question = prompt("Pertanyaan:", faq.question); if(question===null) return;
  const answer = prompt("Jawaban:", faq.answer); if(answer===null) return;
  try { await api.kbUpdateFaq(faqId,{question,answer}); toast("FAQ diperbarui.","success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
}

async function kbSopAction(sopId, status) {
  try { await api.kbUpdateSop(sopId,{status}); toast("SOP diperbarui.","success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
}

async function editKbSop(sopId) {
  const sop = state.kbSops.find((item) => String(item.id)===String(sopId)); if(!sop) return;
  const title = prompt("Judul SOP:", sop.title); if(title===null) return;
  const stepsText = prompt("Langkah-langkah (satu per baris):", (sop.steps||[]).join("\n")); if(stepsText===null) return;
  const steps = stepsText.split("\n").map((item) => item.trim()).filter(Boolean);
  try { await api.kbUpdateSop(sopId,{title,steps}); toast("SOP diperbarui.","success"); await renderKnowledgeBuilder(); }
  catch(error){ toast(error.message,"error"); }
}

// Map raw backend/Midtrans failure text to a message a non-technical user can
// act on, instead of showing e.g. "Gagal membuat transaksi Midtrans" verbatim.
function humanizeCheckoutError(error) {
  const msg = String(error?.message || "");
  if (error?.status === 0) return "API tidak dapat dihubungi. Periksa koneksi internet Anda dan coba lagi.";
  if (/midtrans/i.test(msg) && /(belum dikonfigurasi|gagal membuat transaksi)/i.test(msg)) {
    return "Pembayaran Midtrans belum bisa diproses saat ini — channel pembayaran masih menunggu approval dari Midtrans. Coba lagi nanti, atau hubungi kami.";
  }
  if (/xendit/i.test(msg) && /(belum dikonfigurasi|gagal membuat invoice)/i.test(msg)) {
    return "Pembayaran Xendit belum tersedia saat ini. Coba metode pembayaran lain atau hubungi kami.";
  }
  return msg || "Terjadi kesalahan saat memproses pembayaran.";
}

async function checkout(planKey, useFreeTrial = false) {
  const label = useFreeTrial ? `Mulai free trial 1 bulan paket ${planKey}?` : `Aktifkan paket ${planKey}?`;
  if(!confirm(label)) return;
  try {
    const result = await api.checkout(planKey, "monthly", "midtrans", useFreeTrial);
    bustCache("plans","subscription","usage");
    if(result.redirect_url) location.href = result.redirect_url;
    else {
      const msg = result.free_trial
        ? `✓ Free trial 1 bulan paket ${planKey} aktif!`
        : "Subscription aktif.";
      toast(msg, "success");
      await renderBilling();
    }
  }
  catch(error){ toast(humanizeCheckoutError(error), "error"); }
}

async function topupCredits(amountIdr, convCountRaw) {
  // Jumlah percakapan diambil dari data tombol (data-topup-conv) yang dirender
  // dari API — TIDAK di-hardcode, supaya selalu sinkron dengan backend.
  const convCount = Number(convCountRaw) || 0;
  const convLabel = convCount ? ` (+${convCount.toLocaleString('id-ID')} ${t('billing.conversations_unit')})` : '';
  if(!confirm(`Top up Rp${Number(amountIdr).toLocaleString('id-ID')}${convLabel}?`)) return;
  try {
    const result = await api.topupCredits(Number(amountIdr), "midtrans");
    bustCache("credits");
    if(result.redirect_url) location.href = result.redirect_url;
    else {
      const added = result.conversations_added ?? convCount ?? 0;
      toast(`✓ +${added.toLocaleString('id-ID')} ${t('billing.conversations_unit')} berhasil ditambahkan!`, "success");
      await renderBilling();
    }
  }
  catch(error){ toast(humanizeCheckoutError(error), "error"); }
}

async function buyAddon(addonKey) {
  // Ambil spesifikasi add-on dari cache /addons (nama + harga) untuk konfirmasi.
  const cat = (_cache.get("addons")?.data?.catalog || []).find(a => a.key === addonKey);
  const nameKey = `billing.addon.${addonKey}`;
  const name = (cat && t(nameKey) !== nameKey) ? t(nameKey) : (cat?.label || addonKey);
  const priceLabel = cat ? `Rp${Number(cat.price_idr).toLocaleString('id-ID')}` : '';
  if (!confirm(`${t('billing.addon_confirm')} ${name}${priceLabel ? ` — ${priceLabel}` : ''}?`)) return;
  try {
    const result = await api.checkoutAddon(addonKey, 1, "midtrans");
    bustCache("addons", "subscription", "usage");
    if (result.redirect_url) location.href = result.redirect_url;
    else {
      toast(`✓ ${name} ${t('billing.addon_added')}`, "success");
      await renderBilling();
    }
  }
  catch(error){ toast(humanizeCheckoutError(error), "error"); }
}

async function saveTaxProfile(form) {
  const error = form.querySelector("[data-form-error]"); if(error) error.textContent="";
  const fd = new FormData(form);
  const body = {
    tax_name: String(fd.get("tax_name")||"").trim(),
    tax_npwp: String(fd.get("tax_npwp")||"").trim(),
    tax_address: String(fd.get("tax_address")||"").trim(),
    is_pkp: fd.get("is_pkp")==="on",
  };
  try{
    await api.saveTaxProfile(body);
    bustCache("invoices");
    toast(t('billing.tax_saved'), "success");
    await renderBilling();
  }catch(err){ if(error) error.textContent=err.message; else toast(err.message,"error"); }
}

async function saveSsoConfig(form) {
  const error = form.querySelector("[data-form-error]"); if(error) error.textContent="";
  const fd = new FormData(form);
  const body = {
    issuer: String(fd.get("issuer")||"").trim(),
    client_id: String(fd.get("client_id")||"").trim(),
    allowed_domains: String(fd.get("allowed_domains")||"").split(",").map(s=>s.trim()).filter(Boolean),
    jit_enabled: fd.get("jit_enabled")==="on",
    default_role: String(fd.get("default_role")||"member"),
    enabled: fd.get("enabled")==="on",
  };
  const secret = String(fd.get("client_secret")||"").trim();
  if(secret) body.client_secret = secret;   // kosong = pertahankan secret lama
  try{
    await api.saveSsoConfig(body);
    bustCache("ssoConfig");
    toast(t('settings.sso_saved'), "success");
    await renderSettings();
  }catch(err){ if(error) error.textContent=err.message; else toast(err.message,"error"); }
}

async function deleteSsoConfig() {
  if(!confirm(t('settings.sso_delete_confirm'))) return;
  try{ await api.deleteSsoConfig(); bustCache("ssoConfig"); toast(t('settings.sso_deleted'),"success"); await renderSettings(); }
  catch(err){ toast(err.message,"error"); }
}

// ── Computer Access: aksi kelas-satu per perangkat (wired ke endpoint nyata) ──
function caResultHtml(r) {
  if (!r || typeof r !== "object") return `<pre class="ca-out">${esc(String(r))}</pre>`;
  const out = r.stdout || r.output || "";
  const err = r.stderr || (r.success === false ? (r.error || "") : "");
  if (out || err) return `${out?`<pre class="ca-out">${esc(out)}</pre>`:""}${err?`<pre class="ca-out ca-err">${esc(err)}</pre>`:""}`;
  return `<pre class="ca-out">${esc(JSON.stringify(r, null, 2))}</pre>`;
}

async function caOpenFiles(deviceId, path) {
  let r;
  try { r = await api.localAgentExecute({ tool: "list_dir", args: { path }, device_id: deviceId }); }
  catch (e) { r = { success: false, error: e.message }; }
  if (!r.success) { el("#modal-root").innerHTML = modal({ title: "Files", body: `<p class="subtle">${esc(r.error || "Gagal membuka folder")}</p>`, footer: `<button class="button" data-action="close-modal">Tutup</button>` }); return; }
  const cur = r.path || path;
  const up = cur.replace(/[/\\][^/\\]+[/\\]?$/, "") || cur;
  const rows = (r.items || []).map(it => {
    const isDir = it.type === "dir";
    const full = (cur.endsWith("/") ? cur : cur + "/") + it.name;
    return `<div class="ca-file-row ${isDir?'is-dir':''}" ${isDir?`data-ca-files="${esc(deviceId)}::${esc(full)}"`:''}>
      <span>${isDir?"📁":"📄"} ${esc(it.name)}</span><span class="subtle" style="font-size:11px">${isDir?"":formatFileSize(it.size)}</span></div>`;
  }).join("");
  el("#modal-root").innerHTML = modal({ title: `Files — ${esc(cur)}`, wide: true,
    body: `<div class="ca-file-head"><button class="button button-sm" data-ca-files="${esc(deviceId)}::${esc(up)}">⬆ Naik</button><span class="subtle mono" style="font-size:11px;margin-left:8px">${esc(cur)}</span></div><div class="ca-file-list">${rows || '<p class="subtle">Folder kosong</p>'}</div>`,
    footer: `<button class="button" data-action="close-modal">Tutup</button>` });
}

async function handleComputerAccess(action, deviceId) {
  if (action === "info") {
    try { const r = await api.localAgentExecute({ tool: "get_info", args: {}, device_id: deviceId });
      el("#modal-root").innerHTML = modal({ title: "System Info", body: caResultHtml(r), footer: `<button class="button" data-action="close-modal">Tutup</button>` });
    } catch (e) { toast(e.message, "error"); }
    return;
  }
  if (action === "browser") {
    const url = prompt("URL yang dibuka di browser perangkat:", "https://");
    if (!url) return;
    try { const r = await api.localAgentExecute({ tool: "open", args: { target: url }, device_id: deviceId });
      toast(r.success ? `Membuka ${url} di perangkat.` : (r.error || "Gagal (agent mungkin perlu di-restart untuk tool 'open')"), r.success ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
    return;
  }
  if (action === "terminal") {
    el("#modal-root").innerHTML = modal({ title: "Terminal — jalankan perintah",
      body: `<form id="ca-terminal-form" data-device="${esc(deviceId)}"><div class="form-grid"><label class="field full"><span>Perintah shell</span><input name="command" placeholder="npm run build" autocomplete="off" required></label></div><p class="subtle" style="font-size:11px">Perintah berbahaya bisa minta persetujuan di komputer Anda.</p><div id="ca-out" style="margin-top:10px"></div></form>`,
      footer: `<button class="button" data-action="close-modal">Tutup</button><button class="button button-primary" data-action="ca-terminal-run">Jalankan</button>` });
    return;
  }
  if (action === "files") { await caOpenFiles(deviceId, "~/"); return; }
  if (action === "agent") {
    el("#modal-root").innerHTML = modal({ title: "Computer Agent — beri tugas (bahasa natural)",
      body: `<form id="ca-agent-form" data-device="${esc(deviceId)}"><div class="form-grid"><label class="field full"><span>Tugas</span><textarea name="goal" rows="3" placeholder="Contoh: cari file package.json lalu scan project-nya" required></textarea></label></div><div id="ca-out" style="margin-top:10px"></div></form>`,
      footer: `<button class="button" data-action="close-modal">Tutup</button><button class="button button-primary" data-action="ca-agent-run">Jalankan</button>` });
    return;
  }
}

async function caRunTerminal() {
  const form = document.getElementById("ca-terminal-form"); if (!form) return;
  const deviceId = form.dataset.device;
  const command = form.elements.command.value.trim(); if (!command) return;
  const out = document.getElementById("ca-out"); if (out) out.innerHTML = `<pre class="ca-out">Menjalankan…</pre>`;
  try { const r = await api.localAgentExecute({ tool: "run_command", args: { command }, device_id: deviceId, timeout: 60 });
    if (out) out.innerHTML = caResultHtml(r);
  } catch (e) { if (out) out.innerHTML = `<pre class="ca-out ca-err">${esc(e.message)}</pre>`; }
}

async function caRunAgent() {
  const form = document.getElementById("ca-agent-form"); if (!form) return;
  const deviceId = form.dataset.device;
  const goal = form.elements.goal.value.trim(); if (!goal) return;
  const out = document.getElementById("ca-out"); if (out) out.innerHTML = `<pre class="ca-out">AI merencanakan langkah…</pre>`;
  try { const r = await api.computerAgentRunLocal(goal, 30, deviceId);
    if (out) out.innerHTML = caResultHtml(r);
  } catch (e) { if (out) out.innerHTML = `<pre class="ca-out ca-err">${esc(e.message)}</pre>`; }
}

async function sendPlayground(form) {
  if (!form || form.dataset.sending === "true") return;
  const input = form.elements.message;
  const text = input?.value.trim();
  const botId = form.dataset.botId;
  const container = form.closest(".chat-page") || document;
  const messages = container.querySelector("#playground-messages");
  const submitButton = form.querySelector('button[type="submit"]');
  if (!text || !botId || !messages) return;

  form.dataset.sending = "true";
  messages.insertAdjacentHTML("beforeend", `<div class="message user"><div class="message-bubble">${esc(text)}</div></div><div class="message" data-thinking><div class="message-bubble"><span class="thinking"><i></i><i></i><i></i></span></div></div>`);
  input.value = "";
  messages.scrollTop = messages.scrollHeight;
  if (submitButton) submitButton.disabled = true;
  try {
    const result = await api.chat(botId, text, state.chatSession, {userId:"dashboard-playground", channel:"dashboard"});
    state.chatSession = result.session_id;
    let preparedSpeech = null;
    if (state.speakReplies) {
      try {
        preparedSpeech = await prepareSpeech(result.answer, container);
      } catch (error) {
        voiceStatus(container, `Suara gagal disiapkan: ${error.message}`);
      }
    }
    messages.querySelector("[data-thinking]")?.remove();
    const imageHtml = result.image_url ? `<img src="${esc(result.image_url)}" alt="Generated" style="max-width:280px;border-radius:8px;display:block;margin-bottom:8px">` : "";
    messages.insertAdjacentHTML("beforeend", `<div class="message"><div class="message-bubble">${imageHtml}${renderMarkdown(result.answer)}<div class="message-meta">AI · ${result.latency_ms || 0}ms</div>${feedbackControls(result.message_id,result.session_id)}</div></div>`);
    if (preparedSpeech) {
      speak(result.answer, container, preparedSpeech).catch((error) => voiceStatus(container, `Suara gagal: ${error.message}`));
    }
  } catch (error) {
    messages.querySelector("[data-thinking]")?.remove();
    messages.insertAdjacentHTML("beforeend", `<div class="message"><div class="message-bubble" style="color:var(--red)">${esc(error.message)}</div></div>`);
  } finally {
    delete form.dataset.sending;
    if (submitButton) submitButton.disabled = false;
    input.focus();
    messages.scrollTop = messages.scrollHeight;
  }
}

async function uploadChatImage(input) {
  const file = input.files?.[0];
  if (!file) return;
  const form = input.closest("form");
  const container = form?.closest(".chat-page") || document;
  const messages = container.querySelector("#playground-messages");
  if (!messages) { input.value = ""; return; }
  const textarea = form?.elements?.message;
  const question = textarea?.value.trim() || "";
  const localUrl = URL.createObjectURL(file);
  messages.insertAdjacentHTML("beforeend", `<div class="message user"><div class="message-bubble"><img src="${esc(localUrl)}" alt="" style="max-width:220px;border-radius:8px;display:block;margin-bottom:6px">${esc(question || "Analisis gambar ini")}</div></div><div class="message" data-thinking><div class="message-bubble"><span class="thinking"><i></i><i></i><i></i></span></div></div>`);
  if (textarea) textarea.value = "";
  messages.scrollTop = messages.scrollHeight;
  try {
    const result = await api.imagesAnalyze(file, { question, mode: "describe", botId: state.selectedBotId });
    messages.querySelector("[data-thinking]")?.remove();
    messages.insertAdjacentHTML("beforeend", `<div class="message"><div class="message-bubble">${renderMarkdown(result.answer)}<div class="message-meta">Vision AI</div></div></div>`);
  } catch (error) {
    messages.querySelector("[data-thinking]")?.remove();
    messages.insertAdjacentHTML("beforeend", `<div class="message"><div class="message-bubble" style="color:var(--red)">${esc(error.message)}</div></div>`);
  } finally {
    input.value = "";
    messages.scrollTop = messages.scrollHeight;
  }
}

document.addEventListener("click", async (event) => {
  const langBtn = event.target.closest("[data-set-lang]");
  if (langBtn) { setLang(langBtn.dataset.setLang); renderChrome(); await route(); return; }
  const navToggle=event.target.closest("[data-nav-toggle]");
  if(navToggle){
    const key=navToggle.dataset.navToggle;
    if(state.navOpenSections.has(key)) state.navOpenSections.delete(key); else state.navOpenSections.add(key);
    renderChrome();
    return;
  }
  const feedbackButton=event.target.closest("[data-feedback-rating]");
  if(feedbackButton){
    const rating=feedbackButton.dataset.feedbackRating;
    const comment=rating==='not_helpful' ? (prompt("Apa yang kurang dari jawaban ini? (opsional)") || null) : null;
    try {
      await api.submitFeedback(feedbackButton.dataset.feedbackMessage,feedbackButton.dataset.feedbackConversation,rating,comment);
      const group=feedbackButton.closest("[data-feedback-group]");
      group?.querySelectorAll(".feedback-button").forEach((button)=>button.classList.toggle("selected",button===feedbackButton));
      feedbackButton.classList.toggle("negative",rating==='not_helpful');
      toast(rating==='helpful'?"Feedback Helpful tersimpan.":"Feedback masuk ke learning queue.","success");
    } catch(error) { toast(error.message,"error"); }
    return;
  }
  const learningAction=event.target.closest("[data-learning-action]");
  if(learningAction){ const note=learningAction.dataset.learningAction==='resolved' ? (prompt("Catatan perbaikan yang diterapkan:") || null) : null; try{ await api.updateFeedbackQueue(learningAction.dataset.learningId,learningAction.dataset.learningAction,note); toast("Learning queue updated.","success"); await renderFeedbackLearning(); }catch(error){ toast(error.message,"error"); } return; }
  const claimHandoff=event.target.closest("[data-claim-handoff]");
  if(claimHandoff){ try{ await api.claimHandoff(claimHandoff.dataset.claimHandoff); toast("Handoff assigned to you.","success"); await renderHumanHandoff(); }catch(error){ toast(error.message,"error"); } return; }
  const replyHandoff=event.target.closest("[data-reply-handoff]");
  if(replyHandoff){ const message=prompt("Balasan manusia ke pelanggan:"); if(message?.trim()){ try{ await api.replyHandoff(replyHandoff.dataset.replyHandoff,message.trim()); toast("Human reply sent.","success"); }catch(error){ toast(error.message,"error"); } } return; }
  const resolveHandoff=event.target.closest("[data-resolve-handoff]");
  if(resolveHandoff){ const note=prompt("Catatan resolusi (opsional):") || null; try{ await api.resolveHandoff(resolveHandoff.dataset.resolveHandoff,note); toast("Handoff resolved. AI can resume.","success"); await renderHumanHandoff(); }catch(error){ toast(error.message,"error"); } return; }
  const traceTarget=event.target.closest("[data-observability-trace]");
  if(traceTarget){ await openObservabilityTrace(traceTarget.dataset.observabilityTrace); return; }
  const agentErrTarget=event.target.closest("[data-obs-agent-error]");
  if(agentErrTarget){ await openAgentErrorDetail(agentErrTarget.dataset.obsAgentError); return; }
  const viewSources=event.target.closest("[data-view-sources]");
  if(viewSources){ await openMessageSources(viewSources.dataset.viewSources); return; }
  const marketplaceCategory=event.target.closest("[data-marketplace-category]");
  if(marketplaceCategory){ state.marketplaceFilters ||= { search:"", category:"" }; state.marketplaceFilters.category=marketplaceCategory.dataset.marketplaceCategory || ""; await renderMarketplace(); return; }
  if(event.target.closest("[data-marketplace-clear]")){ state.marketplaceFilters={ search:"", category:"" }; await renderMarketplace(); return; }
  const routeTarget=event.target.closest("[data-route]");
  if(routeTarget){ location.hash=routeTarget.dataset.route; return; }
  const agentTarget=event.target.closest("[data-agent-id]");
  if(agentTarget && !agentTarget.closest("#detail-drawer")){ showAgent(agentTarget.dataset.agentId); return; }
  const conversation=event.target.closest("[data-conversation-id]"); if(conversation){ await openConversation(conversation.dataset.conversationId); return; }
  const action=event.target.closest("[data-action]")?.dataset.action;
  if(action==="show-upgrade-dialog"){ el("#modal-root").innerHTML = upgradeDialog(event.target.closest("[data-plan]")?.dataset.plan || "Pro"); }
  if(action==="toggle-sidebar"){ el("#sidebar").classList.toggle("open"); el("#mobile-scrim").classList.toggle("open"); }
  if(action==="logout"){ tokenStore.clear(); showAuth(); }
  if(action==="refresh") await route();
  if(action==="create-agent") showCreateAgent();
  if(action==="submit-create-agent") await submitCreateAgent();
  if(action==="marketplace-install") showMarketplaceInstall(event.target.closest("[data-marketplace-install]")?.dataset.marketplaceInstall);
  if(action==="submit-marketplace-install") await submitMarketplaceInstall();
  if(action==="mkt-create") { showTemplateEditor(null); return; }
  if(action==="submit-mkt-template") { await submitTemplateEditor(); return; }
  const mktPub=event.target.closest("[data-mkt-publish]"); if(mktPub){ await marketplacePublish(mktPub.dataset.mktPublish, true); return; }
  const mktUnpub=event.target.closest("[data-mkt-unpublish]"); if(mktUnpub){ await marketplacePublish(mktUnpub.dataset.mktUnpublish, false); return; }
  const mktEdit=event.target.closest("[data-mkt-edit]"); if(mktEdit){ showTemplateEditor(mktEdit.dataset.mktEdit); return; }
  if(action==="close-modal") {
    const closeTarget = event.target.closest('[data-action="close-modal"]');
    if(closeTarget?.matches('button') || event.target === closeTarget) el("#modal-root").innerHTML="";
  }
  if(action==="close-drawer") closeDrawer();
  if(action==="notifications") await showNotifications();
  if(action==="gmail-start") await startGmail();
  if(action==="gmail-map") await mapGmail();
  if(action==="gmail-poll") await pollGmail();
  if(action==="sso-delete") await deleteSsoConfig();
  if(action==="connect-whatsapp") showWhatsAppConnect();
  if(action==="submit-meta-asset") await submitMetaAssetSelection();
  if(action==="confirm-meta-redirect" && state.pendingMetaAuthUrl) location.href = state.pendingMetaAuthUrl;
  if(action==="refresh-meta-token"){ try{await api.metaOAuthRefresh();toast("Meta access refreshed.","success");await renderChannels();}catch(error){toast(error.message,"error");} }
  const connectMeta=event.target.closest("[data-connect-meta-channel]"); if(connectMeta) await showMetaConnect(connectMeta.dataset.connectMetaChannel);
  if(action==="submit-connect-whatsapp") await submitWhatsAppConnect();
  const disconnectWhatsApp=event.target.closest("[data-disconnect-whatsapp-bot]"); if(disconnectWhatsApp) await disconnectWhatsAppEmbedded(disconnectWhatsApp.dataset.disconnectWhatsappBot);
  const disconnectIntegration=event.target.closest("[data-disconnect-integration]"); if(disconnectIntegration && confirm("Disconnect this integration?")){ try{ await api.deleteIntegration(disconnectIntegration.dataset.disconnectIntegration); toast("Integration disconnected.","success"); await renderSettings(); }catch(error){toast(error.message,"error");} }
  if(action==="send-chat") { event.preventDefault(); await sendPlayground(event.target.closest("form")); }
  if(action==="toggle-recording") await toggleRecording(event.target.closest('[data-action="toggle-recording"]'));
  if(action==="new-chat") { state.chatSession = null; await renderChat(); }
  if(action==="toggle-speech") {
    const container = event.target.closest(".chat-page") || document;
    state.speakReplies = !state.speakReplies;
    if (!state.speakReplies) await stopSpeaking(container);
    voiceStatus(container, state.speakReplies ? "Suara aktif - jawaban AI akan dibaca sampai akhir" : "Suara dimatikan");
  }
  if(action==="security-scan") { try{ const result=await api.securityScan(); state.securityScan=result; toast(`Security scan completed: ${result.findings?.length||0} findings.`,"success"); if(state.route==="security") await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  if(action==="security-scan-and-alert") { try{ const result=await api.securityScanAndAlert(); state.securityScan=result.scan; toast(`Scan selesai: ${result.alerts_created?.length||0} alert baru.`,"success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  if(action==="security-generate-weekly") { try{ await api.generateSecurityReport("weekly"); toast("Weekly security report dibuat.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  if(action==="security-generate-monthly") { try{ await api.generateSecurityReport("monthly"); toast("Monthly security report dibuat.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  const securityAlertStatus=event.target.closest("[data-security-alert-status]"); if(securityAlertStatus){ const [id,status]=securityAlertStatus.dataset.securityAlertStatus.split(":"); try{ await api.updateSecurityRiskAlert(id,status); toast("Alert diperbarui.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="improvement-scan") { try{ const result=await api.improvementScan(state.improvementDays||30); toast(`Improvement scan completed: ${result.recommendations_generated||0} rekomendasi.`,"success"); if(state.route==="improvement") await renderImprovement(); }catch(error){ toast(error.message,"error"); } }
  const improvementAction=event.target.closest("[data-improvement-action]");
  if(improvementAction){ const status=improvementAction.dataset.improvementAction; const note=(status==="applied"||status==="dismissed") ? (prompt("Catatan (opsional):") || null) : null; try{ await api.updateImprovementRecommendation(improvementAction.dataset.improvementId,{status,resolution_note:note}); toast("Rekomendasi diperbarui.","success"); await renderImprovement(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="create-api-key") showCreateApiKey();
  if(action==="submit-create-api-key") await submitCreateApiKey();
  const revokeSession=event.target.closest("[data-revoke-session]"); if(revokeSession && confirm("Revoke this session? The user will be signed out.")){ try{ await api.revokeSecuritySession(revokeSession.dataset.revokeSession); toast("Session revoked.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  const rotateApiKey=event.target.closest("[data-rotate-api-key]"); if(rotateApiKey && confirm("Rotate this API key? The old key will stop working immediately.")){
    try{ const result=await api.rotateApiKey(rotateApiKey.dataset.rotateApiKey); el("#modal-root").innerHTML=modal({title:"API key rotated",body:`<p class="subtle" style="font-size:11px">Simpan key baru ini sekarang — hanya ditampilkan sekali. Key lama sudah tidak berlaku.</p><div class="form-grid"><label class="field full"><span>New API key</span><input value="${esc(result.key)}" readonly onclick="this.select()"></label></div>`,footer:`<button class="button button-primary" data-action="close-modal">Done</button>`}); toast("API key rotated.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); }
  }
  const revokeApiKey=event.target.closest("[data-revoke-api-key]"); if(revokeApiKey && confirm("Revoke this API key? Any integration using it will stop working.")){ try{ await api.revokeApiKey(revokeApiKey.dataset.revokeApiKey); toast("API key revoked.","success"); await renderSecurity(); }catch(error){ toast(error.message,"error"); } }
  if(action==="invite-member") showInviteMember();
  if(action==="submit-invite-member") await submitInviteMember();
  const disconnectChannel=event.target.closest("[data-disconnect-channel]"); if(disconnectChannel && confirm("Disconnect this channel?")){ try{ await api.disconnectChannel(disconnectChannel.dataset.disconnectChannel); toast("Channel disconnected.","success"); if(state.route==="channels") await renderChannels(); else await renderSettings(); }catch(error){toast(error.message,"error");} }
  const commPeriod=event.target.closest("[data-comm-period]"); if(commPeriod){ state.commCenterDays=Number(commPeriod.dataset.commPeriod); await renderCommunicationCenter(); return; }
  const execTrendPeriod=event.target.closest("[data-exec-trend-period]"); if(execTrendPeriod){ state.executiveTrendDays=Number(execTrendPeriod.dataset.execTrendPeriod); await renderExecutive(); return; }
  if(action==="manage-member") showMemberRole(event.target.closest("[data-team-user]")?.dataset.teamUser);
  if(action==="submit-member-role") await submitMemberRole();
  const revokeMemberRole=event.target.closest("[data-revoke-member-role]");
  if(revokeMemberRole && confirm("Hapus role ini dari anggota?")){
    try{ await api.revokeRole(revokeMemberRole.dataset.userId,revokeMemberRole.dataset.revokeMemberRole); toast("Role dihapus.","success"); await renderTeam(); showMemberRole(revokeMemberRole.dataset.userId); }
    catch(error){ toast(error.message,"error"); }
    return;
  }
  if(action==="export-team") exportTeam();
  if(action==="connect-channel") showConnectChannel();
  const connectType=event.target.closest("[data-connect-channel-type]"); if(connectType) {
    const type=connectType.dataset.connectChannelType;
    if(type==="whatsapp") showWhatsAppConnect();
    else if(type==="facebook"||type==="instagram") await showMetaConnect(type);
    else showConnectChannel(type);
  }
  if(action==="refresh-channel-health"){ try{ await api.channelStatus(true); toast("Channel health refreshed.","success"); if(state.route==="channels") await renderChannels(); }catch(error){toast(error.message,"error");} }
  if(action==="submit-connect-channel") await submitConnectChannel();
  const deleteDoc=event.target.closest("[data-delete-document]"); if(deleteDoc && confirm("Delete this knowledge document?")){ try{ await api.deleteDocument(state.selectedBotId,deleteDoc.dataset.deleteDocument); toast("Document deleted.","success"); await renderKnowledge(); }catch(error){toast(error.message,"error");} }
  const retrySource=event.target.closest("[data-retry-source]"); if(retrySource){ try{ await api.retryKnowledgeSource(retrySource.dataset.retrySource); toast("Retry dijadwalkan.","success"); await renderKnowledge(); }catch(error){toast(error.message,"error");} return; }
  const deleteSource=event.target.closest("[data-delete-source]"); if(deleteSource && confirm("Delete this URL source?")){ try{ await api.deleteKnowledgeSource(deleteSource.dataset.deleteSource); toast("URL source deleted.","success"); await renderKnowledge(); }catch(error){toast(error.message,"error");} return; }
  if(event.target.closest("[data-seed-marketplace]")){ await seedKnowledge("marketplace"); return; }
  if(event.target.closest("[data-retry-failed-sources]")){ try{ const result=await api.retryFailedKnowledgeSources({ bot_id:state.selectedBotId, agent_id:state.knowledgeFilters?.agent_id || null, category:state.knowledgeFilters?.category || null, crawl:false }); toast(`${result.retried} failed URL dikembalikan ke pending.`, "success"); await renderKnowledge(); }catch(error){ toast(error.message,"error"); } return; }
  if(event.target.closest("[data-seed-general]")){ await seedKnowledge("general"); return; }
  if(event.target.closest("[data-seed-all-agents]")){ await seedKnowledge("all"); return; }
  const seedAgent=event.target.closest("[data-seed-agent]"); if(seedAgent){ await seedKnowledge(seedAgent.dataset.seedAgent); return; }
  const kbRegenerate=event.target.closest("[data-kb-regenerate]"); if(kbRegenerate){ await regenerateKb(kbRegenerate.dataset.kbRegenerate); return; }
  const kbFaqActionTarget=event.target.closest("[data-kb-faq-action]"); if(kbFaqActionTarget){ await kbFaqAction(kbFaqActionTarget.dataset.kbFaqId,kbFaqActionTarget.dataset.kbFaqAction); return; }
  const kbFaqEdit=event.target.closest("[data-kb-faq-edit]"); if(kbFaqEdit){ await editKbFaq(kbFaqEdit.dataset.kbFaqEdit); return; }
  const kbSopActionTarget=event.target.closest("[data-kb-sop-action]"); if(kbSopActionTarget){ await kbSopAction(kbSopActionTarget.dataset.kbSopId,kbSopActionTarget.dataset.kbSopAction); return; }
  const kbSopEdit=event.target.closest("[data-kb-sop-edit]"); if(kbSopEdit){ await editKbSop(kbSopEdit.dataset.kbSopEdit); return; }
  const marketplaceUpdate=event.target.closest("[data-marketplace-update]"); if(marketplaceUpdate){ const installId=marketplaceUpdate.dataset.marketplaceUpdate; const name=prompt("Nama agent baru (opsional, kosong untuk mempertahankan)") || null; try{ await api.updateMarketplaceInstall(installId, name?.trim() || null); toast("Marketplace agent updated.","success"); await renderMarketplace(); }catch(error){ toast(error.message,"error"); } return; }
  const marketplaceUninstall=event.target.closest("[data-marketplace-uninstall]"); if(marketplaceUninstall && confirm("Uninstall this marketplace agent?")){ try{ await api.uninstallMarketplaceInstall(marketplaceUninstall.dataset.marketplaceUninstall); await onMarketplaceUninstalled(); toast("Marketplace agent uninstalled.","success"); }catch(error){ toast(error.message,"error"); } return; }
  const plan=event.target.closest("[data-checkout-plan]"); if(plan){ await checkout(plan.dataset.checkoutPlan, false); return; }
  const contactSales=event.target.closest("[data-contact-sales]"); if(contactSales){
    // P0-4 quote flow: paket custom/Enterprise → email sales (bukan checkout).
    const planKey=contactSales.dataset.contactSales;
    const email=state.salesEmail||'sales@botnesia.id';
    const subject=encodeURIComponent(`Permintaan penawaran BotNesia — paket ${planKey}`);
    const body=encodeURIComponent(`Halo tim BotNesia,\n\nSaya tertarik dengan paket ${planKey}. Mohon info penawaran & demo.\n\nNama perusahaan:\nPerkiraan volume percakapan/bulan:\nKebutuhan khusus (white-label/SSO/API/multi-tenant):\n`);
    window.location.href=`mailto:${email}?subject=${subject}&body=${body}`;
    return;
  }
  const trialPlan=event.target.closest("[data-checkout-trial]"); if(trialPlan){ await checkout(trialPlan.dataset.checkoutTrial, true); return; }
  const topup=event.target.closest("[data-topup]"); if(topup){ await topupCredits(topup.dataset.topup, topup.dataset.topupConv); return; }
  const addonBuy=event.target.closest("[data-addon-buy]"); if(addonBuy){ await buyAddon(addonBuy.dataset.addonBuy); return; }
  const laRename=event.target.closest("[data-la-rename]"); if(laRename){ const id=laRename.dataset.laRename; const name=prompt("Nama baru untuk perangkat ini:"); if(name&&name.trim()){ try{ await api.localAgentRenameDevice(id, name.trim()); bustCache("localAgent"); toast("Perangkat diganti nama.","success"); await renderAgentCenter(); }catch(err){ toast(err.message,"error"); } } return; }
  const laDiscon=event.target.closest("[data-la-device-disconnect]"); if(laDiscon){ const id=laDiscon.dataset.laDeviceDisconnect; if(confirm("Putus koneksi perangkat ini?")){ try{ await api.localAgentDeviceDisconnect(id); bustCache("localAgent"); toast("Perangkat diputus.","success"); await renderAgentCenter(); }catch(err){ toast(err.message,"error"); } } return; }
  const agTgl=event.target.closest("[data-agent-toggle]"); if(agTgl){ const key=agTgl.dataset.agentToggle; const turnOn=!agTgl.classList.contains("is-on"); try{ await api.setAgentToggle(key, turnOn); bustCache("agentToggles"); toast(turnOn?`Agent '${key}' diaktifkan.`:`Agent '${key}' dimatikan — tugasnya akan ditolak.`, turnOn?"success":"info"); await renderAgentCenter(); }catch(err){ toast(err.message,"error"); } return; }
  const laAct=event.target.closest("[data-la-act]"); if(laAct){ const raw=laAct.dataset.laAct; const i=raw.indexOf(":"); await handleComputerAccess(raw.slice(0,i), raw.slice(i+1)); return; }
  const caFiles=event.target.closest("[data-ca-files]"); if(caFiles){ const [dev,path]=caFiles.dataset.caFiles.split("::"); await caOpenFiles(dev, path); return; }
  if(action==="finance-new-invoice") await createInvoicePrompt();
  if(action==="finance-new-expense") await createExpensePrompt();
  if(action==="finance-ask-ai") await askFinanceAiPrompt();
  const financeInvoiceStatus=event.target.closest("[data-finance-invoice-status]"); if(financeInvoiceStatus){ const [id,status]=financeInvoiceStatus.dataset.financeInvoiceStatus.split(":"); try{ await api.financeUpdateInvoiceStatus(id,status); toast("Status invoice diperbarui.","success"); await renderFinance(); }catch(error){ toast(error.message,"error"); } return; }
  const financeExpenseApprove=event.target.closest("[data-finance-expense-approve]"); if(financeExpenseApprove){ const [id,approve]=financeExpenseApprove.dataset.financeExpenseApprove.split(":"); try{ await api.financeApproveExpense(id, approve==="1"); toast("Status expense diperbarui.","success"); await renderFinance(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="marketing-new-campaign") await createMarketingCampaignPrompt();
  if(action==="marketing-generate-content") await generateMarketingContentPrompt();
  const marketingApprove=event.target.closest("[data-marketing-content-approve]"); if(marketingApprove){ try{ await api.marketingApproveContent(marketingApprove.dataset.marketingContentApprove); toast("Konten disetujui.","success"); await renderMarketing(); }catch(error){ toast(error.message,"error"); } return; }
  const marketingPublish=event.target.closest("[data-marketing-content-publish]"); if(marketingPublish){ try{ await api.marketingPublishContent(marketingPublish.dataset.marketingContentPublish); toast("Konten ditandai published.","success"); await renderMarketing(); }catch(error){ toast(error.message,"error"); } return; }
  const marketingCancel=event.target.closest("[data-marketing-content-cancel]"); if(marketingCancel){ try{ await api.marketingCancelContent(marketingCancel.dataset.marketingContentCancel); toast("Konten dibatalkan.","success"); await renderMarketing(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="hr-new-candidate") await createHRCandidatePrompt();
  if(action==="hr-new-employee") await createHREmployeePrompt();
  const hrCandidateScore=event.target.closest("[data-hr-candidate-score]"); if(hrCandidateScore){ await scoreHRCandidatePrompt(hrCandidateScore.dataset.hrCandidateScore); return; }
  const hrCandidateDelete=event.target.closest("[data-hr-candidate-delete]"); if(hrCandidateDelete && confirm("Hapus kandidat ini?")){ try{ await api.hrDeleteCandidate(hrCandidateDelete.dataset.hrCandidateDelete); toast("Kandidat dihapus.","success"); await renderHR(); }catch(error){ toast(error.message,"error"); } return; }
  const hrEmployeeEvaluate=event.target.closest("[data-hr-employee-evaluate]"); if(hrEmployeeEvaluate){ await evaluateHREmployeePrompt(hrEmployeeEvaluate.dataset.hrEmployeeEvaluate); return; }
  if(action==="ops-scan"){ try{ const result=await api.opsScan(); toast(`Scan selesai: ${result.alerts_created?.length||0} alert baru.`,"success"); await renderOperations(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="ops-generate-weekly"){ try{ await api.opsGenerateReport("weekly"); toast("Weekly report dibuat.","success"); await renderOperations(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="ops-generate-monthly"){ try{ await api.opsGenerateReport("monthly"); toast("Monthly report dibuat.","success"); await renderOperations(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="executive-generate-weekly"){ try{ await api.generateExecutiveReport("weekly"); toast("Weekly executive brief dibuat.","success"); await renderExecutive(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="executive-generate-monthly"){ try{ await api.generateExecutiveReport("monthly"); toast("Monthly executive brief dibuat.","success"); await renderExecutive(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="analyze-business"){ try{ toast("Menganalisis bisnis Anda...","success"); state.businessAnalysis=await api.analyzeBusiness(); await renderExecutive(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="run-investor-demo"){ await runInvestorDemoSequence(); return; }
  if(action==="casper-demo"){ try{ toast("Submitting demo AI action to Casper Testnet…"); const r=await api.casperDemo(); const modeLabel = r.proof_mode==="real" ? "✓ Real Casper Tx" : "◎ Demo Mode"; toast(`${modeLabel}: ${r.action_summary?.slice(0,60)}…`,"success"); if(state.route==="casper-agentic-workflow") await renderCasperWorkflow(); }catch(error){ console.error("[Casper] demo error:",error); const msg=error?.data?.detail||error?.message||"Unknown error"; toast(`Casper demo failed: ${msg}`,"error"); } return; }
  if(action==="casper-new-action"){ renderCasperNewActionModal(); return; }
  const casperCard=event.target.closest(".casper-action-card"); if(casperCard && casperCard.dataset.actionId){ const id=casperCard.dataset.actionId; try{ const detail=await api.casperAction(id); const c=detail.casper||{}; el("#modal-root").innerHTML=`<div class="modal-overlay" data-dismiss-modal><div class="modal" style="max-width:560px" role="dialog"><div class="modal-head"><h3>Action Detail</h3><button class="icon-button" data-dismiss-modal>${icon("close",16)}</button></div><div style="padding:20px 24px"><p style="font-weight:600;margin:0 0 12px">${esc(detail.action_summary)}</p><table class="data-table" style="font-size:12px"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody><tr><td>Action Type</td><td>${esc(detail.action_type)}</td></tr><tr><td>Agent</td><td>${esc(detail.agent_name)}</td></tr><tr><td>Casper Status</td><td>${casperStatusBadge(c.status)}</td></tr><tr><td>Deploy Hash</td><td><code style="word-break:break-all;font-size:11px">${esc(c.deploy_hash||'—')}</code></td></tr><tr><td>Session Hash</td><td><code style="word-break:break-all;font-size:11px">${esc(c.session_hash||'—')}</code></td></tr><tr><td>Proof Mode</td><td>${esc(c.proof_mode||'—')}</td></tr><tr><td>Submitted</td><td>${c.submitted_at?formatDate(c.submitted_at,{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—'}</td></tr></tbody></table>${c.explorer_url?`<a href="${esc(c.explorer_url)}" target="_blank" rel="noopener" class="button" style="margin-top:16px;font-size:12px">View on cspr.live ↗</a>`:''}</div></div></div>`; el("#modal-root").querySelector("[data-dismiss-modal]").addEventListener("click",e=>{if(e.target.closest(".modal")&&!e.target.dataset.dismissModal)return;el("#modal-root").innerHTML="";}); }catch(err){ toast(err.message,"error"); } return; }
  if(action==="workforce-create-task") { await createWorkforceTaskPrompt(); return; }
  if(action==="workforce-scan-conflicts"){ try{ const result=await api.scanWorkforceConflicts(); toast(`Scan selesai: ${result.conflicts?.length||0} konflik, ${result.escalated?.length||0} task dieskalasi.`,"success"); await renderWorkforce(); }catch(error){ toast(error.message,"error"); } return; }
  const workforceStatus=event.target.closest("[data-workforce-status]"); if(workforceStatus){ const [id,status]=workforceStatus.dataset.workforceStatus.split(":"); try{ await api.updateWorkforceTaskStatus(id,status); toast("Task diperbarui.","success"); await renderWorkforce(); }catch(error){ toast(error.message,"error"); } return; }
  const workforceApprove=event.target.closest("[data-workforce-approve]"); if(workforceApprove){ try{ await api.approveWorkforceTask(workforceApprove.dataset.workforceApprove); toast("Task disetujui.","success"); await renderWorkforce(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="local-agent-disconnect"){ try{ await api.localAgentDisconnect(); toast("Local Agent diputus.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="local-agent-refresh"){ bustCache("localAgent"); await renderAgentCenter(); return; }
  if(action==="agent-self-test"){ await runAgentSelfTest(); return; }
  if(action==="ca-terminal-run"){ await caRunTerminal(); return; }
  if(action==="ca-agent-run"){ await caRunAgent(); return; }
  if(action==="ai-power-toggle"){
    const btn=event.target.closest("[data-action='ai-power-toggle']");
    const turningOff=btn?.classList.contains("is-on");
    if(turningOff && !confirm("Matikan AI? Semua otomatisasi & eksekusi (computer control, terminal, computer agent) akan DIJEDA sampai diaktifkan lagi.")) return;
    try{
      const res=await api.setAiPower(!turningOff);
      bustCache("aiPower");
      toast(res.enabled?"🟢 AI diaktifkan — mode otonom.":"AI dijeda — mode manual.", res.enabled?"success":"info");
      await renderAgentCenter();
    }catch(err){ toast(err.message,"error"); }
    return;
  }
  if(action==="local-agent-test"){
    const tool = document.getElementById("la-tool")?.value || "get_info";
    const resultDiv = document.getElementById("la-result");
    const g = id => (document.getElementById(id)?.value || "").trim();

    // Validasi input list_dir: tolak kalimat biasa yang bukan path
    if(tool === "list_dir"){
      const rawPath = g("la-path");
      const looksLikeQuestion = rawPath.includes("?") || rawPath.includes(" ") && !rawPath.startsWith("/") && !rawPath.startsWith("~") || (rawPath.length > 30 && !rawPath.match(/^[~/]/));
      if(looksLikeQuestion){
        if(resultDiv){
          resultDiv.style.display = "block";
          resultDiv.innerHTML = `<div style="background:var(--surface-2);border-radius:6px;border:1px solid var(--amber,#f59e0b);padding:12px 14px">
            <p style="margin:0 0 6px;font-size:13px;font-weight:600;color:var(--amber,#f59e0b)">⚠ Ini terlihat seperti pertanyaan, bukan path folder.</p>
            <p style="margin:0;font-size:12px;color:var(--text-muted)">Gunakan path seperti <code>/home/asrory</code> atau <code>~/Downloads</code>.<br>Kalau ingin bertanya ke AI, gunakan kotak <strong>Tanya Agent</strong> di bagian atas.</p>
          </div>`;
        }
        return;
      }
    }

    const args = {
      get_info:    {},
      list_dir:    { path: g("la-path") || "~/" },
      read_file:   { path: g("la-path") },
      run_command: { command: g("la-cmd") },
      find_files:  { pattern: g("la-pat") || "*", dir: g("la-dir") || "~/" },
    }[tool] || {};
    if(resultDiv){ resultDiv.style.display="block"; resultDiv.innerHTML=`<p style="font-size:12px;color:var(--text-muted);margin:0;padding:8px">⏳ Mengirim perintah...</p>`; }
    try{
      const r = await api.localAgentExecute({tool, args, timeout:30});
      if(!resultDiv) return;
      if(!r.success){
        resultDiv.innerHTML=`<p style="color:var(--red);font-size:12px;margin:0;padding:8px">❌ ${esc(r.error||'Gagal')}</p>`;
        return;
      }
      // Format hasil per tool type
      let html = "";
      if(tool==="get_info"){
        const rows = [
          ["Hostname",r.hostname],["Platform",r.platform],["OS Version",(r.platform_version||"").slice(0,60)],
          ["Python",r.python_version],["User",r.username],["Home",r.home_dir],["CWD",r.cwd],
          ["Disk Total",r.disk_total_gb!=null?r.disk_total_gb+"GB":"–"],
          ["Disk Used",r.disk_used_gb!=null?r.disk_used_gb+"GB":"–"],
          ["Disk Free",r.disk_free_gb!=null?r.disk_free_gb+"GB":"–"],
        ];
        html = `<table style="width:100%;border-collapse:collapse;font-size:12px">`
          +rows.map(([k,v])=>`<tr><td style="padding:4px 10px;color:var(--text-muted);white-space:nowrap;width:120px">${esc(k)}</td><td style="padding:4px 10px;color:var(--text);word-break:break-all">${esc(String(v||"–"))}</td></tr>`).join("")
          +`</table>`;
      } else if(tool==="list_dir"){
        const items = r.items||[];
        const basePath = (r.path||"").replace(/\/+$/,"");
        const fmtSize = s => s >= 1048576 ? (s/1048576).toFixed(1)+"MB" : s >= 1024 ? (s/1024).toFixed(1)+"KB" : s+"B";
        html = `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--border)">
          <span style="font-size:11px;color:var(--text-muted)">📂 <strong style="color:var(--text)">${esc(r.path||"–")}</strong></span>
          <span style="font-size:11px;color:var(--text-muted)">${items.length} item</span>
        </div>`
        +`<div style="max-height:260px;overflow-y:auto">`
        +items.map(it=>{
          const fullPath = basePath + "/" + it.name;
          const copyBtn = `<button onclick="navigator.clipboard.writeText(${JSON.stringify(fullPath)}).then(()=>{this.textContent='✓';setTimeout(()=>this.textContent='⎘',1000)})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:11px;padding:2px 4px;border-radius:3px" title="Salin path">⎘</button>`;
          const sizeTag = it.type==="file" ? `<span style="color:var(--text-muted);font-size:10px;white-space:nowrap">${fmtSize(it.size)}</span>` : "";
          const typeTag = `<span style="font-size:9px;color:var(--text-muted);background:var(--surface-3,var(--surface-2));padding:1px 5px;border-radius:3px">${it.type==="dir"?"folder":"file"}</span>`;
          return `<div style="display:flex;align-items:center;gap:8px;padding:5px 12px;border-bottom:1px solid var(--border);font-size:12px">
            <span style="width:16px;text-align:center">${it.type==="dir"?"📁":"📄"}</span>
            <span style="color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(fullPath)}">${esc(it.name)}</span>
            ${typeTag}${sizeTag}${copyBtn}
          </div>`;
        }).join("")
        +`</div>`;
      } else if(tool==="read_file"){
        html = `<p style="font-size:11px;color:var(--text-muted);padding:6px 10px;margin:0">${esc(r.path||"")} — ${r.size||0} bytes</p>`
          +`<pre style="margin:0;padding:10px;font-size:11px;max-height:200px;overflow:auto;white-space:pre-wrap;background:var(--surface-2)">${esc((r.content||"").slice(0,4000))}</pre>`;
      } else if(tool==="run_command"){
        html = `<p style="font-size:11px;color:var(--text-muted);padding:6px 10px;margin:0">$ ${esc(r.command||"")}</p>`
          +`<pre style="margin:0;padding:10px;font-size:11px;max-height:200px;overflow:auto;white-space:pre-wrap;background:var(--surface-2);color:${r.exit_code===0?"var(--green)":"var(--red)"}">${esc((r.stdout||r.stderr||"(kosong)").slice(0,4000))}</pre>`;
      } else if(tool==="find_files"){
        const matches = r.matches||[];
        html = `<p style="font-size:11px;color:var(--text-muted);padding:6px 10px;margin:0">Pattern: ${esc(r.pattern||"")} — ${matches.length} file ditemukan</p>`
          +`<div style="max-height:200px;overflow-y:auto">`
          +matches.map(m=>`<div style="padding:3px 10px;font-size:12px;color:var(--text)">${esc(m)}</div>`).join("")
          +`</div>`;
      } else {
        html = `<pre style="margin:0;padding:10px;font-size:11px;max-height:200px;overflow:auto;white-space:pre-wrap;background:var(--surface-2)">${esc(JSON.stringify(r,null,2))}</pre>`;
      }
      resultDiv.innerHTML = `<div style="background:var(--surface-2);border-radius:6px;border:1px solid var(--border);overflow:hidden">${html}</div>`;
      toast("Berhasil","success");
    }catch(err){ if(resultDiv) resultDiv.innerHTML=`<p style="color:var(--red);font-size:12px;margin:0;padding:8px">❌ ${esc(err.message||String(err))}</p>`; toast("Gagal kirim perintah","error"); }
    return;
  }
  const caApprove=event.target.closest("[data-ca-approve]"); if(caApprove){ try{ await api.computerAgentApprove(caApprove.dataset.caApprove); toast("Aksi Computer Agent disetujui & dijalankan.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  const caReject=event.target.closest("[data-ca-reject]"); if(caReject){ const reason=prompt("Alasan reject:","Tidak relevan"); if(!reason) return; try{ await api.computerAgentReject(caReject.dataset.caReject, reason); toast("Task ditolak.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  const laApprove=event.target.closest("[data-la-approve]"); if(laApprove){ try{ await api.localAgentApproveCommand(laApprove.dataset.laApprove); toast("Aksi Local Agent disetujui & dijalankan.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  const laReject=event.target.closest("[data-la-reject]"); if(laReject){ const reason=prompt("Alasan reject:","Tidak relevan"); if(!reason) return; try{ await api.localAgentRejectCommand(laReject.dataset.laReject, reason); toast("Perintah ditolak.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  const cmApprove=event.target.closest("[data-cm-approve]"); if(cmApprove){ try{ const result=await api.channelMessagingApprove(cmApprove.dataset.cmApprove); const sendResult=parseFeatures(result.result); toast(result.status==="sent"?"Pesan berhasil dikirim.":"Approved, tapi pengiriman gagal: "+(sendResult.error||"unknown"),result.status==="sent"?"success":"error"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  const cmReject=event.target.closest("[data-cm-reject]"); if(cmReject){ const reason=prompt("Alasan reject:","Tidak relevan"); if(!reason) return; try{ await api.channelMessagingReject(cmReject.dataset.cmReject, reason); toast("Pesan ditolak, tidak akan dikirim.","success"); await renderAgentCenter(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="learning-scan"){ try{ const result=await api.learningScan(); toast(`Scan selesai: ${result.insights?.length||0} insight diperbarui.`,"success"); await renderLearning(); }catch(error){ toast(error.message,"error"); } return; }
  const learningStatus=event.target.closest("[data-learning-status]"); if(learningStatus){ const [id,status]=learningStatus.dataset.learningStatus.split(":"); try{ await api.updateLearningInsight(id,status); toast("Insight diperbarui.","success"); await renderLearning(); }catch(error){ toast(error.message,"error"); } return; }
  const opsAlertStatus=event.target.closest("[data-ops-alert-status]"); if(opsAlertStatus){ const [id,status]=opsAlertStatus.dataset.opsAlertStatus.split(":"); try{ await api.opsUpdateAlert(id,status); toast("Alert diperbarui.","success"); await renderOperations(); }catch(error){ toast(error.message,"error"); } return; }
  if(action==="wf-new") await createWorkflowPrompt();
  if(action==="wf-back") backToWorkflowList();
  if(action==="wf-save") await saveWorkflow();
  if(action==="wf-publish") await publishWorkflow();
  if(action==="wf-unpublish") await unpublishWorkflow();
  if(action==="wf-test") await testWorkflowRun();
  const wfOpen=event.target.closest("[data-wf-open]"); if(wfOpen){ await openWorkflow(wfOpen.dataset.wfOpen); return; }
  const wfPublish=event.target.closest("[data-wf-publish]"); if(wfPublish){ try{ await api.wfPublish(wfPublish.dataset.wfPublish); toast("Workflow dipublikasikan.","success"); await renderWorkflowBuilder(); }catch(error){ toast(error.message,"error"); } return; }
  const wfUnpublish=event.target.closest("[data-wf-unpublish]"); if(wfUnpublish){ try{ await api.wfUnpublish(wfUnpublish.dataset.wfUnpublish); toast("Workflow diset ke draft.","success"); await renderWorkflowBuilder(); }catch(error){ toast(error.message,"error"); } return; }
  const wfDelete=event.target.closest("[data-wf-delete]"); if(wfDelete){ await deleteWorkflowConfirm(wfDelete.dataset.wfDelete); return; }
  const wfAdd=event.target.closest("[data-wf-add]"); if(wfAdd){ const [cat,type]=wfAdd.dataset.wfAdd.split(":"); addWorkflowNode(cat,type); return; }
  const wfDeleteNode=event.target.closest("[data-wf-delete-node]"); if(wfDeleteNode){ event.stopPropagation(); deleteWorkflowNode(wfDeleteNode.dataset.wfDeleteNode); return; }
  const wfOutDot=event.target.closest("[data-wf-out]"); if(wfOutDot){ event.stopPropagation(); startWorkflowLink(wfOutDot.dataset.wfOut,wfOutDot.dataset.wfHandle); return; }
  const wfInDot=event.target.closest("[data-wf-in]"); if(wfInDot){ event.stopPropagation(); if(state.wfLinkFrom) completeWorkflowLink(wfInDot.dataset.wfIn); return; }
  const wfDeleteEdge=event.target.closest("[data-wf-delete-edge]"); if(wfDeleteEdge){ deleteWorkflowEdge(wfDeleteEdge.dataset.wfDeleteEdge); return; }
  const wfExecution=event.target.closest("[data-wf-execution]"); if(wfExecution){ await openWorkflowExecution(wfExecution.dataset.wfExecution); return; }
  const wfNode=event.target.closest("[data-wf-node]"); if(wfNode){ selectWorkflowNode(wfNode.dataset.wfNode); return; }
});

document.addEventListener("mousedown", (event) => {
  const dragHandle = event.target.closest("[data-wf-drag]");
  if (!dragHandle || !state.wfWorkflow) return;
  const nodeId = dragHandle.dataset.wfDrag;
  const nodeEl = dragHandle.closest("[data-wf-node]");
  const canvas = el("#wf-canvas");
  if (!nodeEl || !canvas) return;
  const canvasRect = canvas.getBoundingClientRect();
  const nodeRect = nodeEl.getBoundingClientRect();
  state.wfDrag = { nodeId, offsetX: event.clientX - nodeRect.left, offsetY: event.clientY - nodeRect.top, canvasRect };
  event.preventDefault();
});

document.addEventListener("mousemove", (event) => {
  if (!state.wfDrag || !state.wfWorkflow) return;
  const { nodeId, offsetX, offsetY, canvasRect } = state.wfDrag;
  const canvas = el("#wf-canvas");
  const nodeEl = canvas?.querySelector(`[data-wf-node="${nodeId}"]`);
  if (!canvas || !nodeEl) return;
  const x = Math.max(0, event.clientX - canvasRect.left - offsetX + canvas.scrollLeft);
  const y = Math.max(0, event.clientY - canvasRect.top - offsetY + canvas.scrollTop);
  nodeEl.style.left = `${x}px`; nodeEl.style.top = `${y}px`;
  const node = (state.wfWorkflow.nodes || []).find((n) => n.id === nodeId);
  if (node) node.position = { x, y };
  updateWorkflowEdgeLines();
});

document.addEventListener("mouseup", () => { state.wfDrag = null; });

document.addEventListener("submit", async (event) => {
  if(event.target.id==="login-form"){
    event.preventDefault(); const form=event.target; const error=form.querySelector("[data-form-error]"); const data=Object.fromEntries(new FormData(form)); error.textContent="";
    try{ const result=await api.login(data.email,data.password); tokenStore.set(result.token); await boot(); }catch(err){ error.textContent=err.message; }
  }
  if(event.target.id==="register-form"){
    event.preventDefault(); const form=event.target; const error=form.querySelector("[data-form-error]"); const data=Object.fromEntries(new FormData(form)); error.textContent="";
    try{ const result=await api.register(data.org_name,data.email,data.password); tokenStore.set(result.token); await boot(); }catch(err){ error.textContent=err.message; }
  }
  if(event.target.id==="sso-form"){
    // Alur OIDC dimulai di backend; navigasi penuh ke endpoint login SSO org.
    event.preventDefault(); const form=event.target; const error=form.querySelector("[data-form-error]"); error.textContent="";
    const slug=String(new FormData(form).get("org_slug")||"").trim().toLowerCase();
    if(!slug){ error.textContent="Masukkan slug workspace Anda"; return; }
    location.href=`/auth/sso/${encodeURIComponent(slug)}/login`;
  }
  if(event.target.id==="tax-profile-form"){ event.preventDefault(); await saveTaxProfile(event.target); }
  if(event.target.id==="sso-config-form"){ event.preventDefault(); await saveSsoConfig(event.target); }
  if(event.target.id==="agent-detail-form"){ event.preventDefault(); await submitAgentDetail(event.target); }
  if(event.target.matches("[data-playground-form]")){ event.preventDefault(); await sendPlayground(event.target); }
  if(event.target.matches("[data-kb-url-form]")){ event.preventDefault(); await uploadKnowledgeUrl(event.target); }
  if(event.target.matches("[data-bulk-url-form]")){ event.preventDefault(); await bulkImportKnowledgeUrls(event.target); }
  if(event.target.matches("[data-cost-budget-form]")){ event.preventDefault(); await updateCostBudget(event.target); }
  if(event.target.matches("[data-multimedia-image-form]")){ event.preventDefault(); await generateMultimediaImage(event.target); }
  if(event.target.matches("[data-multimedia-analyze-form]")){ event.preventDefault(); await analyzeMultimediaImage(event.target); }
  if(event.target.matches("[data-multimedia-document-form]")){ event.preventDefault(); await generateMultimediaDocument(event.target); }
  if(event.target.matches("[data-agent-run-task-form]")){ event.preventDefault(); await runAgentTask(event.target); }
});

document.addEventListener("change", async (event) => {
  if(event.target.matches("[data-chat-page-bot]")){ state.selectedBotId=event.target.value; state.chatSession=null; await renderChat(); }
  if(event.target.matches("[data-conversation-bot]")){ state.selectedBotId=event.target.value; state.selectedConversationId=null; state.messages=[]; await renderConversations(); }
  if(event.target.matches("[data-analytics-bot]")){ state.selectedBotId=event.target.value; await renderAnalytics(); }
  if(event.target.matches("[data-analytics-days]")) await renderAnalytics(event.target.value);
  if(event.target.matches("[data-routing-logs-bot]")){ state.selectedBotId=event.target.value; await renderRoutingLogs(); }
  if(event.target.matches("[data-observability-days]")) await renderObservability(event.target.value);
  if(event.target.matches("[data-knowledge-bot]")){ state.selectedBotId=event.target.value; await renderKnowledge(); }
  if(event.target.matches("[data-source-status]")){ state.knowledgeFilters.status=event.target.value; await renderKnowledge(); }
  if(event.target.matches("[data-source-category]")){ state.knowledgeFilters.category=event.target.value; await renderKnowledge(); }
  if(event.target.matches("[data-source-agent]")){ state.knowledgeFilters.agent_id=event.target.value; await renderKnowledge(); }
  if(event.target.matches("[data-document-upload]")) await uploadDocument(event.target);
  if(event.target.matches("[data-marketplace-category-select]")){ state.marketplaceFilters ||= { search:"", category:"" }; state.marketplaceFilters.category=event.target.value; await renderMarketplace(); }
  if(event.target.matches("[data-knowledge-builder-bot]")){ state.selectedBotId=event.target.value; await renderKnowledgeBuilder(); }
  if(event.target.matches("[data-faq-import]")) await uploadFaqCsv(event.target);
  if(event.target.matches("[data-workflow-builder-bot]")){ state.selectedBotId=event.target.value; state.wfWorkflow=null; state.wfExecution=null; await renderWorkflowBuilder(); }
  if(event.target.matches("[data-wf-field]") && state.wfWorkflow){ state.wfWorkflow[event.target.dataset.wfField]=event.target.value; }
  if(event.target.matches("[data-multimedia-bot]")){ state.selectedBotId=event.target.value; await renderMultimedia(); }
  if(event.target.matches("[data-chat-image-upload]")) await uploadChatImage(event.target);
});

document.addEventListener("input", (event) => {
  if(event.target.matches("[data-wf-field]") && state.wfWorkflow){ state.wfWorkflow[event.target.dataset.wfField]=event.target.value; }
  if(event.target.matches("[data-wf-config-field]") && state.wfWorkflow){
    const form=event.target.closest("#wf-node-config-form");
    const node=(state.wfWorkflow.nodes||[]).find((n)=>n.id===form?.dataset.wfNodeId);
    if(node){ node.config=node.config||{}; node.config[event.target.dataset.wfConfigField]=event.target.value; }
  }
  if(event.target.matches("[data-source-search]")){
    clearTimeout(state.sourceSearchTimer);
    state.sourceSearchTimer=setTimeout(async()=>{ state.knowledgeFilters.search=event.target.value; await renderKnowledge(); },350);
  }
  if(event.target.matches("[data-marketplace-search]")){
    clearTimeout(state.marketplaceSearchTimer);
    state.marketplaceSearchTimer=setTimeout(async()=>{ state.marketplaceFilters ||= { search:"", category:"" }; state.marketplaceFilters.search=event.target.value; await renderMarketplace(); },250);
  }
  if(event.target.matches("[data-conversation-search]")){
    const query=event.target.value.toLowerCase(); els(".conversation-row").forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));
  }
  if(event.target.matches("[data-global-search]")){
    const query=event.target.value.trim().toLowerCase(); if(query.length>1){ const bot=state.bots.find(item=>item.name.toLowerCase().includes(query)); if(bot && state.route!=="agents") location.hash="agents"; }
  }
});

els("[data-auth-tab]").forEach((tab)=>tab.addEventListener("click",()=>{
  els("[data-auth-tab]").forEach(x=>x.classList.toggle("active",x===tab));
  el("#login-form").classList.toggle("hidden",tab.dataset.authTab!=="login"); el("#register-form").classList.toggle("hidden",tab.dataset.authTab!=="register");
}));
el("#mobile-scrim").addEventListener("click",closeMobileNav);
window.addEventListener("hashchange",()=>route());
window.addEventListener("botnesia:unauthorized",showAuth);
window.addEventListener("keydown",(event)=>{ if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();el('[data-global-search]')?.focus();} if(event.key==='Escape'){closeDrawer();el('#modal-root').innerHTML='';} });

// SSO callback mendarat di /ui/?sso_token=... (sukses) atau ?sso_error=... (gagal).
// Ambil token → simpan → bersihkan URL sebelum boot; tampilkan error di layar login.
function handleSsoRedirect() {
  const params = new URLSearchParams(location.search);
  const token = params.get("sso_token");
  const err = params.get("sso_error");
  if(!token && !err) return false;
  history.replaceState(null, "", location.pathname);   // strip query
  if(token){ tokenStore.set(token); return false; }
  if(err){ showAuth(); setTimeout(()=>{ const e=document.querySelector("#sso-form [data-form-error]"); if(e) e.textContent=err; },0); return true; }
  return false;
}

async function boot() {
  if(handleSsoRedirect() && !tokenStore.get()){return;}
  if(!tokenStore.get()){showAuth();return;}
  showApp(); state.route=currentRoute(); pageRoot().innerHTML=skeletonCards(4);
  try{ await loadCore(); await route(); }
  catch(error){ if(error.status===401)showAuth(); else {renderChrome();setPage(errorState(error.message));} }
}

boot();
