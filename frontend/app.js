import { api, tokenStore, settle } from "/ui/api-client.js";
import {
  icon, esc, initials, formatNumber, formatDate, relativeTime, idr, renderMarkdown,
  sidebar, topbar, pageHeader, statusBadge, metricCard, skeletonCards,
  emptyState, errorState, agentCard, activityItem, modal, agentDrawer, toast,
} from "/ui/components.js";

const state = {
  route: "dashboard", health: null, org: null, user: null, bots: [], overview: null,
  inboxSummary: null, team: [], roles: [], rbac: null, subscription: null,
  usage: null, plans: [], invoices: [], selectedBotId: null, selectedConversationId: null,
  conversations: [], messages: [], analytics: null, costIntelligence: null, documents: [], channels: [], integrations: null,
  kbOverview: null, kbFaqs: [], kbSops: [],
  chatSession: null, charts: {}, loading: false,
  analyticsDays: 30, observabilityDays: 7, recorder: null, recordingStream: null, recordingChunks: [], speakReplies: true, speechRunId: 0, speechAudio: null,
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
  return ["dashboard","agents","chat","conversations","handoffs","analytics","learning","observability","costs","marketplace","knowledge","kb-builder","team","billing","settings"].includes(route) ? route : "dashboard";
}

function showAuth() { el("#auth-view").classList.remove("hidden"); el("#app-shell").classList.add("hidden"); }
function showApp() { el("#auth-view").classList.add("hidden"); el("#app-shell").classList.remove("hidden"); }
function closeMobileNav() { el("#sidebar").classList.remove("open"); el("#mobile-scrim").classList.remove("open"); }

function renderChrome() {
  const counts = { agents: state.bots.length, conversations: state.inboxSummary?.by_state?.unread ?? 0, team: state.team.length };
  el("#sidebar").innerHTML = sidebar({ route:state.route, org:state.org, user:state.user, counts });
  el("#topbar").innerHTML = topbar({ route:state.route, health:state.health });
}

