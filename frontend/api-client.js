const TOKEN_KEY = "bn_token";

export class APIError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.data = data;
  }
}

function encodeQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

async function requestBlob(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = options.body;
  if (body && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { ...options, headers, body });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new APIError(response.status, data.detail || data.message || `Request gagal (${response.status})`, data);
  }
  return response.blob();
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { ...options, headers, body });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new CustomEvent("botnesia:unauthorized"));
  }
  if (!response.ok) {
    const message = typeof data === "object" ? data.detail || data.message : data;
    throw new APIError(response.status, message || `Request gagal (${response.status})`, data);
  }
  return data;
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (value) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export const api = {
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),
  register: (org_name, email, password) => request("/auth/register", { method: "POST", body: { org_name, email, password } }),
  health: () => request("/health", { cache: "no-store" }),
  org: () => request("/org"),
  updateLegacyPlan: (plan) => request("/org/plan", { method: "PATCH", body: { plan } }),
  dashboardOverview: () => request("/api/dashboard/overview"),

  bots: () => request("/bots"),
  createBot: (body) => request("/bots", { method: "POST", body }),
  updateBot: (id, body) => request(`/bots/${id}`, { method: "PATCH", body }),
  botAnalytics: (id, days = 30) => request(`/bots/${id}/analytics${encodeQuery({ days })}`),
  botConversations: (id, params = {}) => request(`/bots/${id}/conversations${encodeQuery(params)}`),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),
  messageSources: (messageId) => request(`/messages/${messageId}/sources`),
  chat: (botId, message, sessionId = null, userMeta = null) => request(`/chat/${botId}`, {
    method: "POST", body: { message, session_id: sessionId, user_meta: userMeta },
  }),

  transcribeAudio: (blob, filename = "recording.webm") => {
    const body = new FormData(); body.append("file", blob, filename);
    return request("/audio/transcribe", { method: "POST", body });
  },
  synthesizeSpeech: (text) => requestBlob("/audio/synthesize", { method: "POST", body: { text } }),
  speakText: (text) => request("/audio/speak", { method: "POST", body: { text } }),
  stopSpeech: () => request("/audio/stop", { method: "POST" }),

  documents: (botId) => request(`/bots/${botId}/documents`),
  uploadDocument: (botId, file) => {
    const body = new FormData(); body.append("file", file);
    return request(`/bots/${botId}/documents`, { method: "POST", body });
  },
  uploadDocumentUrl: (botId, url, title = null) => request(`/bots/${botId}/documents/url`, {
    method: "POST",
    body: { url, title },
  }),
  deleteDocument: (botId, documentId) => request(`/bots/${botId}/documents/${documentId}`, { method: "DELETE" }),

  team: () => request("/api/rbac/team"),
  rbacMe: () => request("/api/rbac/me"),
  roles: () => request("/api/rbac/roles"),
  assignRole: (userId, roleKey) => request("/api/rbac/assign", { method: "POST", body: { user_id: userId, role_key: roleKey } }),
  inviteMember: (body) => request("/api/rbac/invite", { method: "POST", body }),
  revokeRole: (userId, roleKey) => request("/api/rbac/revoke", { method: "POST", body: { user_id: userId, role_key: roleKey } }),

  plans: () => request("/api/billing/plans"),
  subscription: () => request("/api/billing/subscription"),
  usage: () => request("/api/billing/usage"),
  checkout: (planKey, billingCycle = "monthly", provider = "midtrans") => request("/api/billing/checkout", {
    method: "POST", body: { plan_key: planKey, billing_cycle: billingCycle, provider },
  }),
  invoices: () => request("/api/billing/invoices"),

  inbox: (params = {}) => request(`/api/inbox${encodeQuery(params)}`),
  inboxSummary: () => request("/api/inbox/summary"),
  handoffQueue: (params = {}) => request(`/api/handoff/queue${encodeQuery(params)}`),
  handoffStats: () => request("/api/handoff/stats"),
  claimHandoff: (id) => request(`/api/handoff/${id}/claim`, { method: "POST" }),
  replyHandoff: (id, message) => request(`/api/handoff/${id}/reply`, { method: "POST", body: { message } }),
  resolveHandoff: (id, note = null) => request(`/api/handoff/${id}/resolve`, { method: "POST", body: { note } }),

  channels: () => request("/api/channels"),
  connectChannel: (body) => request("/api/channels/connect", { method: "POST", body }),
  disconnectChannel: (id) => request("/api/channels/" + id, { method: "DELETE" }),
  integrations: () => request("/integrations"),
  saveMeta: (body) => request("/integrations/meta", { method: "POST", body }),
  mapMetaBot: (waPhoneNumberId, botId) => request("/integrations/meta/map-bot", { method: "POST", body: { wa_phone_number_id: waPhoneNumberId, bot_id: botId } }),
  sendMetaTest: (toNumber, text) => request("/integrations/meta/send-test", { method: "POST", body: { to_number: toNumber, text } }),
  gmailStart: () => request("/integrations/gmail/start", { method: "POST" }),
  gmailMapBot: (botId) => request("/integrations/gmail/map-bot", { method: "POST", body: { bot_id: botId } }),
  gmailPoll: () => request("/integrations/gmail/poller/run-once", { method: "POST" }),
  gmailPoller: () => request("/integrations/gmail/poller"),
  deleteIntegration: (key) => request("/integrations/" + key, { method: "DELETE" }),
  observabilitySummary: (days = 7) => request("/api/observability/summary" + encodeQuery({ days })),
  observabilityTrace: (traceId) => request("/api/observability/traces/" + traceId),
  costIntelligence: () => request("/api/cost-intelligence/summary"),
  updateCostBudget: (monthly_budget_usd) => request("/api/cost-intelligence/budget", { method: "PUT", body: { monthly_budget_usd } }),
  auditLogs: (params = {}) => request(`/api/security/audit-logs${encodeQuery(params)}`),
  securityScan: () => request("/api/security/scan", { method: "POST" }),
};

export async function settle(label, promise) {
  try { return { label, ok: true, data: await promise }; }
  catch (error) { return { label, ok: false, error }; }
}
