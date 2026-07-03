import { tokenStore } from "../auth/tokenStore";

// Mirrors frontend/api-client.js's request() contract exactly (same error
// shape, same 401 handling, same base-URL-from-origin idea) so the same
// mental model/backend contract applies on mobile -- just no DOM `fetch`
// quirks and no localStorage.
export class APIError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data: unknown = null) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.data = data;
  }
}

const API_BASE = process.env.EXPO_PUBLIC_API_BASE || "https://api.botnesia.uk";

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
export function onUnauthorized(fn: Listener) {
  unauthorizedListeners.add(fn);
  return () => {
    unauthorizedListeners.delete(fn);
  };
}

export async function request<T = any>(
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {}
): Promise<T> {
  const token = await tokenStore.get();
  const headers: Record<string, string> = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: any;
  if (options.body instanceof FormData) {
    // Let fetch set its own multipart Content-Type (with boundary) --
    // forcing application/json here would break the upload.
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { method: options.method || "GET", headers, body });
  } catch {
    // Real network failure (offline, DNS, etc) -- same humanized-message
    // pattern used on the web dashboard, not a raw fetch exception.
    throw new APIError(0, "API tidak dapat dihubungi. Periksa koneksi internet Anda.");
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();

  if (response.status === 401) {
    await tokenStore.clear();
    unauthorizedListeners.forEach((fn) => fn());
  }

  if (!response.ok) {
    const message = typeof data === "object" && data ? (data as any).detail || (data as any).message : String(data);
    throw new APIError(response.status, message || `Request gagal (${response.status})`, data);
  }
  return data as T;
}

