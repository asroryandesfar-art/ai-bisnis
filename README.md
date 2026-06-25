# BotNesia — Enterprise Multi-Agent AI Platform

**BotNesia is a production-deployed, multi-tenant Business AI Operating
System.** A Supervisor agent orchestrates a team of 25+ specialist agents —
Customer Service, Sales, Knowledge, Finance, Marketing, HR, Operations,
Security, Executive, Workforce Orchestrator, Self-Learning, and more — that
collaborate in real time to run the customer-facing chat pipeline and the
internal AI Workforce that operates the business itself.

Live at **[botnesia.uk](https://botnesia.uk)**. Built and run by one founder,
serving real tenants today — not a demo shell.

> Submitted to **Casper Agentic Buildathon 2026**.

---

## Why this is an "Enterprise Multi-Agent AI Platform," concretely

| Requirement | Where it lives |
|---|---|
| **Autonomous AI Agents** | 25+ agent classes in `supervisor.py` (`SupervisorAgent.__init__`), each a self-contained `BaseAgent` subclass with its own prompt, tools, and `safe_run()` graceful-degradation contract |
| **Multi-Agent Collaboration** | `supervisor.py` `_process()` — intent routing → parallel specialist fan-out (`asyncio.gather`) → CS Agent synthesis → verification/critique loop → escalation gate, all in one real pipeline (not staged for demo) |
| **Long-Term Memory** | `memory_agent.py` — per-customer profile + cumulative `ConversationSummary` persisted across sessions, injected into every reply for continuity |
| **Knowledge Engine** | `knowledge_agent.py` + Auto Knowledge Builder (`knowledge_builder_agent.py`) — ingest PDF/DOCX/CSV/URL, auto-generate FAQ/SOP, human-approval publish gate into the live knowledge base |
| **Workflow Automation** | `workflow_engine.py` — visual, n8n-style trigger→condition→agent→action graph builder with retries and branching, plus a real Task Engine (`task_engine.py`): Goal → Plan → Subtasks → Tool Selection → Execution → Verification → Report |
| **Business AI Operating System** | 7 "AI Workforce" employees (Finance/Marketing/HR/Operations/Security/Executive/Workforce-Orchestrator) running the business's own back office, with a Self-Learning engine distilling real conversation/sales/complaint patterns into approved organizational knowledge |
| **Production Ready** | Real multi-tenant RBAC, JWT auth, audit logging, rate limiting, billing/subscriptions, 911 automated tests, live on a public domain behind Cloudflare with daily DB backups |

## Architecture at a glance

```
Customer ──HTTPS──> Cloudflare Tunnel ──> FastAPI (main.py)
                                              │
                                  ┌───────────┼────────────┐
                                  ▼           ▼            ▼
                          SupervisorAgent  RBAC/Billing  AI Workforce
                          (chat pipeline)  (bn_platform) (Finance/Mktg/HR/
                                  │                        Ops/Security/Exec)
                       ┌──────────┼──────────┐
                       ▼          ▼          ▼
                  CS/Sales/   Memory/    Verification/
                  Knowledge   Escalation Reasoning/Critique
                       │
                       ▼
                PostgreSQL 16 (single source of truth, RLS-style org_id
                scoping on every table)
```

Full diagrams and per-subsystem detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Feature map

- **AI Agents**: Supervisor, CS, Sales, Knowledge/FAQ, Memory, Escalation,
  Analytics, Trainer, Self-Learning, General AI, Research, Devil's Advocate,
  First-Principle, Planner/Reasoning/Verification, Identity — plus the 7
  AI Workforce domain agents above. Prompt routing between Standard and Pro
  (multi-lens reasoning) modes via `intent_classifier.py`.
- **Tool Framework**: real LLM function-calling (Groq, OpenAI-compatible
  `tools=`) — `database_query`, `web_search`, `browser_open/extract`,
  `financial_data`, `news_search`, `document_generator`, `email_reader`
  (Gmail), `channel_messaging` (WhatsApp/Telegram/Instagram/Facebook, gated
  behind a mandatory human-approval queue before anything is sent).
- **SaaS platform**: multi-tenant Organizations/Workspaces, Team & RBAC
  (owner/admin/manager/viewer/agent), Billing & Subscriptions
  (Midtrans/Xendit), API keys, Usage/Cost Intelligence, Security Dashboard
  (sessions, audit log, suspicious-login detection).
- **Omnichannel**: WhatsApp, Instagram, Facebook, Telegram, web widget — one
  unified inbox, one Human Handoff queue.
- **Frontend**: a single dark-themed dashboard SPA (`frontend/`, vanilla JS,
  no framework/build step) covering chat, conversations, analytics,
  knowledge builder, workflow builder, billing, security, and the full AI
  Workforce + Agent Center — responsive down to mobile.

## Quickstart

```bash
git clone <this-repo>
cd "ai bisnis"
pip install -r requirements.txt
cp .env.example .env        # fill in SECRET_KEY, GROQ_API_KEY at minimum
./setup_db.sh                # bootstraps a local PostgreSQL 16 + pgvector
./start_postgres.sh &        # or: systemctl --user start botnesia-postgres.service
./migrate_database.sh
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` for the landing page, `http://localhost:8000/dashboard`
for the authenticated SPA. The customer-facing chat endpoint is public:
`POST /chat/{bot_id}` (no auth — validated by `bot_id`).

Production runs the exact same code via systemd (`start_all.sh`) behind a
Cloudflare named tunnel — see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Tests

```bash
python3 -m pytest -q   # 911 tests, full backend coverage
```

## Documentation

| Doc | Covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System layers, AI Workforce phase-by-phase map, security patterns |
| [`docs/API.md`](docs/API.md) | Every REST endpoint, grouped by router |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Schema, multi-tenant isolation strategy |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Production topology, systemd services, migration runbook |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Auth/JWT/RBAC, rate limiting, audit logging |
| [`docs/COST_INTELLIGENCE.md`](docs/COST_INTELLIGENCE.md) | Per-tenant AI cost tracking |

## Tech stack

FastAPI + asyncpg (PostgreSQL 16 + pgvector) · Groq (Llama 4) for LLM
inference · vanilla JS SPA frontend (no build step) · Cloudflare Tunnel for
HTTPS · Midtrans/Xendit for billing.
