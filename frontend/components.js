import { t, langSwitcherHtml } from "/ui/i18n.js";
const BRAND_LOGO = "/assets/brand/botnesia-clean-logo.png";

const paths = {
  founder:'<path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="m3 7 6-4 6 5 7-6"/>',
  dashboard:'<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
  agents:'<circle cx="12" cy="8" r="3"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/><path d="M8 3 6 1M16 3l2-2"/>',
  channels:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="7" cy="6" r="2"/><circle cx="17" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
  "communication-center":'<path d="M21 11.5a8.38 8.38 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 17 0z"/><path d="M8 10h8M8 14h5"/>',
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
  finance:'<path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/><circle cx="12" cy="12" r="10"/>',
  marketing:'<path d="M3 11v2a1 1 0 0 0 1 1h3l4 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M16 8a4 4 0 0 1 0 8M19 5a8 8 0 0 1 0 14"/>',
  hr:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-1a6 6 0 0 1 6-6h0a6 6 0 0 1 6 6v1"/><path d="M17 11a3 3 0 1 0 0-6M21 21v-1a5 5 0 0 0-4-4.9"/>',
  operations:'<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/><circle cx="12" cy="12" r="4"/>',
  executive:'<path d="M3 21h18M6 21V10l6-4 6 4v11M9 21v-6h6v6"/>',
  workforce:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 4v5"/>',
  "self-learning":'<path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
  "workforce-overview":'<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  "agent-center":'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="8.5" r="1.5"/><path d="M7 16c1.2-1.5 3-2 5-2s3.8.5 5 2"/>',
  about:'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  "founder-story":'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><circle cx="9" cy="9" r="2"/><path d="M14 8h3M14 12h3"/>',
  "investor-demo":'<path d="m22 12-4-4v3H3v2h15v3z"/><path d="M16 6V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/>',
  multimedia:'<rect x="3" y="3" width="18" height="14" rx="2"/><circle cx="8" cy="9" r="1.5"/><path d="m4 14 4-4 3 3 5-5 4 4"/><path d="M8 21h8"/>',
  team:'<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/>',
  security:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  billing:'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21h-4v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1-2.8-2.8.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3v-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1 2.8-2.8.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3h4v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1 2.8 2.8-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1h.2v4h-.2a1.7 1.7 0 0 0-1.4 1z"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>', menu:'<path d="M4 7h16M4 12h16M4 17h16"/>', close:'<path d="m6 6 12 12M18 6 6 18"/>', bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>', arrow:'<path d="m9 18 6-6-6-6"/>', refresh:'<path d="M20 6v5h-5M4 18v-5h5"/><path d="M18 9a7 7 0 0 0-12-2L4 11M6 15a7 7 0 0 0 12 2l2-4"/>', upload:'<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/>', send:'<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>', mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>', speaker:'<path d="M11 5 6 9H2v6h4l5 4zM15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12"/>', more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  "casper-agentic-workflow":'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
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

const _isTblSep = (l) => /^\|[\s|:=-]{3,}\|/.test(l.trim());
const _isTblRow = (l) => /^\|.+\|/.test(l.trim());

function _flushTable(rows, blocks) {
  if (!rows.length) return;
  if (rows.length === 1 && !_isTblSep(rows[0])) {
    blocks.push(`<p>${mdInline(rows[0].replace(/^\||\|$/g,'').replace(/\|/g,' · '))}</p>`);
    return;
  }
  const parseRow = (r) => r.trim().replace(/^\||\|$/g,'').split('|').map(c => c.trim());
  const sepIdx = rows.findIndex(_isTblSep);
  let html = '<div class="md-table-wrap"><table class="md-table">';
  if (sepIdx > 0) {
    const hCells = parseRow(rows[0]);
    html += `<thead><tr>${hCells.map(c=>`<th>${mdInline(c)}</th>`).join('')}</tr></thead><tbody>`;
    for (let r = 0; r < rows.length; r++) {
      if (r === 0 || _isTblSep(rows[r])) continue;
      html += `<tr>${parseRow(rows[r]).map(c=>`<td>${mdInline(c)}</td>`).join('')}</tr>`;
    }
  } else {
    html += '<tbody>';
    for (const row of rows) {
      if (_isTblSep(row)) continue;
      html += `<tr>${parseRow(row).map(c=>`<td>${mdInline(c)}</td>`).join('')}</tr>`;
    }
  }
  html += '</tbody></table></div>';
  blocks.push(html);
}

export function renderMarkdown(text) {
  const lines = String(text ?? "").replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let list = null;
  let tblRows = [];
  let olNext = 1; // tracks next ol number across ↓-interrupted lists

  const flushList = (keepOlCount = false) => {
    if (!list) return;
    const startAttr = list.tag === 'ol' && list.start > 1 ? ` start="${list.start}"` : '';
    blocks.push(`<${list.tag}${startAttr}>${list.items.map(item=>`<li>${mdInline(item)}</li>`).join('')}</${list.tag}>`);
    if (list.tag === 'ol' && keepOlCount) { olNext = list.start + list.items.length; }
    else if (!keepOlCount) { olNext = 1; }
    list = null;
  };
  const flushTable = () => { _flushTable(tblRows, blocks); tblRows = []; };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // ── Code block ────────────────────────────────────────────────────────
    if (/^\s*```/.test(line)) {
      flushList(); flushTable();
      const lang = line.replace(/^\s*```/, '').trim();
      const code = []; i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i++; }
      i++;
      const la = lang ? ` class="language-${esc(lang)}"` : '';
      blocks.push(`<pre><code${la}>${esc(code.join('\n'))}</code></pre>`);
      continue;
    }

    // ── Horizontal rule ───────────────────────────────────────────────────
    if (/^[ \t]*(\*\*\*+|---+|___+)[ \t]*$/.test(line)) {
      flushList(); flushTable(); olNext = 1;
      blocks.push('<hr class="md-hr">');
      i++; continue;
    }

    // ── Headings ──────────────────────────────────────────────────────────
    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      flushList(); flushTable(); olNext = 1;
      const lvl = Math.min(hm[1].length + 2, 6);
      blocks.push(`<h${lvl} class="md-h${lvl}">${mdInline(hm[2])}</h${lvl}>`);
      i++; continue;
    }

    // ── Blockquote ────────────────────────────────────────────────────────
    if (/^\s*>/.test(line)) {
      flushList(); flushTable(); olNext = 1;
      const qLines = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        qLines.push(lines[i].replace(/^\s*>\s?/, '')); i++;
      }
      blocks.push(`<blockquote class="md-blockquote">${qLines.map(l=>`<p>${mdInline(l)}</p>`).join('')}</blockquote>`);
      continue;
    }

    // ── Table ─────────────────────────────────────────────────────────────
    if (_isTblRow(line) || _isTblSep(line)) {
      flushList();
      tblRows.push(line); i++; continue;
    } else if (tblRows.length) { flushTable(); }

    // ── Workflow arrow (↓ alone on a line) ────────────────────────────────
    if (/^\s*↓\s*$/.test(line)) {
      flushList(true); // keep olNext so next ol continues numbering
      blocks.push('<div class="md-arrow">↓</div>');
      i++; continue;
    }

    // ── Bullet with • character ───────────────────────────────────────────
    const bulletDot = line.match(/^\s*[•·]\s+(.*)/);
    if (bulletDot) {
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(bulletDot[1]); i++; continue;
    }

    // ── Unordered list (- or *) ───────────────────────────────────────────
    const ul = line.match(/^\s*[-*]\s+(.*)/);
    if (ul) {
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(ul[1]); i++; continue;
    }

    // ── Ordered list ──────────────────────────────────────────────────────
    const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (ol) {
      if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [], start: olNext }; }
      list.items.push(ol[1]); i++; continue;
    }

    // ── Blank line ────────────────────────────────────────────────────────
    if (line.trim() === '') { flushList(); i++; continue; }

    // ── Paragraph ─────────────────────────────────────────────────────────
    flushList();
    const para = [line]; i++;
    while (
      i < lines.length && lines[i].trim() !== '' &&
      !/^\s*```/.test(lines[i]) && !/^#{1,6}\s/.test(lines[i]) &&
      !/^\s*[-*•·]\s/.test(lines[i]) && !/^\s*\d+[.)]\s/.test(lines[i]) &&
      !_isTblRow(lines[i]) && !/^\s*>/.test(lines[i]) &&
      !/^[ \t]*(\*\*\*+|---+|___+)[ \t]*$/.test(lines[i]) &&
      !/^\s*↓\s*$/.test(lines[i])
    ) { para.push(lines[i]); i++; }
    blocks.push(`<p>${para.map(mdInline).join('<br>')}</p>`);
  }
  flushList(); flushTable();
  return blocks.join('\n');
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
  if (seconds < 60) return `${Math.floor(seconds)}${t('time.sec_ago')}`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}${t('time.min_ago')}`;
  if (seconds < 86400) return `${Math.floor(seconds/3600)}${t('time.hour_ago')}`;
  return `${Math.floor(seconds/86400)}${t('time.day_ago')}`;
}
export function idr(value) { return new Intl.NumberFormat("id-ID", { style:"currency", currency:"IDR", maximumFractionDigits:0 }).format(Number(value || 0)); }

