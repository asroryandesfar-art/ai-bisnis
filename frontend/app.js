import { api, tokenStore, settle } from "/ui/api-client.js";
import {
  icon, esc, initials, formatNumber, formatDate, relativeTime, idr, renderMarkdown,
  sidebar, topbar, pageHeader, statusBadge, metricCard, skeletonCards,
  emptyState, errorState, agentCard, activityItem, modal, agentDrawer, toast,
} from "/ui/components.js";
import { bufferSpeechSentences, segmentPauseMs } from "/ui/voice-engine.js";

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
  analyticsDays: 30, observabilityDays: 7, recorder: null, recordingStream: null, recordingChunks: [], speakReplies: true, speechRunId: 0, speechAudio: null,
  speechContext: null, speechSources: new Set(),
};

const el = (selector) => document.querySelector(selector);
const els = (selector) => [...document.querySelectorAll(selector)];
const pageRoot = () => el("#page-root");

function parseJwt() {
  try { return JSON.parse(atob(tokenStore.get().split(".")[1].replace(/-/g,"+").replace(/_/g,"/"))); }
  catch { return {}; }
}

function currentRoute() {
  const route = location.hash.replace(/^#\/?/, "").split("/")[0];
  return ["founder","dashboard","agents","chat","conversations","handoffs","analytics","routing-logs","learning","improvement","observability","costs","channels","marketplace","knowledge","kb-builder","workflow-builder","finance","marketing","hr","operations","multimedia","team","billing","security","settings"].includes(route) ? route : "dashboard";
}

function showAuth() { el("#auth-view").classList.remove("hidden"); el("#app-shell").classList.add("hidden"); }
function showApp() { el("#auth-view").classList.add("hidden"); el("#app-shell").classList.remove("hidden"); }
function closeMobileNav() { el("#sidebar").classList.remove("open"); el("#mobile-scrim").classList.remove("open"); }

function renderChrome() {
  const counts = { agents: state.bots.length, conversations: state.inboxSummary?.by_state?.unread ?? 0, team: state.team.length };
  el("#sidebar").innerHTML = sidebar({ route:state.route, org:state.org, user:state.user, counts, founderAccess:state.founderAccess });
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
function loadingPage(title, description) { setPage(`${pageHeader(title,description)}${skeletonCards(4)}<div class="grid dashboard-grid" style="margin-top:16px"><div class="skeleton" style="height:330px"></div><div class="skeleton" style="height:330px"></div></div>`); }

async function renderDashboard() {
  loadingPage("Command Center", "Monitor live AI operations, customer demand, and team workload from one place.");
  const bot = state.bots.find((item) => item.id === state.selectedBotId) || state.bots[0];
  const [analyticsResult, convResult, queueResult] = await Promise.all([
    bot ? settle("analytics", api.botAnalytics(bot.id, 30)) : Promise.resolve({ok:false}),
    bot ? settle("conversations", api.botConversations(bot.id, {limit:8})) : Promise.resolve({ok:false}),
    settle("queue", api.handoffQueue({limit:8})),
  ]);
  const analytics = analyticsResult.ok ? analyticsResult.data : null;
  const conversations = convResult.ok ? convResult.data : [];
  const queue = queueResult.ok ? queueResult.data.queue || [] : [];
  const overview = state.overview || {};
  const summary = analytics?.summary || {};
  const activeAgents = state.bots.filter((item) => item.status === "active").length;
  const resolution = summary.total_convs ? Math.max(0, Math.round((1 - (summary.handoff_count || 0) / summary.total_convs) * 100)) : 0;
  const activities = conversations.slice(0,6).map((conv) => ({
    channel:"AI", title:conv.end_user_name || conv.end_user_email || "Anonymous customer",
    description:`${conv.msg_count || 0} messages · ${conv.handoff_needed ? 'Human handoff requested' : 'Handled by AI'}`,
    time:relativeTime(conv.last_msg_at || conv.started_at),
  }));
  const metrics = [
    metricCard("Conversations", formatNumber(overview.conversations_30d ?? summary.total_convs), "Last 30 days", "chat", "trend-up"),
    metricCard("Resolution rate", `${resolution}%`, `${summary.handoff_count || 0} required handoff`, "dashboard", resolution >= 80 ? "trend-up" : ""),
    metricCard("Active agents", `${activeAgents}/${state.bots.length}`, `${state.bots.filter(b=>b.status==='training').length} in training`, "agents", "trend-up"),
    metricCard("Avg response", summary.avg_latency_ms ? `${(summary.avg_latency_ms/1000).toFixed(1)}s` : "—", "Across assistant messages", "analytics"),
  ].join("");
  const agentRows = state.bots.slice(0,5).map((agent) => `<tr data-agent-id="${esc(agent.id)}"><td><div style="display:flex;align-items:center;gap:10px"><span class="avatar">${initials(agent.name)}</span><div><span class="table-title">${esc(agent.name)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(agent.id).slice(0,8)}</div></div></div></td><td>${statusBadge(agent.status)}</td><td>${formatNumber(agent.total_convs)}</td><td>${formatNumber(agent.total_msgs)}</td><td><span class="thinking"><i></i><i></i><i></i></span></td></tr>`).join("");
  const queueHtml = queue.length ? queue.slice(0,5).map((item) => activityItem({ channel:item.priority || 'H', title:item.end_user_name || 'Escalated conversation', description:item.reason || `${item.status} · human queue`, time:relativeTime(item.created_at) })).join("") : activities.length ? activities.map(activityItem).join("") : emptyState("No live activity", "Activity appears after your agents receive conversations.");
  setPage(`${pageHeader("Command Center",`Good ${new Date().getHours()<12?'morning':new Date().getHours()<18?'afternoon':'evening'}. Here is what is happening across ${state.org?.name || 'your workspace'}.`,`<button class="button" data-action="refresh">${icon('refresh',14)} Refresh</button><button class="button button-primary" data-action="create-agent">${icon('plus',14)} Deploy agent</button>`)}<div class="grid grid-4">${metrics}</div><div class="grid dashboard-grid" style="margin-top:16px"><div class="card"><div class="card-head"><div><h3>Conversation volume</h3><span class="subtle" style="font-size:9px">30-day customer demand</span></div><span class="status-badge active"><span class="live-dot"></span>Live data</span></div><div class="card-body"><div style="height:250px"><canvas id="overview-chart"></canvas></div></div></div><div class="card"><div class="card-head"><div><h3>Live activity</h3><span class="subtle" style="font-size:9px">Latest agent and handoff events</span></div></div><div class="card-body activity-list">${queueHtml}</div></div></div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Agent fleet</h3><span class="subtle" style="font-size:9px">Operational health and workload</span></div><button class="button button-ghost" data-route="agents">View all ${icon('arrow',13)}</button></div>${state.bots.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Status</th><th>Conversations</th><th>Messages</th><th>Activity</th></tr></thead><tbody>${agentRows}</tbody></table></div>`:emptyState("No agents deployed","Create your first AI agent to start handling customer conversations.",`<button class="button button-primary" data-action="create-agent">Create agent</button>`)}</div>`);
  drawChart("overview", "#overview-chart", analytics?.daily_volume || [], "line");
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
    <div class="grid grid-4">${businessCards}</div>
    <div class="grid dashboard-grid founder-primary" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>Revenue Trend</h3><span class="subtle">Paid invoice revenue, last 30 days</span></div><span class="status-badge active">Platform-wide</span></div><div class="card-body"><div style="height:290px"><canvas id="founder-revenue-chart"></canvas></div></div></div>
      <div class="card founder-health"><div class="card-head"><div><h3>Business Health Score</h3><span class="subtle">Growth · revenue · churn · usage · retention</span></div></div><div class="card-body"><div class="health-score ${esc(health.label||'watch')}"><strong>${formatNumber(health.score)}</strong><span>/ 100</span><small>${esc(health.label||'watch')}</small></div>${componentRows}</div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Founder Insights</h3><span class="subtle">Automated signals from revenue, churn, usage, tenant cost, and agent reliability</span></div></div><div class="card-body founder-insights">${insightRows || '<span class="subtle">No material founder insights detected.</span>'}</div></div>
    <div class="grid grid-4" style="margin-top:16px">${aiCards}</div>
    <div class="grid grid-2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>Top Agents</h3><span class="subtle">30-day executions and reliability</span></div>${agentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Executions</th><th>Tokens</th><th>Failure</th></tr></thead><tbody>${agentRows}</tbody></table></div>`:emptyState("No agent usage","Agent metrics appear after AI executions.")}</div>
      <div class="card"><div class="card-head"><h3>Top Channels</h3><span class="subtle">Conversation demand by channel</span></div>${channelRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Conversations</th><th>Share</th></tr></thead><tbody>${channelRows}</tbody></table></div>`:emptyState("No channel usage","Channel metrics appear after conversations.")}</div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>High-Cost Tenants</h3><span class="subtle">Current-month AI cost concentration</span></div></div>${tenantRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tenant</th><th>AI Cost</th><th>Tokens</th></tr></thead><tbody>${tenantRows}</tbody></table></div>`:emptyState("No tenant cost","AI cost will appear after model usage.")}</div>
  `);
  drawChart("founder-revenue","#founder-revenue-chart",trend.map((row)=>({date:row.date,value:row.revenue||0})),"line");
}

async function renderAgents() {
  setPage(`${pageHeader("AI Agent Center","Manage every AI persona, prompt, channel assignment, and lifecycle state.",`<button class="button button-primary" data-action="create-agent">${icon('plus',14)} New agent</button>`)}${state.bots.length?`<div class="grid grid-3">${state.bots.map(agentCard).join('')}</div>`:emptyState("No AI agents yet","Deploy an agent and define its role, system prompt, greeting, and operating language.",`<button class="button button-primary" data-action="create-agent">Deploy first agent</button>`)}`);
}

async function renderChat() {
  if (!state.bots.length) {
    setPage(`${pageHeader("AI Chat","Ngobrol langsung dengan AI agent kamu - seperti ChatGPT atau Claude.")}${emptyState("Belum ada AI agent","Deploy agent dulu untuk mulai mengobrol.",`<button class="button button-primary" data-action="create-agent">Deploy agent</button>`)}`);
    return;
  }
  const bot = state.bots.find((item) => item.id === state.selectedBotId) || state.bots[0];
  state.selectedBotId = bot.id;
  const options = state.bots.map((item) => `<option value="${esc(item.id)}" ${item.id===bot.id?"selected":""}>${esc(item.name)}</option>`).join("");
  const body = `<div class="card chat-page"><div class="card-head"><div><h3>${esc(bot.name)}</h3><span class="subtle" style="font-size:9px">Ngobrol bebas dengan agent ini, lengkap dengan suara dan mikrofon - seperti ChatGPT atau Claude.</span></div><div style="display:flex;gap:8px;align-items:center"><select class="select" data-chat-page-bot>${options}</select><button class="button" data-action="new-chat" title="Mulai obrolan baru">${icon('plus',14)} Chat baru</button></div></div><div id="playground-messages" class="messages chat-page-messages"><div class="message"><div class="message-bubble">${esc(bot.greeting||"Halo! Ada yang bisa saya bantu?")}</div></div></div><div class="chat-page-footer"><form data-playground-form class="chat-composer" data-bot-id="${esc(bot.id)}"><label class="icon-button" title="Upload &amp; analisis gambar">${icon("upload",17)}<input type="file" data-chat-image-upload accept="image/png,image/jpeg,image/webp,image/gif" hidden></label><button class="icon-button record-button" type="button" data-action="toggle-recording" title="Record voice">${icon("mic",17)}</button><textarea name="message" placeholder="Tulis pesan untuk agent..." required></textarea><button class="icon-button" type="button" data-action="toggle-speech" title="Read AI replies">${icon("speaker",17)}</button><button class="button button-primary" type="submit" data-action="send-chat">${icon("send",14)} Kirim</button></form><div class="voice-status" data-voice-status>Mic ready · AI replies will be read aloud</div></div></div>`;
  setPage(`${pageHeader("AI Chat","Ngobrol langsung dengan AI agent kamu - seperti ChatGPT atau Claude.")}${body}`);
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
  loadingPage("Feedback Learning", "Turn real user feedback into knowledge, prompt, and workflow improvements.");
  let data, queueData;
  try { [data, queueData] = await Promise.all([api.feedbackSummary(30), api.feedbackQueue()]); }
  catch (error) { setPage(errorState(error.message)); return; }
  const listCard = (title, rows, empty, negative = false) => `<div class="card"><div class="card-head"><h3>${esc(title)}</h3></div>${rows.length?`<div class="feedback-list">${rows.map((row)=>`<div class="feedback-list-item"><strong>${esc(row.question || 'No question recorded')}</strong><p>${esc(row.comment || row.failure_reason || row.answer || '')}</p><span class="subtle">${formatNumber(row.feedback_count || row.failure_count || row.occurrence_count || 1)} ${negative?'failures':'signals'}</span></div>`).join('')}</div>`:emptyState(empty,"Feedback will appear after users rate AI answers.")}</div>`;
  const queueRows = (queueData.queue || []).map((item) => `<tr><td><span class="table-title">${esc(item.question)}</span><div class="subtle" style="margin-top:4px">${esc(item.failure_reason || '')}</div></td><td>${statusBadge(item.action_type,item.action_type)}</td><td>${formatNumber(item.occurrence_count)}</td><td>${statusBadge(item.status,item.status)}</td><td><div style="display:flex;gap:6px">${item.status==='pending'?`<button class="button" data-learning-action="in_progress" data-learning-id="${esc(item.id)}">Start</button>`:''}${item.status!=='resolved'&&item.status!=='dismissed'?`<button class="button button-primary" data-learning-action="resolved" data-learning-id="${esc(item.id)}">Resolve</button>`:''}</div></td></tr>`).join('');
  setPage(`${pageHeader("Feedback Learning","User ratings feed a governed queue for knowledge, prompt, and workflow improvements.",`<span class="status-badge active">30-day feedback window</span>`)}<div class="grid grid-4">${metricCard("Total Feedback",formatNumber(data.total_feedback),`${formatNumber(data.helpful)} helpful`,`learning`)}${metricCard("Helpful Rate",`${Number(data.helpful_rate||0).toFixed(1)}%`,"Positive user ratings","dashboard","trend-up")}${metricCard("Not Helpful",formatNumber(data.not_helpful),"Answers requiring review","observability",data.not_helpful?'trend-down':'trend-up')}${metricCard("Learning Queue",formatNumber(data.queue?.pending),`${formatNumber(data.queue?.in_progress)} in progress`,`knowledge`)}</div><div class="grid grid-2" style="margin-top:16px">${listCard("Top Positive Feedback",data.top_positive_feedback||[],"No positive feedback")}${listCard("Top Negative Feedback",data.top_negative_feedback||[],"No negative feedback",true)}${listCard("Most Failed Questions",data.most_failed_questions||[],"No failed questions",true)}${listCard("Knowledge Gaps",data.knowledge_gaps||[],"No knowledge gaps",true)}</div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Learning Queue</h3><span class="subtle">Use each item to update knowledge, prompt, or workflow</span></div></div>${queueRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Failed question</th><th>Action</th><th>Signals</th><th>Status</th><th></th></tr></thead><tbody>${queueRows}</tbody></table></div>`:emptyState("Learning queue is empty","Not Helpful ratings automatically create actionable learning items.")}</div>`);
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
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Top Issues</h3><span class="subtle">Failed answers, low confidence, negative feedback, repeated questions, and handoffs</span></div>${data.last_scan_at?`<span class="subtle mono" style="font-size:9px">Last scan: ${relativeTime(data.last_scan_at)}</span>`:''}</div>${topIssueRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Issue</th><th>Count</th></tr></thead><tbody>${topIssueRows}</tbody></table></div>`:emptyState("No issues detected","Run a scan to analyze recent conversations.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Agent Weaknesses</h3><span class="subtle mono" style="font-size:9px">QUALITY & VERIFICATION ROLLUP</span></div>${weaknessRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Conversations</th><th>Avg quality</th><th>Avg confidence</th><th>Failed verifications</th><th>Bad outcomes</th></tr></thead><tbody>${weaknessRows}</tbody></table></div>`:emptyState("No data yet","Agent performance rollups appear once conversations are analyzed.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Knowledge Gaps</h3><span class="subtle mono" style="font-size:9px">RECOMMENDED CONTENT TO ADD</span></div>${knowledgeGapRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Recommendation</th><th>Occurrences</th><th>Status</th><th></th></tr></thead><tbody>${knowledgeGapRows}</tbody></table></div>`:emptyState("No knowledge gaps detected","Run a scan to detect knowledge gaps from low-confidence answers and negative feedback.")}</div>
  <div class="card"><div class="card-head"><h3>Suggested Improvements</h3><span class="subtle mono" style="font-size:9px">PROMPT, WORKFLOW & AGENT — ADMIN DECIDES</span></div>${suggestedRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Recommendation</th><th>Occurrences</th><th>Status</th><th></th></tr></thead><tbody>${suggestedRows}</tbody></table></div>`:emptyState("No suggestions yet","AI tidak mengubah dirinya sendiri — jalankan scan untuk mendapatkan rekomendasi.")}</div>`);
}

async function renderHumanHandoff() {
  loadingPage("Human Handoff", "Monitor escalations and let human agents take over safely.");
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
      ? `<button class="button button-primary" data-claim-handoff="${esc(item.id)}">Claim</button>`
      : assigned && mine
        ? `<button class="button" data-reply-handoff="${esc(item.id)}">Reply</button><button class="button button-primary" data-resolve-handoff="${esc(item.id)}">Resolve</button>`
        : assigned ? `<span class="subtle">Owned by ${esc(item.assigned_agent_name || "another agent")}</span>` : "";
    const slaBreached = item.sla_due_at && new Date(item.sla_due_at) < new Date() && item.status !== "resolved";
    return `<tr><td><span class="table-title">${esc(item.end_user_name || item.end_user_id || "Anonymous customer")}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(String(item.conversation_id).slice(0,8))}</div></td><td>${esc(item.reason || "manual")}</td><td>${statusBadge(status,status)}</td><td>${statusBadge(item.priority || "medium")}</td><td>${esc(item.assigned_agent_name || "Unassigned")}</td><td class="${slaBreached?'trend-down':''}">${item.sla_due_at ? relativeTime(item.sla_due_at) : "—"}${slaBreached?' · breached':''}</td><td><div style="display:flex;gap:6px;align-items:center">${actions}</div></td></tr>`;
  }).join("");
  setPage(`${pageHeader("Human Handoff","AI pauses while a human owns the conversation, then resumes after resolution.",`<button class="button" data-action="refresh">${icon('refresh',14)} Refresh</button>`)}<div class="grid grid-4">${metricCard("Pending",formatNumber(summary.waiting),`${formatNumber(summary.urgent_waiting)} urgent`,`handoffs`,summary.waiting?'trend-down':'trend-up')}${metricCard("Assigned",formatNumber(summary.assigned),"Currently owned by agents","team")}${metricCard("Resolved",formatNumber(summary.resolved_24h),"Last 24 hours","dashboard","trend-up")}${metricCard("SLA Breached",formatNumber(summary.sla_breached),summary.avg_resolution_minutes_7d?`${summary.avg_resolution_minutes_7d}m avg resolution`:"No resolution data","analytics",summary.sla_breached?'trend-down':'trend-up')}</div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Handoff Queue</h3><span class="subtle">Pending, assigned, and resolved conversations</span></div><span class="status-badge active">Tenant isolated</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Customer</th><th>Reason</th><th>Status</th><th>Priority</th><th>Assigned to</th><th>SLA</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("No handoffs","AI escalations will appear here when human assistance is required.")}</div>`);
}

async function renderConversations() {
  loadingPage("Conversation Center","Unified customer conversations with AI context and human handoff visibility.");
  if (!state.selectedBotId) { setPage(pageHeader("Conversation Center","Unified inbox across every channel.") + emptyState("No agent selected","Create an agent before opening the conversation center.")); return; }
  try { await loadConversationData(); } catch (error) { setPage(errorState(error.message)); return; }
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const rows = state.conversations.map((conv) => `<div class="conversation-row ${conv.id===state.selectedConversationId?'active':''}" data-conversation-id="${esc(conv.id)}"><span class="avatar">${initials(conv.end_user_name || conv.end_user_email || 'AN')}</span><div class="truncate"><strong class="truncate">${esc(conv.end_user_name || conv.end_user_email || 'Anonymous customer')}</strong><p class="truncate">${esc(conv.channel || "website")} · ${conv.handoff_needed ? "Needs handoff" : (conv.inbox_state || "AI handled")}</p></div><span class="activity-time">${relativeTime(conv.last_msg_at || conv.started_at)}</span></div>`).join("");
  const chat = state.selectedConversationId ? renderMessagePanel() : `<div class="empty-state" style="height:100%"><span class="state-icon">${icon('chat',22)}</span><h3>Select a conversation</h3><p>Open a customer thread to review messages, latency, and knowledge sources.</p></div>`;
  setPage(`${pageHeader("Conversation Center","Review customer threads, inspect AI answers, and continue testing agents.",`<select class="select" data-conversation-bot>${options}</select>`)}<div class="conversation-layout"><aside class="conversation-list"><div class="conversation-list-head"><input class="input" style="width:100%;min-width:0" data-conversation-search placeholder="Search conversations..."></div><div data-conversation-rows>${rows || emptyState("No conversations","This agent has not received a conversation yet.")}</div></aside><section class="chat-window" id="conversation-chat">${chat}</section></div>`);
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
  state.charts[key] = new Chart(canvas, { type, data:{labels,datasets:[{data:values,borderColor:'#8b7cff',backgroundColor:type==='line'?'rgba(139,124,255,.12)':'rgba(139,124,255,.7)',fill:type==='line',tension:.38,borderWidth:2,pointRadius:0,borderRadius:5}]}, options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#697386',font:{size:9}}},y:{beginAtZero:true,grid:{color:'rgba(105,115,134,.13)'},ticks:{color:'#697386',font:{size:9}}}}} });
}

async function renderAnalytics(days = state.analyticsDays) {
  loadingPage("Analytics","Measure service quality, customer demand, and agent performance.");
  if (!state.selectedBotId) { setPage(pageHeader("Analytics","Performance insights for your AI fleet.") + emptyState("No agent data","Deploy an agent to start collecting analytics.")); return; }
  state.analyticsDays = Number(days) || 30;
  try { state.analytics = await api.botAnalytics(state.selectedBotId, state.analyticsDays); }
  catch (error) { setPage(errorState(error.message)); return; }
  const summary = state.analytics.summary || {};
  const resolution = summary.total_convs ? Math.round((1-(summary.handoff_count||0)/summary.total_convs)*100) : 0;
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const questions = state.analytics.top_questions || [];
  const questionRows = questions.map((q,index) => `<tr><td class="mono">${String(index+1).padStart(2,'0')}</td><td><span class="table-title">${esc(q.content)}</span></td><td>${formatNumber(q.frequency)}</td><td><div class="progress" style="min-width:100px"><span style="width:${Math.max(6,Math.round((q.frequency/(questions[0]?.frequency||1))*100))}%"></span></div></td></tr>`).join("");
  setPage(`${pageHeader("Analytics","Track conversation volume, AI quality, and the questions customers ask most.",`<select class="select" data-analytics-bot>${options}</select><select class="select" data-analytics-days><option value="7" ${state.analyticsDays===7?'selected':''}>7 days</option><option value="30" ${state.analyticsDays===30?'selected':''}>30 days</option><option value="90" ${state.analyticsDays===90?'selected':''}>90 days</option></select>`)}<div class="grid grid-4">${metricCard("Conversations",formatNumber(summary.total_convs),`${formatNumber(summary.total_msgs)} total messages`,"chat")}${metricCard("Resolution",`${resolution}%`,`${summary.handoff_count||0} handoffs`,"dashboard",resolution>=80?'trend-up':'')}${metricCard("Average rating",summary.avg_rating?`${Number(summary.avg_rating).toFixed(1)}/5`:'—',"Customer satisfaction","analytics")}${metricCard("AI latency",summary.avg_latency_ms?`${Math.round(summary.avg_latency_ms)}ms`:'—',"Assistant response time","agents")}</div><div class="grid grid-2" style="margin-top:16px"><div class="card"><div class="card-head"><h3>Daily conversations</h3><span class="status-badge active">Live database</span></div><div class="card-body"><div style="height:300px"><canvas id="analytics-chart"></canvas></div></div></div><div class="card"><div class="card-head"><h3>Service quality</h3></div><div class="card-body"><div class="usage-row"><div class="usage-row-head"><span>AI resolution</span><b>${resolution}%</b></div><div class="progress"><span style="width:${resolution}%"></span></div></div><div class="usage-row"><div class="usage-row-head"><span>Customer rating</span><b>${summary.avg_rating||0}/5</b></div><div class="progress"><span style="width:${Math.min(100,Number(summary.avg_rating||0)*20)}%"></span></div></div><div class="usage-row"><div class="usage-row-head"><span>Automated coverage</span><b>${Math.max(0,100-Math.round((summary.handoff_count||0)/(summary.total_convs||1)*100))}%</b></div><div class="progress"><span style="width:${Math.max(0,100-Math.round((summary.handoff_count||0)/(summary.total_convs||1)*100))}%"></span></div></div></div></div></div><div class="card" style="margin-top:16px"><div class="card-head"><h3>Top customer questions</h3><span class="subtle mono" style="font-size:9px">FROM REAL CONVERSATIONS</span></div>${questionRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>#</th><th>Question</th><th>Frequency</th><th>Demand</th></tr></thead><tbody>${questionRows}</tbody></table></div>`:emptyState("No question data","Top questions appear after customers interact with this agent.")}</div>`);
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
  setPage(`${pageHeader("Routing Logs","Intent Router decisions per pesan — intent, selected agent, confidence, dan handoff status.",`<select class="select" data-routing-logs-bot>${options}</select>`)}<div class="card"><div class="card-head"><h3>Routing decisions</h3><span class="subtle mono" style="font-size:9px">LAST ${logs.length} MESSAGES</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Customer</th><th>Message</th><th>Intent</th><th>Selected Agent</th><th>Confidence</th><th>Handoff</th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("No routing data","Kirim beberapa pesan ke agent ini untuk mengisi routing log.")}</div>`);
}

async function renderObservability(days = state.observabilityDays) {
  state.observabilityDays = Number(days) || 7;
  loadingPage("AI Observability","Inspect agent health, latency, token usage, and request traces.");
  let data;
  try { data = await api.observabilitySummary(state.observabilityDays); }
  catch (error) { setPage(errorState(error.message)); return; }
  const metrics = data.metrics || {};
  const agentRows = (data.agents || []).map((agent) => { const latest=agent.last_status||'unknown'; const healthy=latest==='success'||latest==='skipped'; const label=healthy?'healthy':(latest==='running'?'running':'failed'); const detail=agent.failures?` title="${formatNumber(agent.failures)} historical failure(s) in this window"`:''; return `<tr><td><span class="table-title mono">${esc(agent.agent_name)}</span></td><td>${formatNumber(agent.executions)}</td><td><span${detail}>${statusBadge(healthy?'active':latest,label)}</span></td><td>${Math.round(agent.average_latency_ms || 0)}ms</td><td>${formatNumber(agent.total_tokens)}</td><td>${agent.last_seen_at ? relativeTime(agent.last_seen_at) : '—'}</td></tr>`; }).join("");
  const traceRows = (data.traces || []).map((trace) => `<tr data-observability-trace="${esc(trace.id)}"><td class="mono">${esc(String(trace.id).slice(0,8))}</td><td><span class="table-title trace-question">${esc(trace.user_question)}</span></td><td>${statusBadge(trace.status === 'success' ? 'active' : trace.status, trace.status)}</td><td>${formatNumber(trace.agent_count)} agents</td><td>${trace.duration_ms || 0}ms</td><td>${formatNumber(trace.total_tokens)}</td><td>${relativeTime(trace.started_at)}</td></tr>`).join("");
  setPage(`${pageHeader("AI Observability","Every request and agent lifecycle is recorded for operational debugging.",`<select class="select" data-observability-days><option value="1" ${state.observabilityDays===1?'selected':''}>24 hours</option><option value="7" ${state.observabilityDays===7?'selected':''}>7 days</option><option value="30" ${state.observabilityDays===30?'selected':''}>30 days</option><option value="90" ${state.observabilityDays===90?'selected':''}>90 days</option></select>`)}<div class="grid grid-3 observability-metrics">${metricCard("Active Agents",formatNumber(metrics.active_agents),"Currently executing","agents")}${metricCard("Failed Agents",formatNumber(metrics.failed_agents),"Executions in selected window","observability",metrics.failed_agents?'trend-down':'trend-up')}${metricCard("Average Latency",`${Math.round(metrics.average_latency_ms||0)}ms`,"Per agent execution","analytics")}${metricCard("Token Usage",formatNumber(metrics.total_tokens),`${formatNumber(metrics.prompt_tokens)} prompt · ${formatNumber(metrics.completion_tokens)} completion`,"billing")}${metricCard("Success Rate",`${Number(metrics.success_rate||0).toFixed(1)}%`,"Completed executions","dashboard","trend-up")}${metricCard("Error Rate",`${Number(metrics.error_rate||0).toFixed(1)}%`,"Failed executions","observability",metrics.error_rate?'trend-down':'trend-up')}</div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Agent health</h3><span class="subtle">Latency, failures, and token consumption per agent</span></div></div>${agentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Executions</th><th>Status</th><th>Avg latency</th><th>Tokens</th><th>Last seen</th></tr></thead><tbody>${agentRows}</tbody></table></div>`:emptyState("No execution data","Send a message to an AI agent to create the first trace.")}</div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Agent Trace Viewer</h3><span class="subtle">Open a request to inspect its complete execution chain</span></div></div>${traceRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Trace</th><th>User question</th><th>Status</th><th>Chain</th><th>Latency</th><th>Tokens</th><th>Started</th></tr></thead><tbody>${traceRows}</tbody></table></div>`:emptyState("No traces yet","Request traces will appear here after an agent handles a message.")}</div>`);
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
  setPage(`${pageHeader("Cost Intelligence","FinOps visibility for every tenant, channel, conversation, agent, and model.",`<span class="status-badge active">USD estimated provider cost</span>`)}<div class="grid grid-4">${metricCard("Monthly Cost",usd(data.monthly_cost),`${formatNumber(data.monthly_calls)} model calls`,"costs")}${metricCard("Daily Cost",usd(data.daily_cost),"Cost since 00:00 UTC","analytics")}${metricCard("Projected Month",usd(data.projected_monthly_cost),"Run-rate projection","billing")}${metricCard("Monthly Tokens",formatNumber(data.monthly_tokens),"Prompt + completion","observability")}</div><div class="grid grid-2" style="margin-top:16px">${budgetPanel}<div class="card"><div class="card-head"><div><h3>Daily AI Cost</h3><span class="subtle">Last 30 days</span></div></div><div class="card-body"><div style="height:270px"><canvas id="cost-daily-chart"></canvas></div></div></div></div><div class="grid grid-2" style="margin-top:16px">${costBreakdownTable(data.cost_by_agent,"Cost By Agent")}${costBreakdownTable(data.cost_by_model,"Cost By Model")}${costBreakdownTable(data.cost_by_channel,"Cost By Channel")}${costBreakdownTable(data.cost_by_conversation,"Cost By Conversation")}</div><div class="grid grid-2" style="margin-top:16px"><div class="card"><div class="card-head"><h3>Cost By Tenant</h3><span class="subtle">Current tenant scope</span></div>${tenantRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tenant</th><th>Cost</th><th>Tokens</th></tr></thead><tbody>${tenantRows}</tbody></table></div>`:emptyState("No tenant cost","No model usage recorded this month.")}</div><div class="card"><div class="card-head"><h3>Model Routing</h3><span class="subtle">Simple → economy · Complex → quality</span></div>${routingRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Task</th><th>Model</th><th>Requests</th></tr></thead><tbody>${routingRows}</tbody></table></div>`:emptyState("No routing data","Model route decisions appear after AI requests.")}</div></div>`);
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
    const color = template.primary_color || "#8b7cff";
    return `<article class="card card-hover marketplace-agent-card" style="--agent-color:${esc(color)}">
      <div class="marketplace-agent-top"><span class="marketplace-agent-icon">${icon(template.icon || 'agents',18)}</span><div><h3>${esc(template.name)}</h3><p>${esc(template.category)}</p></div></div>
      <p class="marketplace-agent-desc">${esc(template.description)}</p>
      <div class="marketplace-agent-meta"><span>★ ${Number(template.rating || 0).toFixed(1)}</span><span>${formatNumber(template.install_count || 0)} installs</span><span>v${esc(template.version || '1.0.0')}</span></div>
      <div class="marketplace-tool-tags">${tools || '<span>knowledge base</span><span>prompt</span><span>workflow</span>'}</div>
      ${starters ? `<ul class="marketplace-starters">${starters}</ul>` : ''}
      <div class="marketplace-agent-actions"><span class="status-badge ${installed ? 'active' : 'ready'}">${installed ? 'Installed' : 'Available'}</span><div>${installed ? `<button class="button" data-marketplace-update="${esc(install.id)}">Update</button><button class="button button-danger" data-marketplace-uninstall="${esc(install.id)}">Uninstall</button>` : `<button class="button button-primary" data-action="marketplace-install" data-marketplace-install="${esc(template.key)}">Install</button>`}</div></div>
    </article>`;
  };

  const categoryCards = categories.map((category) => `<button class="marketplace-category-card ${filters.category===category.name?'active':''}" data-marketplace-category="${esc(category.name)}" style="--category-color:${esc(category.color || '#8b7cff')}"><span>${icon(category.icon || 'agents',18)}</span><strong>${esc(category.name)}</strong><small>${formatNumber(category.template_count || 0)} agents</small></button>`).join("");
  const installedRows = installs.map((item) => `<tr><td><span class="table-title">${esc(item.template_name)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(item.template_key)} · ${esc(item.template_version || '1.0.0')}</div></td><td>${esc(item.template_category || 'Business')}</td><td>${statusBadge(item.bot_status || 'inactive', item.bot_status || 'inactive')}</td><td>${esc(item.bot_name || '—')}</td><td>${relativeTime(item.installed_at)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap"><button class="button" data-marketplace-update="${esc(item.id)}">Update</button><button class="button button-danger" data-marketplace-uninstall="${esc(item.id)}">Uninstall</button></div></td></tr>`).join('');

  const actions = `<div class="marketplace-controls"><label class="search-box marketplace-search">${icon('search',15)}<input data-marketplace-search value="${esc(filters.search)}" placeholder="Search 100+ agents"></label><select class="select" data-marketplace-category-select><option value="">All categories</option>${categories.map((cat)=>`<option value="${esc(cat.name)}" ${filters.category===cat.name?'selected':''}>${esc(cat.name)}</option>`).join('')}</select><button class="button" data-marketplace-clear>Clear</button></div>`;
  const hero = `<section class="marketplace-hero"><div><span class="eyebrow">AGENT STORE</span><h2>Shopify-style app store for BotNesia agents</h2><p>Install a ready-to-use professional agent, add isolated knowledge, and let Supervisor Routing choose the best specialist behind BotNesia Assistant.</p></div><div class="marketplace-hero-stats"><strong>${formatNumber(analytics.template_count || templates.length)}</strong><span>Professional templates</span><strong>${formatNumber(analytics.category_count || categories.length)}</strong><span>Categories</span></div></section>`;
  const metrics = `<div class="grid grid-4">${metricCard("Templates",formatNumber(analytics.template_count || templates.length),"Professional agent catalog","marketplace")}${metricCard("Installed",formatNumber(analytics.installed_count || installs.length),"One-click tenant installs","agents")}${metricCard("Avg rating",Number(analytics.average_rating || 0).toFixed(2),"Marketplace quality score","analytics")}${metricCard("Total installs",formatNumber(analytics.total_install_count || 0),"Popularity across templates","dashboard")}</div>`;
  const featuredSection = featured.length ? `<section class="marketplace-section"><div class="section-head"><div><h3>Featured agents</h3><p>Best starting points for most businesses</p></div><span class="status-badge active">${featured.length} featured</span></div><div class="marketplace-agent-grid">${featured.map(marketplaceAgentCard).join('')}</div></section>` : '';
  const recommendedSection = recommended.length ? `<section class="marketplace-section"><div class="section-head"><div><h3>Recommended agents</h3><p>General AI, Supervisor, and high-utility templates</p></div></div><div class="marketplace-agent-grid compact">${recommended.map(marketplaceAgentCard).join('')}</div></section>` : '';
  const trendingSection = trending.length ? `<section class="marketplace-section"><div class="section-head"><div><h3>Trending agents</h3><p>Sorted by install counter and popularity</p></div></div><div class="marketplace-agent-grid compact">${trending.map(marketplaceAgentCard).join('')}</div></section>` : '';
  const catalogSection = `<section class="marketplace-section"><div class="section-head"><div><h3>Agent catalog</h3><p>${formatNumber(filteredTemplates.length)} matching templates. Knowledge, prompt, and FAQ stay isolated per installed agent.</p></div></div>${filteredTemplates.length ? `<div class="marketplace-agent-grid">${filteredTemplates.map(marketplaceAgentCard).join('')}</div>` : emptyState("No matching agents","Try another search or category filter.")}</section>`;

  setPage(`${pageHeader("Agent Marketplace","Choose an agent, install it in one click, then add agent-specific knowledge.",actions)}${hero}${metrics}<section class="marketplace-section"><div class="section-head"><div><h3>Categories</h3><p>Browse by business function and industry</p></div></div><div class="marketplace-category-grid"><button class="marketplace-category-card ${!filters.category?'active':''}" data-marketplace-category=""><span>${icon('marketplace',18)}</span><strong>All categories</strong><small>${formatNumber(templates.length)} agents</small></button>${categoryCards}</div></section>${featuredSection}${recommendedSection}${trendingSection}${catalogSection}<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Installed agents</h3><span class="subtle" style="font-size:9px">Manage tenant-specific installs</span></div></div>${installedRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Template</th><th>Category</th><th>Status</th><th>Bot</th><th>Installed</th><th>Action</th></tr></thead><tbody>${installedRows}</tbody></table></div>` : emptyState("No installed agents","Install a template to create the first reusable AI agent.")}</div>`);
}

async function renderKnowledge() {
  loadingPage("Knowledge Seeder","Manage trusted source documents and URL ingestion queues.");
  if (!state.selectedBotId) { setPage(pageHeader("Knowledge Seeder","Ground agents with company documents and trusted URLs.") + emptyState("No agent available","Create an agent before uploading knowledge.")); return; }
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
  const categoryOptions = `<option value="">All categories</option>` + categories.map((cat)=>`<option value="${esc(cat)}" ${filters.category===cat?'selected':''}>${esc(cat)}</option>`).join("");
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
  setPage(`${pageHeader("Knowledge Seeder","Import trusted URL seeds per agent, crawl in a throttled background queue, and monitor indexing status.",`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="select" data-knowledge-bot>${options}</select><label class="button button-primary">${icon('upload',14)} Upload document<input type="file" data-document-upload accept=".pdf,.docx,.txt,.csv,.md,.markdown" hidden></label></div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${metricCard("Total URLs",formatNumber(stats.total),"Queued for selected agent","knowledge")}${metricCard("Pending",formatNumber(stats.pending),"Waiting for crawler","observability")}${metricCard("Crawling",formatNumber(stats.crawling),"Current batch","refresh")}${metricCard("Failed",formatNumber(stats.failed),"Retry failed in batch","learning",stats.failed?'trend-down':'')}</div>
  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="card"><div class="card-head"><div><h3>Bulk URL Importer</h3><span class="subtle">One URL per line. Optional category is auto-set to custom.</span></div></div><form data-bulk-url-form class="card-body" style="display:grid;gap:10px"><textarea class="input" name="urls" rows="8" placeholder="https://platform.openai.com/docs\nhttps://docs.python.org/3"></textarea><div style="display:flex;gap:8px;justify-content:flex-end"><button class="button button-primary" type="submit">${icon('link',14)} Import URLs</button></div></form></div>
    <div class="card"><div class="card-head"><div><h3>Agent Knowledge Seeder</h3><span class="subtle">Import seed JSON without crawling everything at once.</span></div></div><div class="card-body" style="display:flex;gap:8px;flex-wrap:wrap"><button class="button button-primary" data-seed-marketplace>${icon('marketplace',14)} Seed Marketplace 1000</button><button class="button" data-retry-failed-sources>${icon('refresh',14)} Retry failed</button><button class="button" data-seed-general>${icon('knowledge',14)} General AI</button><button class="button" data-seed-all-agents>All agent seeds</button>${seedButtons}</div></div>
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>URL per Agent</h3><span class="subtle">Marketplace knowledge isolation by agent_id</span></div></div>${agentStatusRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Agent</th><th>Total</th><th>Pending</th><th>Crawling</th><th>Indexed</th><th>Failed</th></tr></thead><tbody>${agentStatusRows}</tbody></table></div>`:emptyState("No agent URL queue","Seed marketplace URLs to see per-agent status.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Source Status Tracking</h3><span class="subtle">Tenant and agent isolated URL ingestion queue</span></div><div style="display:flex;gap:8px;flex-wrap:wrap"><input class="input" data-source-search value="${esc(filters.search||'')}" placeholder="Search URL" style="min-width:180px"><select class="select" data-source-status>${statusOptions}</select><select class="select" data-source-agent>${agentOptions}</select><select class="select" data-source-category>${categoryOptions}</select><button class="button" data-action="refresh">${icon('refresh',14)} Refresh</button></div></div>${sourceRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>URL</th><th>Category</th><th>Status</th><th>Priority</th><th>Updated</th><th></th></tr></thead><tbody>${sourceRows}</tbody></table></div>`:emptyState("No seeded URLs","Import URLs manually or use the seed buttons to populate this agent.")}</div>
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
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Documents</h3><span class="subtle" style="font-size:9px">Status pemrosesan Auto Knowledge Builder</span></div></div>${documentRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Categories</th><th>Tags</th><th>KB Status</th><th></th></tr></thead><tbody>${documentRows}</tbody></table></div>`:emptyState("Belum ada dokumen","Upload dokumen di Knowledge Base untuk memulai Auto Knowledge Builder.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Generated FAQ</h3><span class="subtle" style="font-size:9px">${overview.faqs?.suggested||0} suggested · ${overview.faqs?.approved||0} approved · ${overview.faqs?.rejected||0} rejected</span></div></div>${faqRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>FAQ</th><th>Category</th><th>Status</th><th></th></tr></thead><tbody>${faqRows}</tbody></table></div>`:emptyState("Belum ada FAQ","FAQ hasil AI akan muncul di sini setelah dokumen diproses.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Generated SOP</h3><span class="subtle" style="font-size:9px">${overview.sops?.suggested||0} suggested · ${overview.sops?.approved||0} approved · ${overview.sops?.rejected||0} rejected</span></div></div>${sopRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>SOP</th><th>Category</th><th>Status</th><th></th></tr></thead><tbody>${sopRows}</tbody></table></div>`:emptyState("Belum ada SOP","SOP hasil AI akan muncul di sini setelah dokumen diproses.")}</div>
  <div class="card"><div class="card-head"><h3>Missing topics</h3></div><div class="card-body" style="padding:16px">${missingTopics}</div></div>`);
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
  <div class="card">${rows
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

  setPage(`${pageHeader("Finance Center", "Generate invoice, catat expense, dan pantau revenue/profit/cashflow bisnis Anda — semua aksi tercatat di audit log.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="finance-ask-ai">${icon("chat", 14)} Tanya AI Finance</button>
      <button class="button" data-action="finance-new-expense">Catat Expense</button>
      <button class="button button-primary" data-action="finance-new-invoice">${icon("plus", 14)} Buat Invoice</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Revenue (30d)", formatIDR(dashboard.revenue_30d_idr), "Income tercatat", "finance", "trend-up")}
    ${metricCard("Profit (30d)", formatIDR(dashboard.profit_30d_idr), "Revenue - expense", "finance", dashboard.profit_30d_idr >= 0 ? "trend-up" : "trend-down")}
    ${metricCard("MRR / ARR", `${formatIDR(dashboard.mrr_idr)} / ${formatIDR(dashboard.arr_idr)}`, `Churn ${dashboard.churn_pct}%`, "finance")}
    ${metricCard("Invoice Pending", formatNumber(dashboard.pending_invoices_count), `${formatIDR(dashboard.pending_invoices_amount_idr)} · ${formatNumber(dashboard.overdue_invoices_count)} overdue`, "finance", dashboard.overdue_invoices_count ? "trend-down" : "trend-up")}
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Invoices</h3></div>${invoiceRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Invoice</th><th>Jumlah</th><th>Status</th><th>Jatuh tempo</th><th></th></tr></thead><tbody>${invoiceRows}</tbody></table></div>` : emptyState("Belum ada invoice", "Buat invoice pertama untuk pelanggan Anda.")}</div>
  <div class="card"><div class="card-head"><h3>Expenses</h3></div>${expenseRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Expense</th><th>Jumlah</th><th>Status</th><th>Tanggal</th><th></th></tr></thead><tbody>${expenseRows}</tbody></table></div>` : emptyState("Belum ada expense", "Catat pengeluaran bisnis untuk laporan profit yang akurat.")}</div>`);
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

  const contentRows = state.marketingContent.map((item) => `<tr>
    <td><span class="table-title">${esc(item.title || item.platform)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc((item.body || "").slice(0, 80))}${(item.body || "").length > 80 ? "…" : ""}</div></td>
    <td>${statusBadge("default", item.platform)}</td>
    <td>${statusBadge(item.status, item.status)}</td>
    <td>${item.scheduled_at ? relativeTime(item.scheduled_at) : "—"}</td>
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

  setPage(`${pageHeader("Marketing Center", "AI generate konten per platform, jadwalkan di content calendar — publikasi ke platform tetap manual oleh tim Anda, engagement dicatat manual dari Insights masing-masing platform.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="marketing-new-campaign">Campaign Baru</button>
      <button class="button button-primary" data-action="marketing-generate-content">${icon("plus", 14)} Generate Konten</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Campaign Aktif", formatNumber(dashboard.active_campaigns), "Sedang berjalan", "marketing")}
    ${metricCard("Konten Draft/Scheduled", `${formatNumber(dashboard.content_draft)} / ${formatNumber(dashboard.content_scheduled)}`, `${formatNumber(dashboard.content_due_now)} siap tayang`, "marketing", dashboard.content_due_now ? "trend-down" : "trend-up")}
    ${metricCard("Siap Publish / Published", `${formatNumber(dashboard.content_ready_to_publish)} / ${formatNumber(dashboard.content_published)}`, "Total konten", "marketing")}
    ${metricCard("Engagement (30d)", formatNumber(Object.values(dashboard.engagement_30d || {}).reduce((a, b) => a + b, 0)), "Likes+comments+shares+views+clicks", "marketing", "trend-up")}
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Content Calendar</h3></div>${contentRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Konten</th><th>Platform</th><th>Status</th><th>Jadwal</th><th></th></tr></thead><tbody>${contentRows}</tbody></table></div>` : emptyState("Belum ada konten", "Generate konten pertama untuk campaign Anda.")}</div>
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

  const candidateRows = state.hrCandidates.map((c) => `<tr>
    <td><span class="table-title">${esc(c.name)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(c.position_applied || "")}</div></td>
    <td>${c.score != null ? c.score : "—"}</td>
    <td>${statusBadge(c.status, c.status)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-hr-candidate-score="${esc(c.id)}">Score (AI)</button>
      <button class="button button-danger" data-hr-candidate-delete="${esc(c.id)}">Hapus</button>
    </div></td>
  </tr>`).join("");

  const employeeRows = state.hrEmployees.map((e) => `<tr>
    <td><span class="table-title">${esc(e.full_name)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(e.position || "")}${e.department ? " · " + esc(e.department) : ""}</div></td>
    <td>${statusBadge(e.status, e.status)}</td>
    <td><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="button" data-hr-employee-evaluate="${esc(e.id)}">Generate Evaluasi (AI)</button>
    </div></td>
  </tr>`).join("");

  setPage(`${pageHeader("HR Center", "AI membantu screening CV, scoring kandidat, draft evaluasi, dan rekomendasi training — keputusan akhir (hire/finalisasi evaluasi) tetap di tangan tim Anda.",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="hr-new-candidate">Kandidat Baru</button>
      <button class="button button-primary" data-action="hr-new-employee">${icon("plus", 14)} Karyawan Baru</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Kandidat Baru", formatNumber(dashboard.candidates_by_status?.new || 0), "Belum diproses", "hr")}
    ${metricCard("Kandidat Screened", formatNumber(dashboard.candidates_by_status?.screened || 0), "Sudah di-score AI", "hr")}
    ${metricCard("Karyawan Aktif", formatNumber(dashboard.employees_by_status?.active || 0), "Total aktif", "hr", "trend-up")}
    ${metricCard("Avg Skor Evaluasi (90d)", dashboard.avg_evaluation_score_90d != null ? dashboard.avg_evaluation_score_90d : "—", `${formatNumber(dashboard.pending_training_recommendations)} training pending`, "hr")}
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Kandidat</h3></div>${candidateRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Kandidat</th><th>Skor</th><th>Status</th><th></th></tr></thead><tbody>${candidateRows}</tbody></table></div>` : emptyState("Belum ada kandidat", "Tambahkan kandidat untuk mulai proses screening.")}</div>
  <div class="card"><div class="card-head"><h3>Karyawan</h3></div>${employeeRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Karyawan</th><th>Status</th><th></th></tr></thead><tbody>${employeeRows}</tbody></table></div>` : emptyState("Belum ada karyawan", "Tambahkan karyawan untuk mulai tracking performa.")}</div>`);
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

  setPage(`${pageHeader("Operations Center", "AI memonitor health tenant, workflow, dan SLA, lalu menyusun laporan — alert butuh tindak lanjut manusia (acknowledge/resolve).",
    `<div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="button" data-action="ops-scan">${icon("refresh", 14)} Run Scan</button>
      <button class="button" data-action="ops-generate-weekly">Generate Weekly Report</button>
      <button class="button button-primary" data-action="ops-generate-monthly">Generate Monthly Report</button>
    </div>`)}
  <div class="grid grid-4" style="margin-bottom:16px">
    ${metricCard("Health Score", `${health.score ?? "—"}`, health.label || "—", "operations", healthTrend)}
    ${metricCard("Workflow Success Rate", `${dashboard.workflow_health?.success_rate_pct ?? "—"}%`, `${formatNumber(dashboard.workflow_health?.total_executions || 0)} eksekusi (7d)`, "operations")}
    ${metricCard("SLA Breach Rate", `${dashboard.sla_health?.breach_rate_pct ?? "—"}%`, `${formatNumber(dashboard.sla_health?.total_handoffs || 0)} handoff (7d)`, "operations", dashboard.sla_health?.breach_rate_pct > 10 ? "trend-down" : "trend-up")}
    ${metricCard("Open Alerts", formatNumber(state.opsAlerts.length), `${formatNumber(dashboard.open_alerts_by_severity?.critical || 0)} critical`, "operations", state.opsAlerts.length ? "trend-down" : "trend-up")}
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Alerts</h3></div>${alertRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Alert</th><th>Waktu</th><th></th></tr></thead><tbody>${alertRows}</tbody></table></div>` : emptyState("Tidak ada alert terbuka", "Jalankan scan untuk mendeteksi masalah operasional.")}</div>
  <div class="card"><div class="card-head"><h3>Laporan</h3></div>${reportRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tipe</th><th>Ringkasan</th><th>Dibuat</th></tr></thead><tbody>${reportRows}</tbody></table></div>` : emptyState("Belum ada laporan", "Generate laporan weekly/monthly pertama Anda.")}</div>`);
}

function parseFeatures(value) {
  if (value && typeof value === "object") return value;
  try { return JSON.parse(value || "{}"); } catch { return {}; }
}

function formatFileSize(bytes) { const n=Number(bytes||0); if(n<1024)return `${n} B`; if(n<1048576)return `${(n/1024).toFixed(1)} KB`; return `${(n/1048576).toFixed(1)} MB`; }

async function renderTeam() {
  loadingPage("Team & Tenants","Manage workspace identity, team members, roles, and permissions.");
  const [teamResult, rolesResult, meResult] = await Promise.all([settle("team",api.team()),settle("roles",api.roles()),settle("me",api.rbacMe())]);
  state.team = teamResult.ok ? teamResult.data.team || [] : state.team;
  state.roles = rolesResult.ok ? rolesResult.data.roles || [] : [];
  state.rbac = meResult.ok ? meResult.data : state.rbac;
  const rows = state.team.map((member) => `<tr><td><div style="display:flex;align-items:center;gap:10px"><span class="avatar">${initials(member.full_name||member.email)}</span><div><span class="table-title">${esc(member.full_name||'Unnamed user')}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(member.email)}</div></div></div></td><td>${(member.roles||[]).map(role=>`<span class="status-badge ready" style="margin-right:4px">${esc(role)}</span>`).join('')||'—'}</td><td>${statusBadge(member.is_active?'active':'inactive',member.is_active?'Active':'Disabled')}</td><td>${relativeTime(member.last_login_at)}</td><td><button class="icon-button" data-team-user="${esc(member.id)}" data-action="manage-member">${icon('more')}</button></td></tr>`).join("");
  const permissions = (state.rbac?.permissions||[]).slice(0,8).map(item=>`<span class="status-badge ready">${esc(item)}</span>`).join(' ');
  setPage(`${pageHeader("Team & Tenants","Control who can manage agents, conversations, billing, and platform settings.",`<button class="button" data-action="export-team">Export members</button><button class="button button-primary" data-action="invite-member">${icon('plus',14)} Add member</button>`)}<div class="grid grid-3" style="margin-bottom:16px">${metricCard("Workspace",state.org?.name||'—',state.org?.slug||'tenant',"dashboard")}${metricCard("Team members",formatNumber(state.team.length),`${state.team.filter(x=>x.is_active).length} active accounts`,"team")}${metricCard("Your roles",formatNumber(state.rbac?.roles?.length),(state.rbac?.roles||[]).join(', ')||'No role',"settings")}</div><div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Tenant workspace</h3><span class="subtle mono" style="font-size:9px">DATABASE ISOLATED</span></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Tenant</th><th>Billing status</th><th>Plan</th><th>Members</th></tr></thead><tbody><tr><td><span class="table-title">${esc(state.org?.name||'Workspace')}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(state.org?.slug||'tenant')}</div></td><td>${statusBadge(state.org?.billing_status||'active',state.org?.billing_status||'active')}</td><td>${esc(state.org?.plan||'free')}</td><td>${formatNumber(state.team.length)}</td></tr></tbody></table></div></div><div class="grid dashboard-grid"><div class="card"><div class="card-head"><h3>Workspace members</h3><span class="subtle mono" style="font-size:9px">TENANT ISOLATED</span></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Member</th><th>Roles</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("No team members","Team members appear after users join this tenant.")}</div><div class="card"><div class="card-head"><h3>Your access</h3></div><div class="card-body"><p class="muted" style="font-size:11px;line-height:1.6;margin-top:0">Permissions are enforced by the existing BotNesia RBAC layer.</p><div style="display:flex;gap:6px;flex-wrap:wrap">${permissions||'<span class="subtle">No permissions returned.</span>'}</div></div></div></div>`);
}

async function renderBilling() {
  loadingPage("Billing & Usage","Monitor subscription limits and manage the plan for this workspace.");
  const [plansResult, subResult, usageResult, invoicesResult] = await Promise.all([settle("plans",api.plans()),settle("subscription",api.subscription()),settle("usage",api.usage()),settle("invoices",api.invoices())]);
  state.plans = plansResult.ok ? plansResult.data.plans || [] : [];
  state.subscription = subResult.ok ? subResult.data : state.subscription;
  state.usage = usageResult.ok ? usageResult.data.usage || {} : {};
  state.invoices = invoicesResult.ok ? invoicesResult.data.invoices || [] : [];
  const currentKey = state.subscription?.subscription?.plan_key || state.org?.plan || 'free';
  const planCards = state.plans.map((plan) => {
    const featureConfig = parseFeatures(plan.features);
    const highlights = Array.isArray(featureConfig.highlights) ? featureConfig.highlights : null;
    const features = highlights || (Array.isArray(featureConfig) ? featureConfig : Object.keys(featureConfig).filter((key) => featureConfig[key]));
    const description = plan.description || featureConfig.description || 'Paket BotNesia';
    const isCustomPricing = !!featureConfig.custom_pricing;
    const priceBlock = isCustomPricing
      ? `<div class="plan-price">Custom <small>/ Hubungi Sales</small></div>`
      : `<div class="plan-price">${idr(plan.price_monthly_idr)} <small>/ bulan</small></div>`;
    const extraStats = highlights ? '' : `<li>${plan.max_agents===-1?'Unlimited':plan.max_agents} AI agents</li><li>${plan.max_conversations_per_month===-1?'Unlimited':formatNumber(plan.max_conversations_per_month)} conversations</li>`;
    const buttonLabel = plan.key===currentKey ? 'Current plan' : (isCustomPricing ? 'Hubungi Sales' : 'Choose plan');
    return `<article class="card plan-card ${plan.key===currentKey?'featured':''}"><span class="eyebrow">${plan.key===currentKey?'CURRENT PLAN':'AVAILABLE PLAN'}</span><h3>${esc(plan.name)}</h3><p class="subtle" style="font-size:10px;min-height:32px">${esc(description)}</p>${priceBlock}<ul class="feature-list">${features.slice(0,12).map(feature=>`<li>${esc(String(feature).replace(/_/g,' '))}</li>`).join('')}${extraStats}</ul><button class="button ${plan.key===currentKey?'':'button-primary'}" ${plan.key===currentKey?'disabled':''} data-checkout-plan="${esc(plan.key)}">${buttonLabel}</button></article>`;
  }).join("");
  const usageRows = Object.entries(state.usage||{}).map(([key,item]) => { const limit=Number(item.limit); const pct=limit===-1?10:Math.min(100,Math.round((Number(item.used||0)/Math.max(1,limit))*100)); return `<div class="usage-row"><div class="usage-row-head"><span>${esc(key.replace(/_/g,' '))}</span><b>${formatNumber(item.used)} / ${limit===-1?'∞':formatNumber(limit)}</b></div><div class="progress"><span style="width:${pct}%"></span></div></div>`; }).join("");
  const invoiceRows = state.invoices.map(inv=>`<tr><td class="table-title mono">${esc(inv.invoice_number)}</td><td>${esc(inv.description||'Subscription')}</td><td>${idr(inv.amount_idr)}</td><td>${statusBadge(inv.status,inv.status)}</td><td>${formatDate(inv.created_at)}</td></tr>`).join("");
  setPage(`${pageHeader("Billing & Usage","Plans and limits are read directly from the BotNesia subscription system.",`<span class="status-badge active">${esc(currentKey)} · ${esc(state.subscription?.subscription?.status||state.org?.billing_status||'active')}</span>`)}<div class="grid grid-3">${planCards||emptyState("Plans unavailable","Run the platform schema migration to provision subscription plans.")}</div><div class="grid grid-2" style="margin-top:16px"><div class="card"><div class="card-head"><h3>Current usage</h3></div><div class="card-body">${usageRows||emptyState("Usage unavailable","No usage dimensions returned.")}</div></div><div class="card"><div class="card-head"><h3>Recent invoices</h3></div>${invoiceRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Invoice</th><th>Description</th><th>Amount</th><th>Status</th><th>Date</th></tr></thead><tbody>${invoiceRows}</tbody></table></div>`:emptyState("No invoices","Paid and open invoices will appear here.")}</div></div>`);
}

async function renderSecurity() {
  loadingPage("Security Dashboard","Audit logs, active sessions, suspicious logins, and API key management.");
  const dashResult = await settle("security", api.securityDashboard());
  if (!dashResult.ok) { setPage(`${pageHeader("Security Dashboard","Audit logs, active sessions, suspicious logins, and API key management.")}${errorState(dashResult.error.message)}`); return; }
  state.security = dashResult.data;
  const sec = state.security;

  const sessionRows = (sec.active_sessions||[]).map((session) => `<tr><td><span class="table-title">${esc(session.user_email)}</span><div class="subtle" style="font-size:9px;margin-top:3px">${esc(session.user_agent||'—')}</div></td><td class="mono">${esc(session.ip_address||'—')}</td><td>${session.is_suspicious?statusBadge('error','Suspicious'):statusBadge('active','Normal')}</td><td>${relativeTime(session.last_seen_at)}</td><td>${formatDate(session.expires_at)}</td><td><button class="button button-danger" data-revoke-session="${esc(session.id)}">Revoke</button></td></tr>`).join("");

  const auditRows = (sec.audit_logs||[]).map((log) => `<tr><td>${formatDate(log.created_at,{hour:'2-digit',minute:'2-digit'})}</td><td>${esc(log.actor_email||'system')}</td><td><span class="status-badge ready">${esc(log.action)}</span></td><td>${esc(log.resource_type)}${log.resource_id?` <span class="subtle mono" style="font-size:9px">${esc(String(log.resource_id).slice(0,8))}</span>`:''}</td><td class="mono">${esc(log.ip_address||'—')}</td></tr>`).join("");

  const eventRows = (sec.security_events||[]).map((event) => `<tr><td>${formatDate(event.created_at,{hour:'2-digit',minute:'2-digit'})}</td><td>${esc(event.actor_email||'system')}</td><td><span class="status-badge error">${esc(event.action)}</span></td><td class="mono">${esc(event.ip_address||'—')}</td></tr>`).join("");

  const apiKeyRows = (sec.api_keys||[]).map((key) => `<tr><td><span class="table-title">${esc(key.name)}</span><div class="subtle mono" style="font-size:9px;margin-top:3px">${esc(key.key_prefix)}...</div></td><td>${(key.scopes||[]).map((scope)=>`<span class="status-badge ready" style="margin-right:4px">${esc(scope)}</span>`).join('')||'—'}</td><td>${formatNumber(key.usage_count)}</td><td>${relativeTime(key.last_used_at)}</td><td>${key.expires_at?formatDate(key.expires_at):'Never'}</td><td>${statusBadge(key.is_active?'active':'inactive',key.is_active?'Active':'Revoked')}</td><td style="display:flex;gap:6px;flex-wrap:wrap">${key.is_active?`<button class="button" data-rotate-api-key="${esc(key.id)}">Rotate</button><button class="button button-danger" data-revoke-api-key="${esc(key.id)}">Revoke</button>`:'—'}</td></tr>`).join("");

  const scan = state.securityScan;
  const scoreCard = metricCard("Security Score", scan?`${scan.score}/100`:'—', scan?`${scan.findings_count} findings (last scan)`:'Run a scan to compute', "security");
  const findingsCard = scan?.findings?.length ? `<div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Latest scan findings</h3></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Severity</th><th>Category</th><th>Finding</th><th>Recommendation</th></tr></thead><tbody>${scan.findings.map((finding)=>`<tr><td>${statusBadge(finding.severity==='critical'||finding.severity==='high'?'error':finding.severity==='medium'?'pending':'active',finding.severity)}</td><td>${esc(finding.category)}</td><td>${esc(finding.title)}</td><td class="subtle" style="font-size:10px">${esc(finding.recommendation)}</td></tr>`).join('')}</tbody></table></div></div>` : '';

  setPage(`${pageHeader("Security Dashboard","Enterprise security posture: RBAC, audit trail, sessions, suspicious logins, and API keys.",`<button class="button button-primary" data-action="security-scan">${icon('refresh',14)} Run security scan</button><button class="button" data-action="create-api-key">${icon('plus',14)} New API key</button>`)}
  <div class="grid grid-4" style="margin-bottom:16px">${scoreCard}${metricCard("Active sessions",formatNumber(sec.active_sessions_count),"Across your workspace","team")}${metricCard("Suspicious logins",formatNumber(sec.suspicious_sessions_count),"New IP detected (30 days)","security")}${metricCard("Active API keys",formatNumber(sec.active_api_keys_count),`${formatNumber((sec.api_keys||[]).length)} total`,"settings")}</div>
  ${findingsCard}
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>Active sessions</h3><span class="subtle mono" style="font-size:9px">SESSION MANAGEMENT</span></div>${sessionRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>User</th><th>IP address</th><th>Status</th><th>Last seen</th><th>Expires</th><th></th></tr></thead><tbody>${sessionRows}</tbody></table></div>`:emptyState("No active sessions","Sessions appear here after users log in.")}</div>
  <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>API keys</h3><span class="subtle mono" style="font-size:9px">ROTATION & USAGE TRACKING</span></div>${apiKeyRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Key</th><th>Scopes</th><th>Usage</th><th>Last used</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${apiKeyRows}</tbody></table></div>`:emptyState("No API keys","Create an API key to access BotNesia programmatically.")}</div>
  <div class="grid grid-2"><div class="card"><div class="card-head"><h3>Security events</h3><span class="subtle mono" style="font-size:9px">LOGIN FAILURES & ALERTS</span></div>${eventRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Event</th><th>IP</th></tr></thead><tbody>${eventRows}</tbody></table></div>`:emptyState("No security events","Failed logins, permission denials, and suspicious logins appear here.")}</div><div class="card"><div class="card-head"><h3>Audit log</h3><span class="subtle mono" style="font-size:9px">RECENT ACTIVITY</span></div>${auditRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>IP</th></tr></thead><tbody>${auditRows}</tbody></table></div>`:emptyState("No audit log entries","All login, billing, and configuration changes are tracked here.")}</div></div>`);
}

function showCreateApiKey() {
  el("#modal-root").innerHTML = modal({title:"Create API key",body:`<form id="create-api-key-form"><div class="form-grid"><label class="field full"><span>Name</span><input name="name" required placeholder="e.g. Integration server"></label><label class="field"><span>Expires in (days)</span><input name="expires_in_days" type="number" min="1" placeholder="Never"></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-create-api-key">Create key</button>`});
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
  loadingPage("Channels", "One AI system for WhatsApp, Telegram, Instagram, Facebook Messenger, and Website Chat.");
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
      return `<article class="card channel-card"><div class="card-head"><div class="channel-title"><span class="activity-symbol">WA</span><div><h3>WhatsApp</h3><span class="subtle">Meta Embedded Signup · no token copy-paste</span></div></div>${statusBadge(status,status.charAt(0).toUpperCase()+status.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Connected agents</span><strong>${formatNumber(connected.length)}</strong></div>${accountRows}<div class="channel-actions"><button class="button button-primary" data-action="connect-whatsapp">Connect agent</button>${accountActions}</div></div></article>`;
    }
    const item = state.channels.find((row)=>row.channel_type===key && row.status!=="disconnected") || state.channels.find((row)=>row.channel_type===key);
    if (key === "facebook" || key === "instagram") {
      const oauth = state.metaOAuth || {};
      const selected = oauth.selected || {};
      const channelSelection = selected[key] || {};
      const connected = item?.status === "connected";
      const assetName = key === "facebook" ? channelSelection.page_name : channelSelection.instagram_username;
      const oauthStatus = oauth.status === "reauth_required" ? "error" : (connected ? "connected" : "disconnected");
      return `<article class="card channel-card"><div class="card-head"><div class="channel-title"><span class="activity-symbol">${initials(label)}</span><div><h3>${esc(label)}</h3><span class="subtle">Meta OAuth · tenant-owned account</span></div></div>${statusBadge(oauthStatus,oauthStatus.charAt(0).toUpperCase()+oauthStatus.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Account</span><strong>${esc(assetName||item?.display_name||"Not selected")}</strong></div><div class="channel-stat"><span>Token expiry</span><strong>${oauth.token_expires_at?formatDate(oauth.token_expires_at):"Not connected"}</strong></div><div class="channel-stat"><span>Agent</span><strong>${esc(state.bots.find((bot)=>bot.id===(item?.bot_id||channelSelection.bot_id))?.name||"Not assigned")}</strong></div><div class="channel-actions">${connected?`<button class="button" data-action="refresh-meta-token">Refresh access</button><button class="button button-danger" data-disconnect-channel="${esc(item.id)}">Disconnect</button>`:`<button class="button button-primary" data-connect-meta-channel="${key}">${key==='facebook'?'Hubungkan Facebook':'Hubungkan Instagram Business'}</button>`}</div></div></article>`;
    }
    const status = item?.status || "disconnected";
    return `<article class="card channel-card"><div class="card-head"><div class="channel-title"><span class="activity-symbol">${initials(label)}</span><div><h3>${esc(label)}</h3><span class="subtle">${esc(provider)}</span></div></div>${statusBadge(status,status.charAt(0).toUpperCase()+status.slice(1))}</div><div class="card-body"><div class="channel-stat"><span>Last activity</span><strong>${relativeTime(item?.last_activity_at||item?.connected_at)}</strong></div><div class="channel-stat"><span>Message count</span><strong>${formatNumber(item?.message_count||0)}</strong></div><div class="channel-stat"><span>Connection</span><strong>${esc(item?.display_name||"Not configured")}</strong></div><div class="channel-actions">${status==="connected"?`<button class="button" data-action="refresh-channel-health">Health check</button><button class="button button-danger" data-disconnect-channel="${esc(item.id)}">Disconnect</button>`:`<button class="button button-primary" data-connect-channel-type="${key}">Connect ${esc(label)}</button>`}</div></div></article>`;
  }).join("");
  const a=state.channelAnalytics||{};
  const usage=(a.channel_usage||[]).map((row)=>`<tr><td><span class="table-title">${esc(row.channel)}</span></td><td>${formatNumber(row.messages)}</td><td>${formatNumber(row.active_users)}</td></tr>`).join("");
  setPage(`${pageHeader("Omni Channel Manager","All inbound messages use the same Supervisor, Knowledge Base, Memory, and specialist agents.",`<button class="button" data-action="refresh-channel-health">${icon('refresh',14)} Health check</button><button class="button button-primary" data-action="connect-channel">${icon('plus',14)} Connect other channel</button>`)}<div class="grid grid-4"><article class="card metric-card"><div class="metric-label">Total Messages</div><div class="metric-value">${formatNumber(a.total_messages)}</div><div class="metric-meta">Last 30 days</div></article><article class="card metric-card"><div class="metric-label">Active Users</div><div class="metric-value">${formatNumber(a.active_users)}</div><div class="metric-meta">Unique channel users</div></article><article class="card metric-card"><div class="metric-label">Response Time</div><div class="metric-value">${Number(a.response_time_ms||0).toFixed(0)}ms</div><div class="metric-meta">Average channel delivery</div></article><article class="card metric-card"><div class="metric-label">Conversion Rate</div><div class="metric-value">${Number(a.conversion_rate||0).toFixed(1)}%</div><div class="metric-meta">Marked conversions</div></article></div><div class="grid channel-grid" style="margin-top:16px">${cards}</div><div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Channel Usage</h3><span class="subtle">Per-tenant message and active-user distribution</span></div></div>${usage?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Channel</th><th>Messages</th><th>Active Users</th></tr></thead><tbody>${usage}</tbody></table></div>`:emptyState("No channel traffic","Usage appears after the first inbound message.")}</div>`);
  const params=new URLSearchParams(location.search);
  if(params.get("meta_oauth")==="success"){
    const channel=params.get("meta_channel")||"facebook";
    history.replaceState(null,"",location.pathname+"#channels");
    setTimeout(()=>showMetaAssetSelection(channel),0);
  } else if(params.get("meta_oauth") && params.get("meta_oauth")!=="success"){
    toast("Meta login was not completed.","error");
    history.replaceState(null,"",location.pathname+"#channels");
  }
}

async function renderSettings() {
  loadingPage("Platform Settings","Configure security posture and workspace connectivity.");
  const integrationResult = await settle("integrations",api.integrations());
  state.integrations = integrationResult.ok ? integrationResult.data : {};
  const integrationCards = `<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Gmail</h3><span class="subtle" style="font-size:9px">OAuth inbox processing</span></div>${statusBadge(state.integrations?.gmail?.connected?'active':'inactive',state.integrations?.gmail?.connected?'Connected':'Not connected')}</div><div class="card-body"><p class="subtle">${esc(state.integrations?.gmail?.email||'No Gmail account connected')}</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="button button-primary" data-action="gmail-start">${state.integrations?.gmail?.connected?'Reconnect Gmail':'Connect Gmail'}</button>${state.integrations?.gmail?.connected?'<button class="button" data-action="gmail-map">Map to agent</button><button class="button" data-action="gmail-poll">Poll now</button><button class="button button-danger" data-disconnect-integration="gmail">Disconnect</button>':''}</div></div></div>`;
  const systemStatus = `<div class="grid grid-2"><div class="card"><div class="card-head"><h3>System status</h3></div><div class="card-body"><div class="setting-row"><div><strong>FastAPI backend</strong><p class="subtle">Application and REST APIs</p></div>${statusBadge(state.health?.db?'active':'error',state.health?.db?'Connected':'Unavailable')}</div><div class="setting-row"><div><strong>PostgreSQL</strong><p class="subtle">Tenant and business data</p></div>${statusBadge(state.health?.schema?'active':'error',state.health?.schema?'Schema ready':'Schema issue')}</div><div class="setting-row"><div><strong>AI provider</strong><p class="subtle">${esc(state.health?.ai?.model||'Not configured')}</p></div>${statusBadge(state.health?.ai?.configured?'active':'error',state.health?.ai?.configured?'Ready':'Not configured')}</div></div></div><div class="card"><div class="card-head"><h3>Workspace identity</h3></div><div class="card-body"><div class="form-grid"><label class="field full"><span>Organization</span><input value="${esc(state.org?.name||'')}" readonly></label><label class="field"><span>Tenant slug</span><input value="${esc(state.org?.slug||'')}" readonly></label><label class="field"><span>Application URL</span><input value="${esc(location.origin)}" readonly></label></div></div></div></div>`;
  const sessionCard = `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Session & security</h3></div><div class="card-body" style="display:flex;align-items:center;justify-content:space-between;gap:16px"><div><strong>Current authenticated session</strong><p class="subtle" style="margin:5px 0 0;font-size:10px">JWT authentication and RBAC permissions are enforced by FastAPI.</p></div><button class="button button-danger" data-action="logout">Sign out</button></div></div>`;
  setPage(`${pageHeader("Platform Settings","Manage deployment connectivity, integrations, and workspace security.",`<button class="button" data-action="security-scan">Run security scan</button>`)}${systemStatus}${integrationCards}${sessionCard}`);
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

function settingRowStyles() { if (!document.getElementById('dynamic-setting-style')) { const style=document.createElement('style'); style.id='dynamic-setting-style'; style.textContent='.setting-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 0;border-bottom:1px solid var(--line)}.setting-row:last-child{border-bottom:0}.setting-row p{margin:4px 0 0;font-size:10px}'; document.head.appendChild(style); } }

function showInviteMember() {
  const roleOptions = (state.roles.length ? state.roles : [{key:"admin",name:"Admin"},{key:"manager",name:"Manager"},{key:"agent",name:"Agent"},{key:"viewer",name:"Viewer"}])
    .filter((role) => role.key !== "owner").map((role) => `<option value="${esc(role.key)}">${esc(role.name || role.key)}</option>`).join("");
  el("#modal-root").innerHTML = modal({title:"Add workspace member",body:`<form id="invite-member-form"><div class="form-grid"><label class="field"><span>Full name</span><input name="full_name" required></label><label class="field"><span>Role</span><select name="role_key">${roleOptions}</select></label><label class="field full"><span>Email</span><input type="email" name="email" required></label><label class="field full"><span>Temporary password</span><input type="password" name="password" minlength="8" required></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-invite-member">Add member</button>`});
}

async function submitInviteMember() {
  const form=el("#invite-member-form"); if(!form || !form.reportValidity()) return;
  const button=el("[data-action=submit-invite-member]"); button.disabled=true;
  try { await api.inviteMember(Object.fromEntries(new FormData(form))); el("#modal-root").innerHTML=""; toast("Team member added.","success"); await renderTeam(); renderChrome(); }
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
  el("#modal-root").innerHTML=modal({title:"Connect business channel",body:`<form id="connect-channel-form"><div class="form-grid"><label class="field"><span>Agent</span><select name="bot_id">${bots}</select></label><label class="field"><span>Channel</span><select name="channel_type">${options}</select></label><label class="field full"><span>Display name</span><input name="display_name" required placeholder="Main customer channel"></label><label class="field full"><span>Allowed website domain</span><input name="domain" placeholder="https://example.com (Website Chat only)"></label><p class="subtle full">Provider credentials are managed securely by the platform operator. Customers never need to paste Telegram, Instagram, or Facebook tokens.</p></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-connect-channel">Connect</button>`});
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
    await api.installMarketplaceTemplate(templateKey, botName);
    el("#modal-root").innerHTML = "";
    toast("Agent marketplace installed.", "success");
    await renderMarketplace();
    await loadCore();
  } catch (error) {
    toast(error.message, "error");
    if (button) { button.disabled = false; button.textContent = "Install agent"; }
  }
}

function showCreateAgent() {
  el("#modal-root").innerHTML = modal({title:"Deploy new AI agent",body:`<form id="create-agent-form"><div class="form-grid"><label class="field"><span>Agent name</span><input name="name" required placeholder="Customer Success Agent"></label><label class="field"><span>Language</span><select name="language"><option value="id">Bahasa Indonesia</option><option value="en">English</option></select></label><label class="field full"><span>Greeting</span><textarea name="greeting" style="min-height:80px" placeholder="Halo! Ada yang bisa saya bantu?"></textarea></label><label class="field full"><span>System prompt</span><textarea name="system_prompt" placeholder="You are a professional customer success agent..."></textarea></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-create-agent">Deploy agent</button>`});
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

async function route() {
  state.route = currentRoute(); renderChrome(); closeMobileNav(); settingRowStyles();
  const renderers = {founder:renderFounder,dashboard:renderDashboard,agents:renderAgents,chat:renderChat,conversations:renderConversations,handoffs:renderHumanHandoff,analytics:renderAnalytics,"routing-logs":renderRoutingLogs,learning:renderFeedbackLearning,improvement:renderImprovement,observability:renderObservability,costs:renderCostIntelligence,channels:renderChannels,marketplace:renderMarketplace,knowledge:renderKnowledge,"kb-builder":renderKnowledgeBuilder,"workflow-builder":renderWorkflowBuilder,finance:renderFinance,marketing:renderMarketing,hr:renderHR,operations:renderOperations,multimedia:renderMultimedia,team:renderTeam,billing:renderBilling,security:renderSecurity,settings:renderSettings};
  await renderers[state.route]();
}

async function submitCreateAgent() {
  const form = el("#create-agent-form"); if (!form || !form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  const button = el('[data-action="submit-create-agent"]'); button.disabled=true; button.textContent="Deploying...";
  try {
    await api.createBot({ name:data.name, language:data.language, greeting:data.greeting || "Halo! Ada yang bisa saya bantu?", system_prompt:data.system_prompt || null, primary_color:"#8b7cff", status:"active" });
    state.bots = await api.bots(); state.selectedBotId = state.bots[0]?.id || null; el("#modal-root").innerHTML=""; renderChrome(); toast("AI agent deployed successfully.","success"); await route();
  } catch (error) { toast(error.message,"error"); button.disabled=false; button.textContent="Deploy agent"; }
}

async function submitAgentDetail(form) {
  const id=form.dataset.agentId; const data=Object.fromEntries(new FormData(form));
  const button=form.querySelector('button[type="submit"]'); button.disabled=true; button.textContent="Saving...";
  try { await api.updateBot(id,data); state.bots=await api.bots(); closeDrawer(); renderChrome(); toast("Agent configuration saved.","success"); await route(); }
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

async function checkout(planKey) {
  if(!confirm(`Continue with the ${planKey} plan?`))return;
  try { const result=await api.checkout(planKey,"monthly","local"); if(result.redirect_url) location.href=result.redirect_url; else { toast("Subscription activated.","success"); await renderBilling(); } }
  catch(error){ toast(error.message,"error"); }
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
  if(action==="toggle-sidebar"){ el("#sidebar").classList.toggle("open"); el("#mobile-scrim").classList.toggle("open"); }
  if(action==="logout"){ tokenStore.clear(); showAuth(); }
  if(action==="refresh") await route();
  if(action==="create-agent") showCreateAgent();
  if(action==="submit-create-agent") await submitCreateAgent();
  if(action==="marketplace-install") showMarketplaceInstall(event.target.closest("[data-marketplace-install]")?.dataset.marketplaceInstall);
  if(action==="submit-marketplace-install") await submitMarketplaceInstall();
  if(action==="close-modal") {
    const closeTarget = event.target.closest('[data-action="close-modal"]');
    if(closeTarget?.matches('button') || event.target === closeTarget) el("#modal-root").innerHTML="";
  }
  if(action==="close-drawer") closeDrawer();
  if(action==="notifications") await showNotifications();
  if(action==="gmail-start") await startGmail();
  if(action==="gmail-map") await mapGmail();
  if(action==="gmail-poll") await pollGmail();
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
  const marketplaceUninstall=event.target.closest("[data-marketplace-uninstall]"); if(marketplaceUninstall && confirm("Uninstall this marketplace agent?")){ try{ await api.uninstallMarketplaceInstall(marketplaceUninstall.dataset.marketplaceUninstall); toast("Marketplace agent uninstalled.","success"); await renderMarketplace(); }catch(error){ toast(error.message,"error"); } return; }
  const plan=event.target.closest("[data-checkout-plan]"); if(plan) await checkout(plan.dataset.checkoutPlan);
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
  if(event.target.id==="agent-detail-form"){ event.preventDefault(); await submitAgentDetail(event.target); }
  if(event.target.matches("[data-playground-form]")){ event.preventDefault(); await sendPlayground(event.target); }
  if(event.target.matches("[data-kb-url-form]")){ event.preventDefault(); await uploadKnowledgeUrl(event.target); }
  if(event.target.matches("[data-bulk-url-form]")){ event.preventDefault(); await bulkImportKnowledgeUrls(event.target); }
  if(event.target.matches("[data-cost-budget-form]")){ event.preventDefault(); await updateCostBudget(event.target); }
  if(event.target.matches("[data-multimedia-image-form]")){ event.preventDefault(); await generateMultimediaImage(event.target); }
  if(event.target.matches("[data-multimedia-analyze-form]")){ event.preventDefault(); await analyzeMultimediaImage(event.target); }
  if(event.target.matches("[data-multimedia-document-form]")){ event.preventDefault(); await generateMultimediaDocument(event.target); }
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

async function boot() {
  if(!tokenStore.get()){showAuth();return;}
  showApp(); state.route=currentRoute(); pageRoot().innerHTML=skeletonCards(4);
  try{ await loadCore(); await route(); }
  catch(error){ if(error.status===401)showAuth(); else {renderChrome();setPage(errorState(error.message));} }
}

boot();
