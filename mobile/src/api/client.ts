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
  return () => unauthorizedListeners.delete(fn);
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
  health: () => request("/health"),
  dashboardOverview: () => request("/api/dashboard/overview"),
  bots: () => request<any[]>("/bots"),
  agentCenterOverview: () => request("/api/agent-center/overview"),
  org: () => request("/org"),
  team: () => request("/api/rbac/team"),
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
  knowledgeSources: () => request<{ sources: any[]; stats: any }>("/api/knowledge/sources?limit=100"),
  uploadDocument: (botId: string, file: { uri: string; name: string; mimeType?: string | null }) => {
    const form = new FormData();
    form.append("file", { uri: file.uri, name: file.name, type: file.mimeType || "application/octet-stream" } as any);
    return request<any>(`/bots/${botId}/documents`, { method: "POST", body: form });
  },
  financeDashboard: () => request<any>("/api/finance/dashboard"),
  marketingDashboard: () => request<any>("/api/marketing/dashboard"),
  hrDashboard: () => request<any>("/api/hr/dashboard"),
  opsDashboard: () => request<any>("/api/operations/dashboard"),
  securityDashboard: () => request<any>("/api/security/dashboard"),
  executiveDashboard: () => request<any>("/api/executive/dashboard"),
  workforceDashboard: () => request<any>("/api/workforce/dashboard"),
};