function getNavGroups() {
  const n = (k) => t(`nav.item.${k}`);
  const g = (k) => t(`nav.group.${k}`);
  return [
    ["command-center", g("command-center"), "dashboard", [
      ["dashboard", n("dashboard")],
      ["casper-agentic-workflow", n("casper-agentic-workflow")],
      ["executive", n("executive")],
      ["workforce-overview", n("workforce-overview")],
      ["investor-demo", n("investor-demo")],
    ]],
    ["workforce", g("workforce"), "agents", [
      ["agents", n("agents")],
      ["chat", n("chat")],
      ["finance", n("finance")],
      ["marketing", n("marketing")],
      ["hr", n("hr")],
      ["operations", n("operations")],
      ["marketplace", n("marketplace")],
    ]],
    ["tasks", g("tasks"), "workflow-builder", [
      ["workflow-builder", n("workflow-builder")],
      ["workforce", n("workforce")],
    ]],
    ["communications", g("communications"), "communication-center", [
      ["conversations", n("conversations")],
      ["handoffs", n("handoffs")],
      ["communication-center", n("communication-center")],
      ["channels", n("channels")],
    ]],
    ["knowledge", g("knowledge"), "knowledge", [
      ["knowledge", n("knowledge")],
      ["kb-builder", n("kb-builder")],
      ["learning", n("learning")],
      ["self-learning", n("self-learning")],
      ["improvement", n("improvement")],
    ]],
    ["business", g("business"), "analytics", [
      ["analytics", n("analytics")],
      ["multimedia", n("multimedia")],
      ["handoffs", n("handoffs-customers")],
    ]],
    ["agent-os", g("agent-os"), "agent-center", [
      ["agent-center", n("agent-center")],
      ["routing-logs", n("routing-logs")],
      ["observability", n("observability")],
      ["costs", n("costs")],
    ]],
    ["organization", g("organization"), "team", [
      ["team", n("team")],
      ["security", n("security")],
    ]],
    ["billing", g("billing"), "billing", [
      ["billing", n("billing")],
    ]],
    ["settings", g("settings"), "settings", [
      ["settings", n("settings")],
      ["founder", n("founder")],
      ["about", n("about")],
      ["founder-story", n("founder-story")],
    ]],
  ];
}