export const api = {
  login: (email: string, password: string) => request<{ token: string }>("/auth/login", { method: "POST", body: { email, password } }),
  register: (orgName: string, email: string, password: string) =>
    request<{ token: string; org_id: string; trial_ends: string }>("/auth/register", {
      method: "POST",
      body: { org_name: orgName, email, password },
    }),
  health: () => request<{ status: string; db: boolean; schema: boolean; ai: { configured: boolean; providers?: Record<string, any> } }>("/health"),
  integrations: () => request<{ gmail: { connected: boolean; email: string | null; bot_id: string | null } }>("/integrations"),
  gmailStart: () => request<{ auth_url: string }>("/integrations/gmail/start", { method: "POST" }),
  gmailMapBot: (botId: string) => request<any>("/integrations/gmail/map-bot", { method: "POST", body: { bot_id: botId } }),
  gmailPoll: () => request<any>("/integrations/gmail/poller/run-once", { method: "POST" }),
  deleteIntegration: (key: string) => request<any>(`/integrations/${key}`, { method: "DELETE" }),
  securityScan: () => request<{ score: number; findings_count: number; findings: any[] }>("/api/security/scan", { method: "POST" }),
  dashboardOverview: () => request("/api/dashboard/overview"),
  bots: () => request<any[]>("/bots"),
  agentCenterOverview: () => request("/api/agent-center/overview"),
  org: () => request("/org"),
  team: () => request<{ team: any[] }>("/api/rbac/team"),
  rbacRoles: () => request<{ roles: any[] }>("/api/rbac/roles"),
  rbacMe: () => request<{ user_id: string; roles: string[]; permissions: string[] }>("/api/rbac/me"),
  inviteMember: (body: { email: string; full_name?: string; role_key: string; password: string }) =>
    request<any>("/api/rbac/invite", { method: "POST", body }),
  assignRole: (userId: string, roleKey: string) => request<any>("/api/rbac/assign", { method: "POST", body: { user_id: userId, role_key: roleKey } }),
  revokeRole: (userId: string, roleKey: string) => request<any>("/api/rbac/revoke", { method: "POST", body: { user_id: userId, role_key: roleKey } }),
  billingSubscription: () => request("/api/billing/subscription"),
  billingPlans: () => request<{ plans: any[] }>("/api/billing/plans"),
  billingCheckout: (planKey: string, billingCycle: "monthly" | "yearly" = "monthly", useFreeTrial = false) =>
    request<{ requires_payment: boolean; redirect_url?: string }>("/api/billing/checkout", {
      method: "POST",
      body: { plan_key: planKey, billing_cycle: billingCycle, provider: "midtrans", use_free_trial: useFreeTrial },
    }),
  invoices: () => request<{ invoices: any[] }>("/api/billing/invoices"),
  credits: () => request<any>("/api/billing/credits"),
  topupCredits: (amountIdr: number) =>
    request<{ redirect_url?: string }>("/api/billing/credits/topup", {
      method: "POST",
      body: { amount_idr: amountIdr, provider: "midtrans" },
    }),

  // Approval queues -- same 3 real queues wired into the web Agent Center
  // this session (local-agent risky actions, browser Computer Agent tasks,
  // outbound Channel Messaging) -- merged into one feed on this screen.
  localAgentPending: () => request<{ commands: any[] }>("/api/local-agent/history?status=pending_approval"),
  localAgentApprove: (id: string) => request(`/api/local-agent/commands/${id}/approve`, { method: "POST" }),
  localAgentReject: (id: string, reason: string) =>
    request(`/api/local-agent/commands/${id}/reject`, { method: "POST", body: { reason } }),

  computerAgentPending: () => request<{ tasks: any[] }>("/api/computer-agent/tasks?status=pending_approval"),
  computerAgentTasksAll: () => request<{ tasks: any[] }>("/api/computer-agent/tasks?limit=50"),
  computerAgentRunLocal: (goal: string, timeout = 30) =>
    request<any>("/api/computer-agent/run-local", { method: "POST", body: { goal, timeout } }),
  computerAgentApprove: (id: string) => request(`/api/computer-agent/tasks/${id}/approve`, { method: "POST" }),
  computerAgentReject: (id: string, reason: string) =>
    request(`/api/computer-agent/tasks/${id}/reject`, { method: "POST", body: { reason } }),

  channelMessagingPending: () => request<{ tasks: any[] }>("/api/channel-messaging/tasks?status=pending_approval"),
  channelMessagingApprove: (id: string) => request(`/api/channel-messaging/tasks/${id}/approve`, { method: "POST" }),
  channelMessagingReject: (id: string, reason: string) =>
    request(`/api/channel-messaging/tasks/${id}/reject`, { method: "POST", body: { reason } }),

  workforceTasks: (params: { status?: string } = {}) =>
    request<{ tasks: any[] }>(`/api/workforce/tasks${params.status ? `?status=${params.status}` : ""}`),
  createWorkforceTask: (body: Record<string, any>) =>
    request<any>("/api/workforce/tasks", { method: "POST", body }),
  updateWorkforceTaskStatus: (id: string, status: string) =>
    request<any>(`/api/workforce/tasks/${id}/status`, { method: "PATCH", body: { status } }),
  approveWorkforceTask: (id: string) =>
    request<any>(`/api/workforce/tasks/${id}/approve`, { method: "POST" }),
  scanWorkforceConflicts: () =>
    request<any>("/api/workforce/scan-conflicts", { method: "POST" }),

  // Workflow Builder -- "automations" (trigger-based, per-bot; the route also
  // returns global bot_id IS NULL workflows, so aggregate + dedupe by id).
  wfList: (botId: string) => request<any>(`/api/workflow-builder/bots/${botId}/workflows`),
  wfTest: (workflowId: string) =>
    request<any>(`/api/workflow-builder/workflows/${workflowId}/test`, { method: "POST", body: { payload: {} } }),

  // Business-command-center dashboards -- same 7 sub-dashboards the web
  // renderDashboard() aggregates. Each is permission-gated (finance.read etc)
  // so callers should tolerate failure (Promise.allSettled), matching the web
  // settle() pattern.
  // Public customer-facing chat pipeline -- reused as the in-app playground
  // (same as web renderChat). Returns { answer, session_id, ... }.
  chat: (botId: string, message: string, sessionId?: string | null) =>
    request<{ answer: string; session_id: string; image_url?: string }>(`/chat/${botId}`, {
      method: "POST",
      body: { message, session_id: sessionId || null },
    }),
  createBot: (body: Record<string, any>) => request<any>("/bots", { method: "POST", body }),
  updateBot: (id: string, body: Record<string, any>) => request<any>(`/bots/${id}`, { method: "PATCH", body }),
  botAnalytics: (botId: string, days = 30) => request<any>(`/bots/${botId}/analytics?days=${days}`),
  handoffQueue: (params: { limit?: number } = {}) =>
    request<{ queue: any[] }>(`/api/handoff/queue${params.limit ? `?limit=${params.limit}` : ""}`),
  handoffStats: () => request<{ stats: any }>("/api/handoff/stats"),
  claimHandoff: (id: string) => request<any>(`/api/handoff/${id}/claim`, { method: "POST" }),
  replyHandoff: (id: string, message: string) => request<any>(`/api/handoff/${id}/reply`, { method: "POST", body: { message } }),
  resolveHandoff: (id: string, note?: string | null) => request<any>(`/api/handoff/${id}/resolve`, { method: "POST", body: { note: note ?? null } }),

  // Channels -- mirrors web's renderChannels (frontend/app.js).
  channelStatus: (refresh = false) => request<{ channels: any[]; summary: any }>(`/api/channels/status${refresh ? "?refresh=true" : ""}`),
  channelAnalytics: (days = 30) => request<any>(`/api/channels/analytics?days=${days}`),
  connectChannel: (body: { bot_id: string; channel_type: string; display_name: string; external_id?: string | null; credentials?: any; config?: any }) =>
    request<{ channel: any }>("/api/channels/connect", { method: "POST", body }),
  disconnectChannel: (connectionId: string) => request<any>("/api/channels/disconnect", { method: "POST", body: { connection_id: connectionId } }),
  whatsappEmbeddedStatus: () => request<{ accounts: any[] }>("/integrations/whatsapp/status"),
  whatsappEmbeddedConnect: (botId: string) =>
    request<{ app_id: string; config_id: string; graph_api_version: string; state: string; bot_id: string }>(
      `/integrations/whatsapp/connect?bot_id=${botId}`
    ),
  whatsappEmbeddedCallback: (body: { state: string; code: string; waba_id: string; phone_number_id: string; business_id?: string | null }) =>
    request<any>("/integrations/whatsapp/callback", { method: "POST", body }),
  whatsappEmbeddedDisconnect: (botId: string) =>
    request<any>("/integrations/whatsapp/disconnect", { method: "POST", body: { bot_id: botId } }),
  metaOAuthStatus: () =>
    request<{ connected: boolean; status: string; pages: any[]; token_expires_at: string | null; selected: any }>(
      "/api/integrations/meta/oauth/status"
    ),
  metaOAuthStart: (botId: string, channel: "facebook" | "instagram") =>
    request<{ auth_url: string; state: string }>("/api/integrations/meta/oauth/start", { method: "POST", body: { bot_id: botId, channel } }),
  metaOAuthSelect: (body: { bot_id: string; page_id: string; channels: string[]; instagram_id?: string }) =>
    request<any>("/api/integrations/meta/oauth/select", { method: "POST", body }),
  metaOAuthRefresh: () => request<any>("/api/integrations/meta/oauth/refresh", { method: "POST" }),

  // Chat Inbox -- real customer conversations (distinct from `chat()` above,
  // which is the admin-facing test playground). Mirrors web's renderConversations
  // / renderMessagePanel (frontend/app.js).
  botConversations: (botId: string, params: { limit?: number; offset?: number } = {}) =>
    request<any[]>(`/bots/${botId}/conversations?limit=${params.limit ?? 20}&offset=${params.offset ?? 0}`),
  conversationMessages: (convId: string) => request<any[]>(`/conversations/${convId}/messages`),
  messageSources: (messageId: string) => request<any[]>(`/messages/${messageId}/sources`),
  submitFeedback: (messageId: string, conversationId: string, rating: "helpful" | "not_helpful", comment?: string | null) =>
    request<any>("/api/feedback-learning/feedback", {
      method: "POST",
      body: { message_id: messageId, conversation_id: conversationId, rating, comment: comment ?? null },
    }),
  knowledgeSources: (params: { botId?: string; status?: string; category?: string; agentId?: string; search?: string } = {}) => {
    const q = new URLSearchParams({ limit: "100" });
    if (params.botId) q.set("bot_id", params.botId);
    if (params.status) q.set("status", params.status);
    if (params.category) q.set("category", params.category);
    if (params.agentId) q.set("agent_id", params.agentId);
    if (params.search) q.set("search", params.search);
    return request<{ sources: any[]; stats: any }>(`/api/knowledge/sources?${q.toString()}`);
  },
  knowledgeSeedStatus: (botId: string) => request<any>(`/api/knowledge/seed/status?bot_id=${botId}`),
  uploadDocument: (botId: string, file: { uri: string; name: string; mimeType?: string | null }) => {
    const form = new FormData();
    form.append("file", { uri: file.uri, name: file.name, type: file.mimeType || "application/octet-stream" } as any);
    return request<any>(`/bots/${botId}/documents`, { method: "POST", body: form });
  },
  documents: (botId: string) => request<any[]>(`/bots/${botId}/documents`),
  deleteDocument: (botId: string, docId: string) => request<any>(`/bots/${botId}/documents/${docId}`, { method: "DELETE" }),
  bulkKnowledgeUrls: (botId: string, urls: Record<string, any>[], crawl = true) =>
    request<{ imported: number; skipped_duplicate: number; skipped_invalid: number; total: number; stats: any }>(
      "/api/knowledge/urls/bulk",
      { method: "POST", body: { bot_id: botId, urls, crawl } }
    ),
  seedKnowledgeGeneral: (botId: string, crawl = true) =>
    request<any>("/api/knowledge/seed/general", { method: "POST", body: { bot_id: botId, crawl } }),
  seedKnowledgeAgents: (botId: string, crawl = true) =>
    request<any>("/api/knowledge/seed/agents", { method: "POST", body: { bot_id: botId, crawl } }),
  seedKnowledgeAgent: (agentType: string, botId: string, crawl = true) =>
    request<any>(`/api/knowledge/seed/${agentType}`, { method: "POST", body: { bot_id: botId, crawl } }),
  seedMarketplaceKnowledge: (botId: string | null = null, crawl = false, installedOnly = false) =>
    request<any>("/api/knowledge/seed/marketplace-1000", { method: "POST", body: { bot_id: botId, crawl, installed_only: installedOnly } }),
  retryFailedKnowledgeSources: (body: { bot_id?: string | null; agent_id?: string | null; category?: string | null; crawl?: boolean } = {}) =>
    request<{ retried: number; crawler: string }>("/api/knowledge/sources/retry-failed", { method: "POST", body }),
  retryKnowledgeSource: (sourceId: string) => request<any>(`/api/knowledge/sources/${sourceId}/retry`, { method: "POST" }),
  deleteKnowledgeSource: (sourceId: string) => request<any>(`/api/knowledge/sources/${sourceId}`, { method: "DELETE" }),

  // Knowledge Builder (FAQ/SOP auto-generation) -- mirrors web's
  // renderKnowledgeBuilder (frontend/app.js).
  kbOverview: (botId: string) => request<any>(`/api/knowledge-builder/bots/${botId}/overview`),
  kbRegenerate: (botId: string, docId: string) =>
    request<any>(`/api/knowledge-builder/bots/${botId}/documents/${docId}/generate`, { method: "POST" }),
  kbFaqs: (botId: string, status?: string | null) =>
    request<{ faqs: any[] }>(`/api/knowledge-builder/bots/${botId}/faqs${status ? `?status=${status}` : ""}`),
  kbUpdateFaq: (faqId: string, body: { status?: string; question?: string; answer?: string; category?: string }) =>
    request<any>(`/api/knowledge-builder/faqs/${faqId}`, { method: "PATCH", body }),
  kbSops: (botId: string, status?: string | null) =>
    request<{ sops: any[] }>(`/api/knowledge-builder/bots/${botId}/sops${status ? `?status=${status}` : ""}`),
  kbUpdateSop: (sopId: string, body: { status?: string; title?: string; steps?: string[]; category?: string }) =>
    request<any>(`/api/knowledge-builder/sops/${sopId}`, { method: "PATCH", body }),
  importFaqCsv: (botId: string, file: { uri: string; name: string; mimeType?: string | null }) => {
    const form = new FormData();
    form.append("file", { uri: file.uri, name: file.name, type: file.mimeType || "text/csv" } as any);
    return request<any>(`/bots/${botId}/documents/faq-import`, { method: "POST", body: form });
  },
  financeDashboard: () => request<any>("/api/finance/dashboard"),
  marketingDashboard: () => request<any>("/api/marketing/dashboard"),
  hrDashboard: () => request<any>("/api/hr/dashboard"),
  opsDashboard: () => request<any>("/api/operations/dashboard"),
  securityDashboard: () => request<any>("/api/security/dashboard"),
  executiveDashboard: () => request<any>("/api/executive/dashboard"),
  workforceDashboard: () => request<any>("/api/workforce/dashboard"),

  // Security Dashboard -- mirrors web's renderSecurity (frontend/app.js).
  securityScanAndAlert: () => request<any>("/api/security/scan-and-alert", { method: "POST" }),
  securityRiskAlerts: (params: { status_filter?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.status_filter) q.set("status_filter", params.status_filter);
    if (params.limit) q.set("limit", String(params.limit));
    return request<{ alerts: any[] }>(`/api/security/risk-alerts?${q.toString()}`);
  },
  updateSecurityRiskAlert: (id: string, status: string) =>
    request<any>(`/api/security/risk-alerts/${id}`, { method: "PATCH", body: { status } }),
  securityReports: (params: { limit?: number } = {}) =>
    request<{ reports: any[] }>(`/api/security/reports${params.limit ? `?limit=${params.limit}` : ""}`),
  generateSecurityReport: (reportType: string) =>
    request<any>("/api/security/reports/generate", { method: "POST", body: { report_type: reportType } }),
  revokeSecuritySession: (id: string) => request<any>(`/api/security/sessions/${id}/revoke`, { method: "POST" }),
  createApiKey: (body: { name: string; expires_in_days?: number }) => request<{ key: string }>("/api-keys", { method: "POST", body }),
  rotateApiKey: (id: string) => request<{ key: string }>(`/api/security/api-keys/${id}/rotate`, { method: "POST" }),
  revokeApiKey: (id: string) => request<any>(`/api/security/api-keys/${id}`, { method: "DELETE" }),
};