async function loadCore() {
  state.loading = true;
  const results = await Promise.all([
    settle("health", api.health()), settle("org", api.org()), settle("bots", api.bots()),
    settle("overview", api.dashboardOverview()), settle("inboxSummary", api.inboxSummary()),
    settle("rbac", api.rbacMe()), settle("team", api.team()), settle("subscription", api.subscription()),
  ]);
  for (const result of results) if (result.ok) state[result.label] = result.data;
  state.bots = state.bots || [];
  state.team = state.team?.team || state.team || [];
  state.subscription = state.subscription || null;
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
  const body = `<div class="card chat-page"><div class="card-head"><div><h3>${esc(bot.name)}</h3><span class="subtle" style="font-size:9px">Ngobrol bebas dengan agent ini, lengkap dengan suara dan mikrofon - seperti ChatGPT atau Claude.</span></div><div style="display:flex;gap:8px;align-items:center"><select class="select" data-chat-page-bot>${options}</select><button class="button" data-action="new-chat" title="Mulai obrolan baru">${icon('plus',14)} Chat baru</button></div></div><div id="playground-messages" class="messages chat-page-messages"><div class="message"><div class="message-bubble">${esc(bot.greeting||"Halo! Ada yang bisa saya bantu?")}</div></div></div><div class="chat-page-footer"><form data-playground-form class="chat-composer" data-bot-id="${esc(bot.id)}"><button class="icon-button record-button" type="button" data-action="toggle-recording" title="Record voice">${icon("mic",17)}</button><textarea name="message" placeholder="Tulis pesan untuk agent..." required></textarea><button class="icon-button" type="button" data-action="toggle-speech" title="Read AI replies">${icon("speaker",17)}</button><button class="button button-primary" type="submit" data-action="send-chat">${icon("send",14)} Kirim</button></form><div class="voice-status" data-voice-status>Mic ready · AI replies will be read aloud</div></div></div>`;
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
  const messages = state.messages.map((message) => `<div class="message ${message.role==='user'?'user':''}"><div class="message-bubble">${message.role==='user'?esc(message.content).replace(/\n/g,'<br>'):renderMarkdown(message.content)}<div class="message-meta">${esc(message.role)} · ${formatDate(message.created_at,{hour:'2-digit',minute:'2-digit'})}${message.latency_ms?` · ${message.latency_ms}ms`:''}</div>${message.role==='assistant'&&!String(message.model||'').startsWith('human:')&&!String(message.model||'').includes('human-handoff')?feedbackControls(message.id,state.selectedConversationId,message.feedback_rating):''}</div></div>`).join("");
  return `<header class="chat-head"><div style="display:flex;align-items:center;gap:10px"><span class="avatar">${initials(conv?.end_user_name || 'AN')}</span><div><strong>${esc(conv?.end_user_name || conv?.end_user_email || 'Anonymous customer')}</strong><div style="margin-top:4px">${statusBadge(conv?.handoff_needed?'handoff':'resolved',conv?.handoff_needed?'Needs handoff':'AI handled')}</div></div></div><button class="icon-button">${icon('more')}</button></header><div class="messages">${messages || emptyState("No messages","This conversation does not contain messages.")}</div>`;
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

async function renderObservability(days = state.observabilityDays) {
  state.observabilityDays = Number(days) || 7;
  loadingPage("AI Observability","Inspect agent health, latency, token usage, and request traces.");
  let data;
  try { data = await api.observabilitySummary(state.observabilityDays); }
  catch (error) { setPage(errorState(error.message)); return; }
  const metrics = data.metrics || {};
  const agentRows = (data.agents || []).map((agent) => `<tr><td><span class="table-title mono">${esc(agent.agent_name)}</span></td><td>${formatNumber(agent.executions)}</td><td>${statusBadge(agent.failures ? 'error' : 'active', agent.failures ? `${agent.failures} failed` : 'healthy')}</td><td>${Math.round(agent.average_latency_ms || 0)}ms</td><td>${formatNumber(agent.total_tokens)}</td><td>${agent.last_seen_at ? relativeTime(agent.last_seen_at) : '—'}</td></tr>`).join("");
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
  loadingPage("Agent Marketplace", "Install, update, and uninstall reusable agents without rebuilding the platform.");
  try {
    const [templatesResult, installsResult] = await Promise.all([api.marketplaceTemplates(), api.marketplaceInstalls()]);
    state.marketplace = {
      templates: templatesResult.templates || [],
      installs: installsResult.installs || [],
    };
  } catch (error) { setPage(errorState(error.message)); return; }

  const templates = state.marketplace?.templates || [];
  const installs = state.marketplace?.installs || [];
  const installedByTemplate = new Map(installs.map((item) => [item.template_key, item]));
  const categoryOrder = ["Business", "Education", "Healthcare", "E-commerce", "Travel"];
  const categoryMeta = {
    Business: "Customer service, sales, FAQ, and property workflows",
    Education: "School and education operations",
    Healthcare: "Clinic and patient administration",
    "E-commerce": "Commerce operations and order support",
    Travel: "Trip planning and booking assistance",
  };

  const templateCard = (template) => {
    const install = installedByTemplate.get(template.key);
    const installed = !!install;
    return `<article class="card card-hover marketplace-card"><div class="card-head"><div><h3>${esc(template.name)}</h3><span class="subtle" style="font-size:9px">${esc(template.category)} · v${esc(template.version || '1.0.0')}</span></div>${statusBadge(template.status || 'active', template.status || 'active')}</div><p>${esc(template.description)}</p><div class="marketplace-tags" style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0">${installed ? `<span class="status-badge active">Installed</span><span class="status-badge ${esc(install.bot_status || 'active')}">${esc(install.bot_status || 'active')}</span>` : `<span class="status-badge ready">Available</span>`}</div><div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between;align-items:center"><div class="subtle mono" style="font-size:8px">${installed ? `Bot: ${esc(install.bot_name || '')}` : `Template: ${esc(template.key)}`}</div><div style="display:flex;gap:8px;flex-wrap:wrap">${installed ? `<button class="button" data-marketplace-update="${esc(install.id)}">Update</button><button class="button button-danger" data-marketplace-uninstall="${esc(install.id)}">Uninstall</button>` : `<button class="button button-primary" data-marketplace-install="${esc(template.key)}">Install</button>`}</div></div></article>`;
  };

  const categorySections = categoryOrder.map((category) => {
    const rows = templates.filter((template) => template.category === category);
    return `<section class="card" style="margin-top:16px"><div class="card-head"><div><h3>${esc(category)}</h3><span class="subtle" style="font-size:9px">${esc(categoryMeta[category] || '')}</span></div><span class="status-badge active">${formatNumber(rows.length)} templates</span></div>${rows.length ? `<div class="grid grid-2" style="padding:16px">${rows.map(templateCard).join('')}</div>` : emptyState("No templates", "No templates are available in this category.")}</section>`;
  }).join('');

  const installedRows = installs.map((item) => `<tr><td><span class="table-title">${esc(item.template_name)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(item.template_key)} · ${esc(item.template_version || '1.0.0')}</div></td><td>${esc(item.template_category || 'Business')}</td><td>${statusBadge(item.bot_status || 'inactive', item.bot_status || 'inactive')}</td><td>${esc(item.bot_name || '—')}</td><td>${relativeTime(item.installed_at)}</td><td><div style="display:flex;gap:6px;flex-wrap:wrap"><button class="button" data-marketplace-update="${esc(item.id)}">Update</button><button class="button button-danger" data-marketplace-uninstall="${esc(item.id)}">Uninstall</button></div></td></tr>`).join('');

  setPage(`${pageHeader("Agent Marketplace","Install reusable agents like apps, then update or uninstall them per tenant.",`<span class="status-badge active">${formatNumber(templates.length)} templates</span>`)}<div class="grid grid-4">${metricCard("Templates",formatNumber(templates.length),"Reusable agent blueprints","agents")}${metricCard("Installed",formatNumber(installs.length),"Tenant agent installs","dashboard")}${metricCard("Active installs",formatNumber(installs.filter((item) => item.bot_status === 'active').length),"Currently enabled","observability")}${metricCard("Categories",formatNumber(categoryOrder.length),"Business, Education, Healthcare, E-commerce, Travel","knowledge")}</div>${categorySections}<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Installed agents</h3><span class="subtle" style="font-size:9px">Manage tenant-specific agent installs</span></div></div>${installedRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Template</th><th>Category</th><th>Status</th><th>Bot</th><th>Installed</th><th>Action</th></tr></thead><tbody>${installedRows}</tbody></table></div>` : emptyState("No installed agents","Install a template from the marketplace to create the first reusable agent.")}</div>`);
}

async function renderKnowledge() {
  loadingPage("Knowledge Base","Manage trusted source documents used to ground AI answers.");
  if (!state.selectedBotId) { setPage(pageHeader("Knowledge Base","Ground agents with company documents.") + emptyState("No agent available","Create an agent before uploading knowledge.")); return; }
  try { state.documents = await api.documents(state.selectedBotId); }
  catch (error) { setPage(errorState(error.message)); return; }
  const options = state.bots.map((bot) => `<option value="${esc(bot.id)}" ${bot.id===state.selectedBotId?'selected':''}>${esc(bot.name)}</option>`).join("");
  const rows = state.documents.map((doc) => {
    const sourceLabel = doc.source_type === 'url' ? 'Website URL' : 'File upload';
    const sourceInfo = doc.source_url ? `<div class="subtle mono" style="font-size:8px;margin-top:3px;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(doc.source_url)}</div>` : '';
    return `<tr><td><div style="display:flex;align-items:flex-start;gap:10px"><span class="activity-symbol">KB</span><div><span class="table-title">${esc(doc.filename)}</span><div class="subtle mono" style="font-size:8px;margin-top:3px">${esc(doc.id).slice(0,12)} · ${esc(sourceLabel)}</div>${sourceInfo}</div></div></td><td>${formatFileSize(doc.file_size)}</td><td>${formatNumber(doc.chunk_count)}</td><td>${statusBadge(doc.status,doc.status)}</td><td>${formatDate(doc.created_at)}</td><td><button class="button button-danger" data-delete-document="${esc(doc.id)}">Delete</button></td></tr>`;
  }).join("");
  setPage(`${pageHeader("Knowledge Base","Upload product docs, policies, FAQs, websites, and playbooks for retrieval-grounded answers.",`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="select" data-knowledge-bot>${options}</select><label class="button button-primary">${icon('upload',14)} Upload document<input type="file" data-document-upload accept=".pdf,.docx,.txt,.csv,.md,.markdown" hidden></label><form data-kb-url-form style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input class="input" name="title" placeholder="Judul opsional" style="min-width:180px"><input class="input" name="url" placeholder="https://example.com/kb" style="min-width:240px" required><button class="button button-primary" type="submit">${icon('link',14)} Upload URL</button></form></div>`)}<div class="grid grid-3" style="margin-bottom:16px">${metricCard("Documents",formatNumber(state.documents.length),"Connected to selected agent","knowledge")}${metricCard("Knowledge chunks",formatNumber(state.documents.reduce((n,d)=>n+(d.chunk_count||0),0)),"Searchable retrieval units","analytics")}${metricCard("Ready sources",formatNumber(state.documents.filter(d=>d.status==='ready').length),"Available to AI","agents","trend-up")}</div><div class="card"><div class="card-head"><div><h3>Source library</h3><span class="subtle" style="font-size:9px">PDF, DOCX, TXT, Markdown, CSV, and website URLs</span></div></div>${rows?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Size</th><th>Chunks</th><th>Status</th><th>Uploaded</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("No knowledge sources","Upload a document or website URL to ground this agent with company information.",`<label class="button button-primary">Upload first document<input type="file" data-document-upload hidden></label>`)}</div>`);
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