function getRouteMeta() {
  const r = (k) => [t(`route.${k}.title`), t(`route.${k}.desc`)];
  return {
    founder: r("founder"),
    dashboard: r("dashboard"),
    agents: r("agents"),
    chat: r("chat"),
    conversations: r("conversations"),
    analytics: r("analytics"),
    observability: r("observability"),
    "routing-logs": r("routing-logs"),
    channels: r("channels"),
    costs: r("costs"),
    marketplace: r("marketplace"),
    handoffs: r("handoffs"),
    learning: r("learning"),
    improvement: r("improvement"),
    knowledge: r("knowledge"),
    "kb-builder": r("kb-builder"),
    "workflow-builder": r("workflow-builder"),
    finance: r("finance"),
    marketing: r("marketing"),
    hr: r("hr"),
    operations: r("operations"),
    executive: r("executive"),
    workforce: r("workforce"),
    "self-learning": r("self-learning"),
    "workforce-overview": r("workforce-overview"),
    "agent-center": r("agent-center"),
    "communication-center": r("communication-center"),
    "casper-agentic-workflow": r("casper-agentic-workflow"),
    about: r("about"),
    "founder-story": r("founder-story"),
    "investor-demo": r("investor-demo"),
    multimedia: r("multimedia"),
    team: r("team"),
    security: r("security"),
    billing: r("billing"),
    settings: r("settings"),
  };
}

