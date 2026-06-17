const paths = {
  founder:'<path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="m3 7 6-4 6 5 7-6"/>',
  dashboard:'<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
  agents:'<circle cx="12" cy="8" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/><path d="M8 3 6 1M16 3l2-2"/>',
  channels:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="7" cy="6" r="2"/><circle cx="17" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
  chat:'<path d="M21 15a3 3 0 0 1-3 3H8l-5 4V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3z"/>',
  analytics:'<path d="M4 20V10M10 20V4M16 20v-7M22 20V7"/>',
  observability:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>',
  costs:'<path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
  marketplace:'<path d="M3 7h18l-1.5 12h-15z"/><path d="M7 7a5 5 0 0 1 10 0"/>',
  handoffs:'<path d="M4 4h16v12H7l-3 3z"/><path d="M8 8h8M8 12h5"/>',
  learning:'<path d="M12 3a5 5 0 0 0-3 9v3h6v-3a5 5 0 0 0-3-9z"/><path d="M9 19h6M10 22h4"/>',
  improvement:'<path d="M3 17l6-6 4 4 8-8"/><path d="M17 3h4v4"/>',
  knowledge:'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 5.5v14"/>',
  "kb-builder":'<path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/><circle cx="12" cy="12" r="4"/>',
  "workflow-builder":'<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="12" r="2.5"/><circle cx="5" cy="18" r="2.5"/><path d="M7.5 6h5a3 3 0 0 1 3 3v0M7.5 18h5a3 3 0 0 0 3-3v0M16.5 9v6"/>',
  multimedia:'<rect x="3" y="3" width="18" height="14" rx="2"/><circle cx="8" cy="9" r="1.5"/><path d="m4 14 4-4 3 3 5-5 4 4"/><path d="M8 21h8"/>',
  team:'<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/>',
  security:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  billing:'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21h-4v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1-2.8-2.8.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3v-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1 2.8-2.8.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3h4v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1 2.8 2.8-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1h.2v4h-.2a1.7 1.7 0 0 0-1.4 1z"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>', menu:'<path d="M4 7h16M4 12h16M4 17h16"/>', close:'<path d="m6 6 12 12M18 6 6 18"/>', bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>', arrow:'<path d="m9 18 6-6-6-6"/>', refresh:'<path d="M20 6v5h-5M4 18v-5h5"/><path d="M18 9a7 7 0 0 0-12-2L4 11M6 15a7 7 0 0 0 12 2l2-4"/>', upload:'<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/>', send:'<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>', mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>', speaker:'<path d="M11 5 6 9H2v6h4l5 4zM15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12"/>', more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
};

export function icon(name, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.dashboard}</svg>`;
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function mdInline(text) {
  let html = esc(text);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}

// Render a light subset of Markdown (paragraphs, lists, headings, code, bold/italic, links)
// for assistant chat replies, so AI answers look as structured as Claude/ChatGPT output.
export function renderMarkdown(text) {
  const lines = String(text ?? "").replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let list = null;
  const flushList = () => {
    if (list) blocks.push(`<${list.tag}>${list.items.map((item) => `<li>${mdInline(item)}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flushList();
      const code = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i++; }
      i++;
      blocks.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.*)/);
    if (heading) { flushList(); blocks.push(`<p><strong>${mdInline(heading[1])}</strong></p>`); i++; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)/);
    if (ul) {
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(ul[1]); i++; continue;
    }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (ol) {
      if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; }
      list.items.push(ol[1]); i++; continue;
    }
    if (line.trim() === '') { flushList(); i++; continue; }
    flushList();
    const para = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== '' && !/^\s*```/.test(lines[i]) && !/^#{1,6}\s+/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\d+[.)]\s+/.test(lines[i])) {
      para.push(lines[i]); i++;
    }
    blocks.push(`<p>${para.map(mdInline).join('<br>')}</p>`);
  }
  flushList();
  return blocks.join('');
}

