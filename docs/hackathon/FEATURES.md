# BotNesia — Feature List

Every item below is implemented and live-verified against the running
production instance, not aspirational. ✔ = built, tested, live. 🔜 = not
yet built (see [`ROADMAP.md`](ROADMAP.md)).

## Multi-Agent AI Core
- ✔ Multi Agent Collaboration — Supervisor orchestrates parallel specialist
  fan-out (Sales/Knowledge/FAQ) + synthesis + verification loop on every
  customer message.
- ✔ Autonomous AI — AI Workforce agents plan and execute multi-step goals
  via real LLM tool-calling (Goal → Plan → Subtasks → Tool Selection →
  Execution → Verification → Report).
- ✔ Long-Term Memory — per-customer profile + cumulative conversation
  summary persisted across sessions (`memory_agent.py`).
- ✔ Knowledge Engine — auto-ingests PDF/DOCX/CSV/URL, auto-drafts
  FAQ/SOP, quality-scores them, human-approval publish gate.
- ✔ AI Workflow Automation — visual trigger→condition→agent→action graph
  builder with branching and retries (`workflow_engine.py`).
- ✔ Human Approval gate — any AI action that could reach a real customer
  (outbound messaging) is architecturally forced through a
  pending-approval queue before it executes.
- ✔ Prompt Routing — intent classification chooses Standard vs Pro
  (multi-lens) reasoning mode per message.
- ✔ Reasoning / Verification — devil's-advocate critique + bounded
  rewrite loop before low-confidence answers reach a customer.
- ✔ Escalation — automatic human handoff when confidence is too low.
- ✔ 25 wired agent classes: Supervisor, CS, Sales, Knowledge/FAQ, Memory,
  Escalation, Analytics, Trainer, Self-Learning, General AI, Research,
  Devil's Advocate, First-Principle, Planner, Reasoning, Verification,
  Identity, plus the 7 AI Workforce domain agents below.

## AI Workforce (internal business operations)
- ✔ Finance Agent — invoices, payments, expenses, revenue/profit/cashflow
  forecasting.
- ✔ Marketing Agent — content generation, campaign calendar, analytics.
- ✔ HR Agent — CV screening/scoring, interview question generation,
  performance evaluation, training recommendations.
- ✔ Operations Agent — SLA/health monitoring, alerts, periodic reports.
- ✔ Security Agent — API abuse detection, tenant isolation checks, risk
  scoring.
- ✔ Executive Agent — cross-domain synthesis, company health score,
  executive briefs.
- ✔ Workforce Orchestrator — cross-agent task tracking, conflict
  detection, overdue escalation.
- ✔ Self-Learning Company — distills real sales/complaint/success
  patterns from conversation history into human-approved organizational
  knowledge.

## Tool Framework (real LLM function-calling)
- ✔ `database_query` (allowlisted tables, parameterized — no SQL
  injection surface), `web_search`, `browser_open`/`browser_extract`,
  `financial_data`, `news_search`, `document_generator` (PDF/DOCX/XLSX/
  PPTX), `email_reader` (Gmail), `channel_messaging` (gated by human
  approval).

## Omnichannel
- ✔ WhatsApp, Instagram, Facebook, Telegram, and web widget — real
  per-channel connectors (`bn_platform/channels/connectors.py`), one
  unified inbox, one Human Handoff queue.

## Enterprise SaaS
- ✔ Multi-tenant Organizations/Workspaces — every table scoped by
  `org_id`.
- ✔ RBAC — owner/admin/manager/viewer/agent with a real permission
  matrix (read/write/approve tiers per domain), not a single admin flag.
- ✔ Billing & Subscriptions — 5 real plans (Free/Starter/Pro/Business/
  Enterprise), Midtrans + Xendit payment integration, usage metering.
- ✔ API Keys — generation, rotation, usage tracking.
- ✔ Usage & Cost Intelligence — per-tenant AI cost tracking down to the
  token.
- ✔ Settings — integrations (Gmail OAuth, channel connections), team
  management, security controls.

## Security & Production Readiness
- ✔ JWT auth with optional session tracking (`sid` claim), revocable
  sessions.
- ✔ Suspicious-login detection (new-IP heuristic).
- ✔ Audit log across every sensitive action.
- ✔ Rate limiting on every AI-cost-incurring endpoint.
- ✔ CORS locked to explicit production domains (not wildcard).
- ✔ 911 automated backend tests.

## Frontend
- ✔ Single dark-themed dashboard SPA (no build step), responsive down to
  mobile, loading/empty/error/success states and toasts used consistently
  across all 35 pages.
- ✔ Premium public landing page + Investor Demo mode (live LLM-backed
  business analysis simulation).

## Not yet built (honest gaps — see Roadmap)
- 🔜 Voice channel (phone/IVR).
- 🔜 Native calendar integration (Google/Outlook) — confirmed not built,
  not claimed anywhere as built.
- 🔜 Light-mode theme toggle (dark-only by design today).
- 🔜 Public agent marketplace for third-party-built specialist agents.