export function sidebar({ route, org, user, counts = {}, founderAccess = false, openSections = new Set() }) {
  const groups = getNavGroups().map(([key, label, groupIcon, links]) => [key, label, groupIcon, links.filter(([k]) => k !== "founder" || founderAccess)]).filter(([, , , links]) => links.length);
  const items = groups.map(([key, label, groupIcon, links]) => {
    const isOpen = openSections.has(key) || links.some(([k]) => k === route);
    const children = links.map(([k,l]) => {
      const isActive = route === k;
      const countBadge = counts[k] !== undefined ? `<span class="nav-count" aria-label="${counts[k]} items">${counts[k]}</span>` : '';
      return `<button class="nav-item ${isActive ? 'active' : ''}" data-route="${k}" aria-label="${esc(l)}" ${isActive ? 'aria-current="page"' : ''}>${icon(k)}<span>${l}</span>${countBadge}</button>`;
    }).join('');
    return `<div class="nav-group ${isOpen?'open':''}" role="group" aria-label="${esc(label)}"><button class="nav-group-toggle" data-nav-toggle="${key}" aria-expanded="${isOpen}" aria-label="${esc(label)} section">${icon(groupIcon)}<span>${label}</span><span class="nav-chevron" aria-hidden="true">${icon('arrow',12)}</span></button><div class="nav-group-items">${children}</div></div>`;
  }).join('');
  const planBadgeText = (org?.plan || 'free').toUpperCase();
  return `<div class="sidebar-head"><a class="brand" href="#dashboard" aria-label="BotNesia — Go to dashboard"><img class="brand-logo" src="${BRAND_LOGO}" alt="BotNesia logo"><span>BOTNESIA</span></a><div class="workspace-switcher" role="status" aria-label="Current workspace: ${esc(org?.name || 'Workspace')}, plan: ${planBadgeText}"><strong class="truncate">${esc(org?.name || 'Workspace')}</strong><small>${planBadgeText} · ${esc(org?.slug || 'tenant')}</small></div></div><nav class="nav" role="navigation" aria-label="Main navigation">${items}</nav><div class="sidebar-footer"><div class="user-chip"><span class="avatar" aria-hidden="true">${initials(user?.full_name || user?.email)}</span><div class="truncate"><strong class="truncate">${esc(user?.full_name || 'Workspace Admin')}</strong><small class="truncate">${esc(user?.email || '')}</small></div><button class="icon-button" data-action="logout" title="${t('signout')}" aria-label="${t('signout')}">${icon('arrow',14)}</button></div></div>`;
}

export function topbar({ route, health }) {
  const [title, description] = (getRouteMeta()[route] || getRouteMeta().dashboard);
  const isActive = health?.status === 'ok';
  return `<div class="topbar-left"><button class="icon-button mobile-menu" data-action="toggle-sidebar" aria-label="Toggle navigation menu" aria-expanded="false">${icon('menu')}</button><img class="topbar-logo" src="${BRAND_LOGO}" alt="BotNesia logo" aria-hidden="true"><div class="page-heading" role="heading" aria-level="1"><h1>${title}</h1><p>${description}</p></div></div><div class="topbar-actions" role="toolbar" aria-label="Topbar actions"><label class="search-box" aria-label="Global search">${icon('search',15)}<input data-global-search placeholder="${t('search_placeholder')}" aria-label="${t('search_placeholder')}" autocomplete="off"><kbd class="mono" aria-label="Shortcut: Command K">⌘K</kbd></label><span class="status-badge ${isActive?'active':'error'}" role="status" aria-live="polite">${isActive?t('status_active'):t('status_down')}</span>${langSwitcherHtml()}<button class="icon-button" data-action="notifications" title="Notifications" aria-label="Notifications">${icon('bell')}</button></div>`;
}

export function pageHeader(title, description, actions = "") { return `<div class="page-header"><div><span class="eyebrow" aria-hidden="true">BOTNESIA</span><h2>${esc(title)}</h2>${description ? `<p>${esc(description)}</p>` : ''}</div><div class="header-actions">${actions}</div></div>`; }
export function statusBadge(status = "unknown", label = status) { return `<span class="status-badge ${esc(status)}">${esc(label)}</span>`; }
export function metricCard(label, value, meta, iconName = "analytics", trend = "") { return `<article class="card metric-card card-hover"><div class="metric-top"><span class="metric-label">${esc(label)}</span><span class="metric-icon">${icon(iconName,16)}</span></div><div class="metric-value">${value}</div><div class="metric-meta ${trend}">${meta}</div></article>`; }
export function skeletonCards(count = 4) { return `<div class="grid grid-4">${Array.from({length:count},()=>'<div class="skeleton skeleton-card"></div>').join('')}</div>`; }
export function emptyState(title, description, action = "", iconName = "agents") { return `<div class="empty-state"><span class="state-icon">${icon(iconName,22)}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action ? `<div style="margin-top:16px">${action}</div>` : ''}</div>`; }
export function errorState(message) { return `<div class="error-state"><span class="state-icon">!</span><h3>${t('error.default')}</h3><p>${esc(message)}</p><button class="button" style="margin-top:14px" data-action="refresh">${icon('refresh',14)} ${t('error.retry_btn')}</button></div>`; }