export function initials(value = "BN") {
  return value.split(/\s+/).filter(Boolean).slice(0,2).map((item) => item[0]).join("").toUpperCase() || "BN";
}

export function formatNumber(value) { return Number(value || 0).toLocaleString("id-ID"); }
export function formatDate(value, options = {}) {
  if (!value) return "—";
  const date = new Date(value); if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("id-ID", { day:"2-digit", month:"short", year:"numeric", ...options }).format(date);
}
export function relativeTime(value) {
  if (!value) return "—"; const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}d lalu`; if (seconds < 3600) return `${Math.floor(seconds/60)}m lalu`;
  if (seconds < 86400) return `${Math.floor(seconds/3600)}j lalu`; return `${Math.floor(seconds/86400)}h lalu`;
}
export function idr(value) { return new Intl.NumberFormat("id-ID", { style:"currency", currency:"IDR", maximumFractionDigits:0 }).format(Number(value || 0)); }

const navGroups = [
  ["FOUNDER", [["founder","Founder OS"]]],
  ["OPERATIONS", [["dashboard","Command Center"],["agents","AI Agents"],["chat","AI Chat"],["conversations","Conversations"],["handoffs","Human Handoff"],["analytics","Analytics"],["routing-logs","Routing Logs"],["learning","Feedback Learning"],["improvement","AI Improvement"],["observability","AI Observability"],["costs","Cost Intelligence"]]],
  ["PLATFORM", [["channels","Channels"],["marketplace","Agent Marketplace"],["knowledge","Knowledge Base"],["kb-builder","Knowledge Builder"],["workflow-builder","Workflow Builder"],["multimedia","Multimedia Studio"],["team","Team & Tenants"],["billing","Billing"]]],
  ["SYSTEM", [["security","Security"],["settings","Settings"]]],
];

export function sidebar({ route, org, user, counts = {}, founderAccess = false }) {
  const groups = navGroups.map(([section, links]) => [section, links.filter(([key]) => key !== "founder" || founderAccess)]).filter(([, links]) => links.length);
  const items = groups.map(([section, links]) => `<div class="nav-section">${section}</div>${links.map(([key,label]) => `<button class="nav-item ${route===key?'active':''}" data-route="${key}">${icon(key)}<span>${label}</span>${counts[key] !== undefined ? `<span class="nav-count">${counts[key]}</span>` : ''}</button>`).join('')}`).join('');
  return `<div class="sidebar-head"><a class="brand" href="#dashboard"><span class="brand-mark">BN</span><span>BotNesia</span></a><div class="workspace-switcher"><strong class="truncate">${esc(org?.name || 'Workspace')}</strong><small>${esc((org?.plan || 'free').toUpperCase())} · ${esc(org?.slug || 'tenant')}</small></div></div><nav class="nav">${items}</nav><div class="sidebar-footer"><div class="user-chip"><span class="avatar">${initials(user?.full_name || user?.email)}</span><div class="truncate"><strong class="truncate">${esc(user?.full_name || 'Workspace Admin')}</strong><small class="truncate">${esc(user?.email || '')}</small></div><button class="icon-button" data-action="logout" title="Keluar">${icon('arrow',14)}</button></div></div>`;
}

const routeMeta = {
  founder:["Founder Operating System","Platform-wide revenue, growth, retention, AI economics, and business health"],
  dashboard:["Command Center","Live overview of your AI operations"], agents:["AI Agent Center","Deploy, monitor, and tune every customer-facing agent"],
  chat:["AI Chat","Ngobrol langsung dengan AI agent kamu - seperti ChatGPT atau Claude"],
  conversations:["Conversation Center","Unified inbox across every connected channel"], analytics:["Analytics","Performance, quality, and business impact"],
  observability:["AI Observability","Agent execution health, latency, tokens, failures, and request traces"],
  "routing-logs":["Routing Logs","Per-message Intent Router decisions: intent, selected agent, confidence, and handoff status"],
  channels:["Channels","Connect and monitor WhatsApp, Telegram, Instagram, Facebook Messenger, and Website Chat"],
  costs:["Cost Intelligence","AI operating cost, budget health, and model efficiency"],
  marketplace:["Agent Marketplace","Install, update, and manage reusable AI agents"],
  handoffs:["Human Handoff","AI escalation queue, ownership, SLA, and resolution workflow"],
  learning:["Feedback Learning","User feedback, failed questions, knowledge gaps, and improvement queue"],
  improvement:["AI Improvement Center","Self-evaluation: top issues, knowledge gaps, agent weaknesses, and AI-suggested improvements for admin review"],
  knowledge:["Knowledge Base","Ground your agents with trusted company knowledge"],
  "kb-builder":["Knowledge Builder","Auto-generate FAQ, SOP, summaries, categories, and quality scores from your documents"],
  "workflow-builder":["Workflow Builder","Rancang automasi AI Agent ala n8n/Zapier — trigger, condition, agent, action, dan notification"],
  multimedia:["Multimedia Studio","Generate gambar, analisis gambar (Vision AI), dan buat dokumen PDF/DOCX/XLSX/PPTX"],
  team:["Team & Tenants","People, roles, access, and workspace identity"],
  security:["Security Dashboard","Audit logs, active sessions, suspicious logins, and API key management"],
  billing:["Billing & Usage","Subscription, limits, invoices, and plan management"], settings:["Platform Settings","Connections, security, and system configuration"],
};
export function topbar({ route, health }) {
  const [title, description] = routeMeta[route] || routeMeta.dashboard;
  return `<div class="topbar-left"><button class="icon-button mobile-menu" data-action="toggle-sidebar">${icon('menu')}</button><div class="page-heading"><h1>${title}</h1><p>${description}</p></div></div><div class="topbar-actions"><label class="search-box">${icon('search',15)}<input data-global-search placeholder="Search agents, conversations..."><kbd class="mono">⌘K</kbd></label><span class="status-badge ${health?.status==='ok'?'active':'error'}">${health?.status==='ok'?'Systems operational':'Degraded'}</span><button class="icon-button" data-action="notifications" title="Notifications">${icon('bell')}</button><button class="button button-primary" data-action="create-agent">${icon('plus',15)}<span class="button-label">New agent</span></button></div>`;
}

export function pageHeader(title, description, actions = "") { return `<div class="page-header"><div><span class="eyebrow">BOTNESIA PLATFORM</span><h2>${esc(title)}</h2><p>${esc(description)}</p></div><div class="header-actions">${actions}</div></div>`; }
export function statusBadge(status = "unknown", label = status) { return `<span class="status-badge ${esc(status)}">${esc(label)}</span>`; }
export function metricCard(label, value, meta, iconName = "analytics", trend = "") { return `<article class="card metric-card card-hover"><div class="metric-top"><span class="metric-label">${esc(label)}</span><span class="metric-icon">${icon(iconName,16)}</span></div><div class="metric-value">${value}</div><div class="metric-meta ${trend}">${meta}</div></article>`; }
export function skeletonCards(count = 4) { return `<div class="grid grid-4">${Array.from({length:count},()=>'<div class="skeleton skeleton-card"></div>').join('')}</div>`; }
export function emptyState(title, description, action = "") { return `<div class="empty-state"><span class="state-icon">${icon('agents',22)}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action ? `<div style="margin-top:16px">${action}</div>` : ''}</div>`; }
export function errorState(message) { return `<div class="error-state"><span class="state-icon">!</span><h3>Data tidak dapat dimuat</h3><p>${esc(message)}</p><button class="button" style="margin-top:14px" data-action="refresh">${icon('refresh',14)} Coba lagi</button></div>`; }

export function agentCard(bot) {
  const status = bot.status || "inactive";
  return `<article class="card card-hover agent-card" data-agent-id="${esc(bot.id)}"><div class="agent-card-top"><span class="agent-icon">${initials(bot.name)}</span><div style="min-width:0;flex:1"><h3 class="truncate">${esc(bot.name)}</h3>${statusBadge(status)}</div><button class="icon-button" data-agent-id="${esc(bot.id)}">${icon('more',14)}</button></div><p>${esc(bot.greeting || 'AI agent configured for customer operations.')}</p><div class="agent-stats"><div><b>${formatNumber(bot.total_convs)}</b><span>Conversations</span></div><div><b>${formatNumber(bot.total_msgs)}</b><span>Messages</span></div></div></article>`;
}

export function activityItem(item) {
  return `<div class="activity-item"><span class="activity-symbol">${initials(item.channel || 'AI')}</span><div><strong>${esc(item.title)}</strong><p>${esc(item.description)}</p></div><span class="activity-time">${esc(item.time)}</span></div>`;
}

export function modal({ title, body, footer = "", wide = false }) {
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" style="${wide?'width:min(760px,100%)':''}" role="dialog" aria-modal="true"><header class="modal-head"><strong>${esc(title)}</strong><button class="icon-button" data-action="close-modal">${icon('close',16)}</button></header><div class="modal-body">${body}</div>${footer?`<footer class="modal-foot">${footer}</footer>`:''}</section></div>`;
}