async function renderSettings() {
  loadingPage("Platform Settings","Configure channels, security posture, and workspace connectivity.");
  const [channelResult, integrationResult] = await Promise.all([settle("channels",api.channels()),settle("integrations",api.integrations())]);
  state.channels = channelResult.ok ? channelResult.data.channels || [] : [];
  state.integrations = integrationResult.ok ? integrationResult.data : {};
  const channelRows = state.channels.map((channel) => `<tr><td><span class="activity-symbol">${initials(channel.channel_type)}</span></td><td><span class="table-title">${esc(channel.display_name)}</span><div class="subtle" style="font-size:9px">${esc(channel.channel_type)}</div></td><td>${statusBadge(channel.is_active?'active':'inactive')}</td><td>${relativeTime(channel.last_sync_at||channel.connected_at)}</td><td><button class="button button-danger" data-disconnect-channel="${esc(channel.id)}">Disconnect</button></td></tr>`).join("");
  const integrationCards = `<div class="grid grid-2" style="margin-top:16px"><div class="card"><div class="card-head"><div><h3>Meta WhatsApp</h3><span class="subtle" style="font-size:9px">Cloud API and inbound bot mapping</span></div>${statusBadge(state.integrations?.meta?.connected?'active':'inactive',state.integrations?.meta?.connected?'Connected':'Not connected')}</div><div class="card-body"><p class="subtle">Phone ID: ${esc(state.integrations?.meta?.wa_phone_number_id||'Not configured')}</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="button button-primary" data-action="configure-meta">Configure Meta</button>${state.integrations?.meta?.connected?'<button class="button" data-action="test-meta">Send test</button><button class="button button-danger" data-disconnect-integration="meta">Disconnect</button>':''}</div></div></div><div class="card"><div class="card-head"><div><h3>Gmail</h3><span class="subtle" style="font-size:9px">OAuth inbox processing</span></div>${statusBadge(state.integrations?.gmail?.connected?'active':'inactive',state.integrations?.gmail?.connected?'Connected':'Not connected')}</div><div class="card-body"><p class="subtle">${esc(state.integrations?.gmail?.email||'No Gmail account connected')}</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="button button-primary" data-action="gmail-start">${state.integrations?.gmail?.connected?'Reconnect Gmail':'Connect Gmail'}</button>${state.integrations?.gmail?.connected?'<button class="button" data-action="gmail-map">Map to agent</button><button class="button" data-action="gmail-poll">Poll now</button><button class="button button-danger" data-disconnect-integration="gmail">Disconnect</button>':''}</div></div></div></div>`;
  const systemStatus = `<div class="grid grid-2"><div class="card"><div class="card-head"><h3>System status</h3></div><div class="card-body"><div class="setting-row"><div><strong>FastAPI backend</strong><p class="subtle">Application and REST APIs</p></div>${statusBadge(state.health?.db?'active':'error',state.health?.db?'Connected':'Unavailable')}</div><div class="setting-row"><div><strong>PostgreSQL</strong><p class="subtle">Tenant and business data</p></div>${statusBadge(state.health?.schema?'active':'error',state.health?.schema?'Schema ready':'Schema issue')}</div><div class="setting-row"><div><strong>AI provider</strong><p class="subtle">${esc(state.health?.ai?.model||'Not configured')}</p></div>${statusBadge(state.health?.ai?.configured?'active':'error',state.health?.ai?.configured?'Ready':'Not configured')}</div></div></div><div class="card"><div class="card-head"><h3>Workspace identity</h3></div><div class="card-body"><div class="form-grid"><label class="field full"><span>Organization</span><input value="${esc(state.org?.name||'')}" readonly></label><label class="field"><span>Tenant slug</span><input value="${esc(state.org?.slug||'')}" readonly></label><label class="field"><span>Application URL</span><input value="${esc(location.origin)}" readonly></label></div></div></div></div>`;
  const channelTable = `<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Connected channels</h3><span class="subtle" style="font-size:9px">Website and Telegram channels, plus managed integrations below</span></div><span class="status-badge active">${state.channels.filter(c=>c.is_active).length} active</span></div>${channelRows?`<div class="table-wrap"><table class="data-table"><thead><tr><th></th><th>Channel</th><th>Status</th><th>Last sync</th><th></th></tr></thead><tbody>${channelRows}</tbody></table></div>`:emptyState("No platform channels","Connect a website or Telegram channel to an AI agent.")}</div>`;
  const sessionCard = `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Session & security</h3></div><div class="card-body" style="display:flex;align-items:center;justify-content:space-between;gap:16px"><div><strong>Current authenticated session</strong><p class="subtle" style="margin:5px 0 0;font-size:10px">JWT authentication and RBAC permissions are enforced by FastAPI.</p></div><button class="button button-danger" data-action="logout">Sign out</button></div></div>`;
  setPage(`${pageHeader("Platform Settings","Manage deployment connectivity, integrations, and workspace security.",`<button class="button" data-action="connect-channel">Connect channel</button><button class="button" data-action="security-scan">Run security scan</button>`)}${systemStatus}${channelTable}${integrationCards}${sessionCard}`);
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
  const options=state.roles.map((role)=>`<option value="${esc(role.key)}" ${(member.roles||[]).includes(role.key)?"selected":""}>${esc(role.name||role.key)}</option>`).join("");
  el("#modal-root").innerHTML=modal({title:`Manage access - ${member.full_name||member.email}`,body:`<form id="member-role-form" data-user-id="${esc(member.id)}"><label class="field"><span>Add role</span><select name="role_key">${options}</select></label></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-member-role">Assign role</button>`});
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

function showConnectChannel() {
  const bots=state.bots.map((bot)=>`<option value="${esc(bot.id)}">${esc(bot.name)}</option>`).join("");
  el("#modal-root").innerHTML=modal({title:"Connect business channel",body:`<form id="connect-channel-form"><div class="form-grid"><label class="field"><span>Agent</span><select name="bot_id">${bots}</select></label><label class="field"><span>Channel</span><select name="channel_type"><option value="website">Website</option><option value="telegram">Telegram</option></select></label><label class="field full"><span>Display name</span><input name="display_name" required placeholder="Main website"></label><label class="field"><span>External ID</span><input name="external_id" placeholder="Optional"></label><label class="field"><span>Telegram bot token</span><input name="credential" type="password" placeholder="Only required for Telegram"></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-connect-channel">Connect</button>`});
}

async function submitConnectChannel() {
  const form=el("#connect-channel-form"); if(!form || !form.reportValidity())return; const data=Object.fromEntries(new FormData(form));
  const credentials=data.credential ? (data.channel_type==="telegram"?{bot_token:data.credential}:{token:data.credential}) : {}; delete data.credential; data.credentials=credentials;
  try { await api.connectChannel(data); el("#modal-root").innerHTML=""; toast("Channel connected.","success"); await renderSettings(); } catch(error){ toast(error.message,"error"); }
}

function showMetaIntegration() {
  const bots=state.bots.map((bot)=>`<option value="${esc(bot.id)}">${esc(bot.name)}</option>`).join("");
  el("#modal-root").innerHTML=modal({title:"Configure Meta WhatsApp",body:`<form id="meta-integration-form"><div class="form-grid"><label class="field"><span>WhatsApp phone number ID</span><input name="wa_phone_number_id" required value="${esc(state.integrations?.meta?.wa_phone_number_id||'')}"></label><label class="field"><span>Route inbound to agent</span><select name="wa_bot_id">${bots}</select></label><label class="field full"><span>Permanent access token</span><input type="password" name="wa_token" required></label><label class="field"><span>Default test number</span><input name="default_to_number" placeholder="62812..."></label></div></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-meta">Save integration</button>`});
}

async function submitMetaIntegration() { const form=el("#meta-integration-form"); if(!form||!form.reportValidity())return; try{await api.saveMeta(Object.fromEntries(new FormData(form))); el("#modal-root").innerHTML=""; toast("Meta WhatsApp configured.","success"); await renderSettings();}catch(error){toast(error.message,"error");} }
async function startGmail() { try{const result=await api.gmailStart(); location.href=result.auth_url;}catch(error){toast(error.message,"error");} }
async function mapGmail() { const botId=state.selectedBotId||state.bots[0]?.id; if(!botId)return toast("Create an agent first.","error"); try{await api.gmailMapBot(botId); toast("Gmail mapped to selected agent.","success"); await renderSettings();}catch(error){toast(error.message,"error");} }
async function pollGmail() { try{const result=await api.gmailPoll(); toast(`Gmail poll complete: ${result.processed||0} messages.`,"success");}catch(error){toast(error.message,"error");} }
function showMetaTest() { el("#modal-root").innerHTML=modal({title:"Send WhatsApp test",body:`<form id="meta-test-form"><label class="field"><span>Destination number</span><input name="to_number" required placeholder="62812..."></label><label class="field" style="margin-top:12px"><span>Message</span><textarea name="text">Halo! Ini test dari BotNesia.</textarea></label></form>`,footer:`<button class="button" data-action="close-modal">Cancel</button><button class="button button-primary" data-action="submit-meta-test">Send test</button>`}); }
async function submitMetaTest(){const form=el("#meta-test-form");if(!form||!form.reportValidity())return;try{await api.sendMetaTest(form.elements.to_number.value,form.elements.text.value);el("#modal-root").innerHTML="";toast("WhatsApp test sent.","success");}catch(error){toast(error.message,"error");}}
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

function cleanSpeechText(text) {
  const ordinals = ["", "Pertama", "Kedua", "Ketiga", "Keempat", "Kelima", "Keenam", "Ketujuh", "Kedelapan", "Kesembilan", "Kesepuluh"];
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/https?:\/\/\S+/g, " tautan ")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/^\s*(\d{1,2})[.)]\s+/gm, (_, value) => `${ordinals[Number(value)] || `Nomor ${value}`}, `)
    .replace(/^\s*[-*•]\s+/gm, "Berikutnya, ")
    .replace(/[;]+/g, ",")
    .replace(/[:]+(?=\s)/g, ",")
    .replace(/[!?]{2,}/g, (value) => value[0])
    .replace(/\.{3,}/g, ".")
    .replace(/[*_`#>|~]/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\s*\n{2,}\s*/g, ". ")
    .replace(/\s*\n\s*/g, ", ")
    .replace(/\s+([,.;!?])/g, "$1")
    .replace(/([.!?])(?=[A-Za-zÀ-ÿ])/g, "$1 ")
    .replace(/,{2,}/g, ",")
    .replace(/\s+/g, " ")
    .trim();
}

function splitSpeechText(text, maxLength = 180) {
  const sentences = cleanSpeechText(text).match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [];
  const chunks = [];
  let current = "";
  for (const sentence of sentences) {
    const part = sentence.trim();
    if (!part) continue;
    if (current && current.length + part.length + 1 > maxLength) {
      chunks.push(current);
      current = "";
    }
    if (part.length <= maxLength) {
      current = current ? `${current} ${part}` : part;
      continue;
    }
    const words = part.split(/\s+/);
    for (const word of words) {
      if (current && current.length + word.length + 1 > maxLength) {
        chunks.push(current);
        current = word;
      } else {
        current = current ? `${current} ${word}` : word;
      }
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

function voiceStatus(container, message) {
  const status = container?.querySelector?.("[data-voice-status]");
  if (status) status.textContent = message;
}

async function stopSpeaking(container = document) {
  state.speechRunId += 1;
  window.speechSynthesis?.cancel();
  if (state.speechAudio) {
    state.speechAudio.pause();
    state.speechAudio.src = "";
    state.speechAudio = null;
  }
  try { await api.stopSpeech(); } catch {}
  voiceStatus(container, "Suara dihentikan");
}

async function playSpeechBlob(blob, runId) {
  const url = URL.createObjectURL(blob);
  try {
    await new Promise((resolve, reject) => {
      const audio = new Audio(url);
      state.speechAudio = audio;
      audio.preload = "auto";
      audio.onended = resolve;
      audio.onerror = () => reject(new Error("Audio neural gagal diputar."));
      if (runId !== state.speechRunId) return resolve();
      audio.play().catch(reject);
    });
  } finally {
    if (state.speechAudio?.src === url) state.speechAudio = null;
    URL.revokeObjectURL(url);
  }
}

async function prepareSpeech(text, container = document) {
  if (!state.speakReplies) return null;
  const chunks = splitSpeechText(text);
  if (!chunks.length) return null;
  voiceStatus(container, "Menyinkronkan tulisan dan suara...");
  const firstBlob = await api.synthesizeSpeech(chunks[0]);
  return { chunks, firstBlob };
}

async function speak(text, container = document, prepared = null) {
  if (!state.speakReplies) return;
  const chunks = prepared?.chunks || splitSpeechText(text);
  if (!chunks.length) return;

  const runId = ++state.speechRunId;
  window.speechSynthesis?.cancel();
  if (state.speechAudio) state.speechAudio.pause();
  const audioJobs = chunks.map((chunk, index) => index === 0 && prepared?.firstBlob
    ? Promise.resolve(prepared.firstBlob)
    : api.synthesizeSpeech(chunk));
  for (let index = 0; index < audioJobs.length && runId === state.speechRunId; index += 1) {
    voiceStatus(container, `Gadis Neural membaca ${index + 1}/${chunks.length}...`);
    const blob = await audioJobs[index];
    if (runId !== state.speechRunId) break;
    await playSpeechBlob(blob, runId);
    // Beri jeda singkat antar kalimat agar terdengar seperti orang berhenti sejenak di titik/koma.
    if (runId === state.speechRunId && index < audioJobs.length - 1) {
      await new Promise((resolve) => setTimeout(resolve, 260));
    }
  }
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
  const renderers = {dashboard:renderDashboard,agents:renderAgents,chat:renderChat,conversations:renderConversations,handoffs:renderHumanHandoff,analytics:renderAnalytics,learning:renderFeedbackLearning,observability:renderObservability,costs:renderCostIntelligence,marketplace:renderMarketplace,knowledge:renderKnowledge,"kb-builder":renderKnowledgeBuilder,team:renderTeam,billing:renderBilling,settings:renderSettings};
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
    messages.insertAdjacentHTML("beforeend", `<div class="message"><div class="message-bubble">${renderMarkdown(result.answer)}<div class="message-meta">AI · ${result.latency_ms || 0}ms</div>${feedbackControls(result.message_id,result.session_id)}</div></div>`);
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
  if(action==="configure-meta") showMetaIntegration();
  if(action==="submit-meta") await submitMetaIntegration();
  if(action==="test-meta") showMetaTest();
  if(action==="submit-meta-test") await submitMetaTest();
  if(action==="gmail-start") await startGmail();
  if(action==="gmail-map") await mapGmail();
  if(action==="gmail-poll") await pollGmail();
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
  if(action==="security-scan") { try{ const result=await api.securityScan(); toast(`Security scan completed: ${result.findings?.length||0} findings.`,"success"); }catch(error){ toast(error.message,"error"); } }
  if(action==="invite-member") showInviteMember();
  if(action==="submit-invite-member") await submitInviteMember();
  const disconnectChannel=event.target.closest("[data-disconnect-channel]"); if(disconnectChannel && confirm("Disconnect this channel?")){ try{ await api.disconnectChannel(disconnectChannel.dataset.disconnectChannel); toast("Channel disconnected.","success"); await renderSettings(); }catch(error){toast(error.message,"error");} }
  if(action==="manage-member") showMemberRole(event.target.closest("[data-team-user]")?.dataset.teamUser);
  if(action==="submit-member-role") await submitMemberRole();
  if(action==="export-team") exportTeam();
  if(action==="connect-channel") showConnectChannel();
  if(action==="submit-connect-channel") await submitConnectChannel();
  const deleteDoc=event.target.closest("[data-delete-document]"); if(deleteDoc && confirm("Delete this knowledge document?")){ try{ await api.deleteDocument(state.selectedBotId,deleteDoc.dataset.deleteDocument); toast("Document deleted.","success"); await renderKnowledge(); }catch(error){toast(error.message,"error");} }
  const kbRegenerate=event.target.closest("[data-kb-regenerate]"); if(kbRegenerate){ await regenerateKb(kbRegenerate.dataset.kbRegenerate); return; }
  const kbFaqActionTarget=event.target.closest("[data-kb-faq-action]"); if(kbFaqActionTarget){ await kbFaqAction(kbFaqActionTarget.dataset.kbFaqId,kbFaqActionTarget.dataset.kbFaqAction); return; }
  const kbFaqEdit=event.target.closest("[data-kb-faq-edit]"); if(kbFaqEdit){ await editKbFaq(kbFaqEdit.dataset.kbFaqEdit); return; }
  const kbSopActionTarget=event.target.closest("[data-kb-sop-action]"); if(kbSopActionTarget){ await kbSopAction(kbSopActionTarget.dataset.kbSopId,kbSopActionTarget.dataset.kbSopAction); return; }
  const kbSopEdit=event.target.closest("[data-kb-sop-edit]"); if(kbSopEdit){ await editKbSop(kbSopEdit.dataset.kbSopEdit); return; }
  const marketplaceUpdate=event.target.closest("[data-marketplace-update]"); if(marketplaceUpdate){ const installId=marketplaceUpdate.dataset.marketplaceUpdate; const name=prompt("Nama agent baru (opsional, kosong untuk mempertahankan)") || null; try{ await api.updateMarketplaceInstall(installId, name?.trim() || null); toast("Marketplace agent updated.","success"); await renderMarketplace(); }catch(error){ toast(error.message,"error"); } return; }
  const marketplaceUninstall=event.target.closest("[data-marketplace-uninstall]"); if(marketplaceUninstall && confirm("Uninstall this marketplace agent?")){ try{ await api.uninstallMarketplaceInstall(marketplaceUninstall.dataset.marketplaceUninstall); toast("Marketplace agent uninstalled.","success"); await renderMarketplace(); }catch(error){ toast(error.message,"error"); } return; }
  const plan=event.target.closest("[data-checkout-plan]"); if(plan) await checkout(plan.dataset.checkoutPlan);
});

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
  if(event.target.matches("[data-cost-budget-form]")){ event.preventDefault(); await updateCostBudget(event.target); }
});

document.addEventListener("change", async (event) => {
  if(event.target.matches("[data-chat-page-bot]")){ state.selectedBotId=event.target.value; state.chatSession=null; await renderChat(); }
  if(event.target.matches("[data-conversation-bot]")){ state.selectedBotId=event.target.value; state.selectedConversationId=null; state.messages=[]; await renderConversations(); }
  if(event.target.matches("[data-analytics-bot]")){ state.selectedBotId=event.target.value; await renderAnalytics(); }
  if(event.target.matches("[data-analytics-days]")) await renderAnalytics(event.target.value);
  if(event.target.matches("[data-observability-days]")) await renderObservability(event.target.value);
  if(event.target.matches("[data-knowledge-bot]")){ state.selectedBotId=event.target.value; await renderKnowledge(); }
  if(event.target.matches("[data-document-upload]")) await uploadDocument(event.target);
  if(event.target.matches("[data-knowledge-builder-bot]")){ state.selectedBotId=event.target.value; await renderKnowledgeBuilder(); }
  if(event.target.matches("[data-faq-import]")) await uploadFaqCsv(event.target);
});

document.addEventListener("input", (event) => {
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