export function planBadge(planKey) {
  const key = (planKey || 'free').toLowerCase();
  const labels = { free: t('plan.free'), standard: t('plan.standard'), pro: t('plan.pro'), enterprise: t('plan.enterprise') };
  return `<span class="plan-badge plan-badge-${key}">${labels[key] || esc(planKey)}</span>`;
}

export function lockCard(title, sub, requiredPlan = "Pro") {
  return `<div class="lock-card" aria-label="${esc(title)} — ${t('upgrade.feature_locked')}"><div class="lock-layer"><div class="lock-icon-wrap">🔒</div><p class="lock-title">${esc(title)}</p><p class="lock-sub">${esc(sub || `${t('upgrade.available_on')} ${requiredPlan}`)}</p><button class="button button-primary button-sm" data-action="show-upgrade-dialog" data-plan="${esc(requiredPlan)}">${t('upgrade.unlock')}</button></div></div>`;
}

export function upgradeDialog(requiredPlan = "Pro") {
  return modal({
    title: t('upgrade.title'),
    body: `<div style="text-align:center;padding:10px 0 6px"><div style="font-size:36px;margin-bottom:14px">🚀</div><p style="margin:0 0 8px;font-size:14px;font-weight:700">${t('upgrade.feature_locked')}</p><p style="margin:0;color:var(--text-2);font-size:12px;line-height:1.6">${t('upgrade.desc')}</p><div style="margin:18px 0 6px;display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border:1px solid rgba(139,124,255,.3);border-radius:10px;background:rgba(139,124,255,.08)"><span style="color:var(--brand);font-size:11px;font-weight:650">${t('upgrade.available_on')} <strong>${esc(requiredPlan)}</strong></span></div></div>`,
    footer: `<button class="button" data-action="close-modal">${t('cancel')}</button><button class="button button-primary" data-route="billing">${t('upgrade')}</button>`,
  });
}

export function upgradeBanner(title, sub) {
  return `<div class="upgrade-banner"><div class="upgrade-banner-copy"><strong>${esc(title)}</strong><p>${esc(sub)}</p></div><button class="button button-primary button-sm" data-route="billing">${icon('arrow',13)} ${t('upgrade')}</button></div>`;
}

export function settingSection(title, desc, content) {
  return `<section class="settings-section"><div class="settings-section-head"><h3>${esc(title)}</h3><p>${esc(desc)}</p></div>${content}</section>`;
}

export function settingRow(label, desc, control) {
  return `<div class="setting-row"><div class="setting-row-left"><strong>${esc(label)}</strong><p>${esc(desc)}</p></div><div class="setting-row-control">${control}</div></div>`;
}

export function readonlyField(label, value) {
  return `<div class="setting-row"><div class="setting-row-left"><strong>${esc(label)}</strong></div><div class="setting-row-control"><input style="min-width:200px;max-width:260px" class="input" value="${esc(value)}" readonly onclick="this.select()"></div></div>`;
}

export function agentCard(bot) {
  const status = bot.status || "inactive";
  return `<article class="card card-hover agent-card" data-agent-id="${esc(bot.id)}" role="button" tabindex="0" aria-label="Agent: ${esc(bot.name)}, status: ${esc(status)}"><div class="agent-card-top"><span class="agent-icon" aria-hidden="true">${initials(bot.name)}</span><div style="min-width:0;flex:1"><h3 class="truncate">${esc(bot.name)}</h3>${statusBadge(status)}</div><button class="icon-button" data-agent-id="${esc(bot.id)}" aria-label="More options for ${esc(bot.name)}">${icon('more',14)}</button></div><p>${esc(bot.greeting || 'AI agent configured for customer operations.')}</p><div class="agent-stats"><div><b>${formatNumber(bot.total_convs)}</b><span>${t('page.agents.convs')}</span></div><div><b>${formatNumber(bot.total_msgs)}</b><span>${t('page.agents.msgs')}</span></div></div></article>`;
}

export function activityItem(item) {
  return `<div class="activity-item"><span class="activity-symbol">${initials(item.channel || 'AI')}</span><div><strong>${esc(item.title)}</strong><p>${esc(item.description)}</p></div><span class="activity-time">${esc(item.time)}</span></div>`;
}