export function agentDrawer(bot) {
  return `<div class="drawer-head"><div><span class="eyebrow">AGENT DETAIL</span><h3 style="margin:7px 0 0">${esc(bot.name)}</h3></div><button class="icon-button" data-action="close-drawer">${icon('close')}</button></div><div class="drawer-body"><div class="drawer-section"><div class="agent-card-top"><span class="agent-icon">${initials(bot.name)}</span><div><strong>${esc(bot.name)}</strong><div style="margin-top:6px">${statusBadge(bot.status)}</div></div></div></div><form id="agent-detail-form" data-agent-id="${esc(bot.id)}"><div class="form-grid"><label class="field"><span>Agent name</span><input name="name" value="${esc(bot.name)}" required></label><label class="field"><span>Status</span><select name="status"><option value="active" ${bot.status==='active'?'selected':''}>Active</option><option value="training" ${bot.status==='training'?'selected':''}>Training</option><option value="inactive" ${bot.status==='inactive'?'selected':''}>Inactive</option></select></label><label class="field full"><span>Greeting message</span><textarea name="greeting" style="min-height:90px">${esc(bot.greeting || '')}</textarea></label><label class="field full"><span>System prompt</span><textarea name="system_prompt" placeholder="Define role, tone, boundaries, and business context...">${esc(bot.system_prompt || '')}</textarea></label><label class="field"><span>Language</span><select name="language"><option value="id" ${bot.language==='id'?'selected':''}>Bahasa Indonesia</option><option value="en" ${bot.language==='en'?'selected':''}>English</option></select></label><label class="field"><span>Brand color</span><input name="primary_color" type="color" value="${esc(bot.primary_color || '#8b7cff')}"></label><label class="field"><span>Reasoning Mode</span><select name="reasoning_mode"><option value="standard" ${bot.reasoning_mode!=='pro'?'selected':''}>Standard (fast)</option><option value="pro" ${bot.reasoning_mode==='pro'?'selected':''}>Pro (deep analysis)</option></select><small style="color:var(--text-muted);display:block;margin-top:4px">Pro: untuk pertanyaan kompleks/analitis, agent merencanakan, bernalar lewat tim spesialis, dan memverifikasi jawaban sebelum dikirim (lebih lambat &amp; lebih dalam).</small></label></div><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px"><button class="button button-primary" type="submit">Save changes</button></div></form></div>`;
}

export function toast(message, type = "") {
  const root = document.getElementById("toast-region"); const node = document.createElement("div");
  node.className = `toast ${type}`; node.textContent = message; root.appendChild(node); setTimeout(() => node.remove(), 4200);
}
