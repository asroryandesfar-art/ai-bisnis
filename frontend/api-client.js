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
  founderAccess: () => request("/api/founder/access"),
  founderOverview: () => request("/api/founder/overview"),

  bots: () => request("/bots"),
  createBot: (body) => request("/bots", { method: "POST", body }),
  updateBot: (id, body) => request(`/bots/${id}`, { method: "PATCH", body }),
  botAnalytics: (id, days = 30) => request(`/bots/${id}/analytics${encodeQuery({ days })}`),
  botConversations: (id, params = {}) => request(`/bots/${id}/conversations${encodeQuery(params)}`),
  routingLogs: (botId, params = {}) => request(`/bots/${botId}/routing-logs${encodeQuery(params)}`),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),
  messageSources: (messageId) => request(`/messages/${messageId}/sources`),
  chat: (botId, message, sessionId = null, userMeta = null) => request(`/chat/${botId}`, {
    method: "POST", body: { message, session_id: sessionId, user_meta: userMeta },
  }),

  marketplaceTemplates: () => request("/api/marketplace/templates"),
  marketplaceTemplate: (key) => request(`/api/marketplace/templates/${key}`),
  marketplaceCategories: () => request("/api/marketplace/categories"),
  marketplaceAnalytics: () => request("/api/marketplace/analytics"),
  marketplaceRecommended: (q = "", limit = 12) => request(`/api/marketplace/recommended${encodeQuery({ q, limit })}`),
  marketplaceSupervisorRoute: (message) => request("/api/marketplace/supervisor/route", { method: "POST", body: { message } }),
  marketplaceInstalls: () => request("/api/marketplace/installs"),
  installMarketplaceTemplate: (template_key, bot_name = null) => request("/api/marketplace/install", {
    method: "POST", body: { template_key, bot_name },
  }),
  updateMarketplaceInstall: (install_id, bot_name = null) => request(`/api/marketplace/installs/${install_id}/update`, {
    method: "POST", body: { bot_name },
  }),
  uninstallMarketplaceInstall: (install_id) => request(`/api/marketplace/installs/${install_id}/uninstall`, {
    method: "POST",
  }),

  transcribeAudio: (blob, filename = "recording.webm") => {
    const body = new FormData(); body.append("file", blob, filename);
    return request("/audio/transcribe", { method: "POST", body });
  },
  synthesizeSpeech: (text) => requestBlob("/audio/synthesize", { method: "POST", body: { text } }),
  speakText: (text) => request("/audio/speak", { method: "POST", body: { text } }),
  stopSpeech: () => request("/audio/stop", { method: "POST" }),

  imagesGenerate: (body) => request("/api/images/generate", { method: "POST", body }),
  imagesAnalyze: (file, { question = "", mode = "describe", botId = null, conversationId = null } = {}) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/api/images/analyze${encodeQuery({ question, mode, bot_id: botId, conversation_id: conversationId })}`, {
      method: "POST", body,
    });
  },
  imagesHistory: (params = {}) => request(`/api/images/history${encodeQuery(params)}`),
  documentsGenerate: (body) => request("/api/documents/generate", { method: "POST", body }),

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
  importFaqCsv: (botId, file) => {
    const body = new FormData(); body.append("file", file);
    return request(`/bots/${botId}/documents/faq-import`, { method: "POST", body });
  },
  knowledgeSources: (params = {}) => request(`/api/knowledge/sources${encodeQuery(params)}`),
  bulkKnowledgeUrls: (botId, urls, crawl = true) => request("/api/knowledge/urls/bulk", { method: "POST", body: { bot_id: botId, urls, crawl } }),
  seedKnowledgeGeneral: (botId, crawl = true) => request("/api/knowledge/seed/general", { method: "POST", body: { bot_id: botId, crawl } }),
  seedKnowledgeAgents: (botId, crawl = true) => request("/api/knowledge/seed/agents", { method: "POST", body: { bot_id: botId, crawl } }),
  seedKnowledgeAgent: (agentType, botId, crawl = true) => request(`/api/knowledge/seed/${agentType}`, { method: "POST", body: { bot_id: botId, crawl } }),
  seedMarketplaceKnowledge: (botId = null, crawl = false, installedOnly = false) => request("/api/knowledge/seed/marketplace-1000", { method: "POST", body: { bot_id: botId, crawl, installed_only: installedOnly } }),
  knowledgeSeedStatus: (params = {}) => request(`/api/knowledge/seed/status${encodeQuery(params)}`),
  retryFailedKnowledgeSources: (body = {}) => request("/api/knowledge/sources/retry-failed", { method: "POST", body }),
  retryKnowledgeSource: (sourceId) => request(`/api/knowledge/sources/${sourceId}/retry`, { method: "POST" }),
  deleteKnowledgeSource: (sourceId) => request(`/api/knowledge/sources/${sourceId}`, { method: "DELETE" }),

  kbOverview: (botId) => request(`/api/knowledge-builder/bots/${botId}/overview`),
  kbRegenerate: (botId, docId) => request(`/api/knowledge-builder/bots/${botId}/documents/${docId}/generate`, { method: "POST" }),
  kbFaqs: (botId, status = null) => request(`/api/knowledge-builder/bots/${botId}/faqs${encodeQuery({ status })}`),
  kbUpdateFaq: (faqId, body) => request(`/api/knowledge-builder/faqs/${faqId}`, { method: "PATCH", body }),
  kbSops: (botId, status = null) => request(`/api/knowledge-builder/bots/${botId}/sops${encodeQuery({ status })}`),
  kbUpdateSop: (sopId, body) => request(`/api/knowledge-builder/sops/${sopId}`, { method: "PATCH", body }),
  kbQuality: (botId) => request(`/api/knowledge-builder/bots/${botId}/quality`),

  wfNodeCatalog: () => request("/api/workflow-builder/node-catalog"),
  wfList: (botId) => request(`/api/workflow-builder/bots/${botId}/workflows`),
  wfCreate: (botId, body) => request(`/api/workflow-builder/bots/${botId}/workflows`, { method: "POST", body }),
  wfGet: (workflowId) => request(`/api/workflow-builder/workflows/${workflowId}`),
  wfUpdate: (workflowId, body) => request(`/api/workflow-builder/workflows/${workflowId}`, { method: "PATCH", body }),
  wfDelete: (workflowId) => request(`/api/workflow-builder/workflows/${workflowId}`, { method: "DELETE" }),
  wfPublish: (workflowId) => request(`/api/workflow-builder/workflows/${workflowId}/publish`, { method: "POST" }),
  wfUnpublish: (workflowId) => request(`/api/workflow-builder/workflows/${workflowId}/unpublish`, { method: "POST" }),
  wfTest: (workflowId, payload = {}) => request(`/api/workflow-builder/workflows/${workflowId}/test`, { method: "POST", body: { payload } }),
  wfExecutions: (workflowId) => request(`/api/workflow-builder/workflows/${workflowId}/executions`),
  wfExecution: (executionId) => request(`/api/workflow-builder/executions/${executionId}`),

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
  disconnectChannel: (id) => request("/api/channels/disconnect", { method: "POST", body: { connection_id:id } }),
  channelStatus: (refresh = false) => request(`/api/channels/status${encodeQuery({ refresh })}`),
  channelAnalytics: (days = 30) => request(`/api/channels/analytics${encodeQuery({ days })}`),
  integrations: () => request("/integrations"),
  saveMeta: (body) => request("/integrations/meta", { method: "POST", body }),
  mapMetaBot: (waPhoneNumberId, botId) => request("/integrations/meta/map-bot", { method: "POST", body: { wa_phone_number_id: waPhoneNumberId, bot_id: botId } }),
  sendMetaTest: (toNumber, text) => request("/integrations/meta/send-test", { method: "POST", body: { to_number: toNumber, text } }),
  gmailStart: () => request("/integrations/gmail/start", { method: "POST" }),
  gmailMapBot: (botId) => request("/integrations/gmail/map-bot", { method: "POST", body: { bot_id: botId } }),
  gmailPoll: () => request("/integrations/gmail/poller/run-once", { method: "POST" }),
  gmailPoller: () => request("/integrations/gmail/poller"),
  deleteIntegration: (key) => request("/integrations/" + key, { method: "DELETE" }),
  whatsappEmbeddedConnect: (botId) => request(`/integrations/whatsapp/connect${encodeQuery({ bot_id: botId })}`),
  whatsappEmbeddedCallback: (body) => request("/integrations/whatsapp/callback", { method: "POST", body }),
  whatsappEmbeddedStatus: (botId = null) => request(`/integrations/whatsapp/status${encodeQuery(botId ? { bot_id: botId } : {})}`),
  whatsappEmbeddedDisconnect: (botId) => request("/integrations/whatsapp/disconnect", { method: "POST", body: { bot_id: botId } }),
  metaOAuthStart: (botId, channel) => request("/api/integrations/meta/oauth/start", { method: "POST", body: { bot_id: botId, channel } }),
  metaOAuthStatus: () => request("/api/integrations/meta/oauth/status"),
  metaOAuthSelect: (body) => request("/api/integrations/meta/oauth/select", { method: "POST", body }),
  metaOAuthRefresh: () => request("/api/integrations/meta/oauth/refresh", { method: "POST" }),
  metaOAuthDisconnect: (channels) => request("/api/integrations/meta/oauth/disconnect", { method: "POST", body: { channels } }),
  observabilitySummary: (days = 7) => request("/api/observability/summary" + encodeQuery({ days })),
  observabilityTrace: (traceId) => request("/api/observability/traces/" + traceId),
  costIntelligence: () => request("/api/cost-intelligence/summary"),
  updateCostBudget: (monthly_budget_usd) => request("/api/cost-intelligence/budget", { method: "PUT", body: { monthly_budget_usd } }),
  submitFeedback: (message_id, conversation_id, rating, comment = null) => request("/api/feedback-learning/feedback", { method: "POST", body: { message_id, conversation_id, rating, comment } }),
  feedbackSummary: (days = 30) => request("/api/feedback-learning/summary" + encodeQuery({ days })),
  feedbackQueue: (params = {}) => request(`/api/feedback-learning/queue${encodeQuery(params)}`),
  updateFeedbackQueue: (id, status, resolution_note = null) => request(`/api/feedback-learning/queue/${id}`, { method: "PATCH", body: { status, resolution_note } }),
  improvementDashboard: (days = 30) => request(`/api/improvement/dashboard${encodeQuery({ days })}`),
  improvementRecommendations: (params = {}) => request(`/api/improvement/recommendations${encodeQuery(params)}`),
  updateImprovementRecommendation: (id, body) => request(`/api/improvement/recommendations/${id}`, { method: "PATCH", body }),
  improvementScan: (days = 30) => request(`/api/improvement/scan${encodeQuery({ days })}`, { method: "POST" }),
  auditLogs: (params = {}) => request(`/api/security/audit-logs${encodeQuery(params)}`),
  securityScan: () => request("/api/security/scan", { method: "POST" }),
  securityDashboard: () => request("/api/security/dashboard"),
  securitySessions: (scope = "me") => request(`/api/security/sessions${encodeQuery({ scope })}`),
  revokeSecuritySession: (id) => request(`/api/security/sessions/${id}/revoke`, { method: "POST" }),
  securityApiKeys: () => request("/api/security/api-keys"),
  createApiKey: (body) => request("/api-keys", { method: "POST", body }),
  rotateApiKey: (id) => request(`/api/security/api-keys/${id}/rotate`, { method: "POST" }),
  revokeApiKey: (id) => request(`/api/security/api-keys/${id}`, { method: "DELETE" }),
  financeDashboard: () => request("/api/finance/dashboard"),
  financeRevenueReport: (period_days = 30) => request(`/api/finance/reports/revenue${encodeQuery({ period_days })}`),
  financeProfitReport: (period_days = 30) => request(`/api/finance/reports/profit${encodeQuery({ period_days })}`),
  financeCashflowReport: (period_days = 30) => request(`/api/finance/reports/cashflow${encodeQuery({ period_days })}`),
  financeForecast: (months_back = 3) => request(`/api/finance/reports/forecast${encodeQuery({ months_back })}`),
  financeReminders: () => request("/api/finance/reminders"),
  financeInvoices: (params = {}) => request(`/api/finance/invoices${encodeQuery(params)}`),
  financeCreateInvoice: (body) => request("/api/finance/invoices", { method: "POST", body }),
  financeUpdateInvoiceStatus: (id, status) => request(`/api/finance/invoices/${id}/status`, { method: "PATCH", body: { status } }),
  financeDeleteInvoice: (id) => request(`/api/finance/invoices/${id}`, { method: "DELETE" }),
  financePayments: (limit = 50) => request(`/api/finance/payments${encodeQuery({ limit })}`),
  financeCreatePayment: (body) => request("/api/finance/payments", { method: "POST", body }),
  financeExpenses: (params = {}) => request(`/api/finance/expenses${encodeQuery(params)}`),
  financeCreateExpense: (body) => request("/api/finance/expenses", { method: "POST", body }),
  financeApproveExpense: (id, approve) => request(`/api/finance/expenses/${id}/approval`, { method: "PATCH", body: { approve } }),
  financeParse: (text, bot_id = null) => request("/api/finance/parse", { method: "POST", body: { text, bot_id } }),
};

export async function settle(label, promise) {
  try { return { label, ok: true, data: await promise }; }
  catch (error) { return { label, ok: false, error }; }
}