export function modal({ title, body, footer = "", wide = false }) {
  const titleId = `modal-title-${Math.random().toString(36).slice(2,8)}`;
  return `<div class="modal-backdrop" data-action="close-modal" role="presentation"><section class="modal" style="${wide?'width:min(760px,100%)':''}" role="dialog" aria-modal="true" aria-labelledby="${titleId}"><header class="modal-head"><strong id="${titleId}">${esc(title)}</strong><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close',16)}</button></header><div class="modal-body">${body}</div>${footer?`<footer class="modal-foot">${footer}</footer>`:''}</section></div>`;
}

export function agentDrawer(bot) {
  return `<div class="drawer-head"><div><span class="eyebrow">${t('agent.detail')}</span><h3 style="margin:7px 0 0">${esc(bot.name)}</h3></div><button class="icon-button" data-action="close-drawer">${icon('close')}</button></div><div class="drawer-body"><div class="drawer-section"><div class="agent-card-top"><span class="agent-icon">${initials(bot.name)}</span><div><strong>${esc(bot.name)}</strong><div style="margin-top:6px">${statusBadge(bot.status)}</div></div></div></div><form id="agent-detail-form" data-agent-id="${esc(bot.id)}"><div class="form-grid"><label class="field"><span>${t('agent.field.name')}</span><input name="name" value="${esc(bot.name)}" required></label><label class="field"><span>${t('agent.field.status')}</span><select name="status"><option value="active" ${bot.status==='active'?'selected':''}>${t('agent.status.active')}</option><option value="training" ${bot.status==='training'?'selected':''}>${t('agent.status.training')}</option><option value="inactive" ${bot.status==='inactive'?'selected':''}>${t('agent.status.inactive')}</option></select></label><label class="field full"><span>${t('agent.field.greeting')}</span><textarea name="greeting" style="min-height:90px">${esc(bot.greeting || '')}</textarea></label><label class="field full"><span>${t('agent.field.prompt')}</span><textarea name="system_prompt" placeholder="Define role, tone, boundaries, and business context...">${esc(bot.system_prompt || '')}</textarea></label><label class="field"><span>${t('agent.field.language')}</span><select name="language"><option value="id" ${bot.language==='id'?'selected':''}>Bahasa Indonesia</option><option value="en" ${bot.language==='en'?'selected':''}>English</option></select></label><label class="field"><span>${t('agent.field.color')}</span><input name="primary_color" type="color" value="${esc(bot.primary_color || '#8b7cff')}"></label><label class="field"><span>${t('agent.field.reasoning')}</span><select name="reasoning_mode"><option value="standard" ${bot.reasoning_mode!=='pro'?'selected':''}>${t('agent.field.reasoning_standard')}</option><option value="pro" ${bot.reasoning_mode==='pro'?'selected':''}>${t('agent.field.reasoning_pro')}</option></select><small style="color:var(--text-muted);display:block;margin-top:4px">${t('agent.field.reasoning_note')}</small></label><label class="field full"><span>Computer Agent</span><select name="computer_agent_enabled"><option value="false" ${!bot.computer_agent_enabled?'selected':''}>Nonaktif</option><option value="true" ${bot.computer_agent_enabled?'selected':''}>Aktif — bot bisa buka website &amp; screenshot</option></select><small style="color:var(--text-muted);display:block;margin-top:4px">Aktifkan agar bot bisa browsing web, screenshot halaman, dan mengisi form atas permintaan user</small></label></div><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px"><button class="button button-primary" type="submit">${t('agent.save_changes')}</button></div></form></div>`;
}

export function toast(message, type = "") {
  const root = document.getElementById("toast-region");
  const icons = { success: "✓", error: "✕", info: "ℹ" };
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.setAttribute("role", "alert");
  node.setAttribute("aria-live", type === "error" ? "assertive" : "polite");
  node.innerHTML = `${icons[type] ? `<span class="toast-icon" aria-hidden="true">${icons[type]}</span>` : ''}<span class="toast-body">${esc(message)}</span><button class="toast-dismiss" aria-label="Dismiss notification" onclick="this.closest('.toast').classList.add('removing');setTimeout(()=>this.closest('.toast')?.remove(),200)">✕</button>`;
  root.appendChild(node);
  setTimeout(() => { node.classList.add("removing"); setTimeout(() => node.remove(), 200); }, 4000);
}
