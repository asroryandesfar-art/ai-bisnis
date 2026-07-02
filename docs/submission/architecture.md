# BotNesia — Architecture (judge-facing summary)

*Full deep-dive: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) ·
[`docs/API.md`](../API.md) · [`docs/DATABASE.md`](../DATABASE.md) ·
[`docs/DEPLOYMENT.md`](../DEPLOYMENT.md) ·
[`docs/hackathon/DIAGRAMS.md`](../hackathon/DIAGRAMS.md).*

## System overview

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
                PostgreSQL 16 (single source of truth, org_id-scoped
                on every table)
```

## Three subsystems worth knowing for judging

**1. Chat pipeline (`supervisor.py`)** — `SupervisorAgent._process()`:
intent classification → parallel specialist fan-out (`asyncio.gather`) →
CS Agent synthesis → verification/critique loop → escalation gate. Real
LLM calls at every step, not a scripted demo path.

**2. Local Computer Agent (`bn_platform/local_agent_router.py` +
`botnesia_local_agent.py`)** — a script a tenant downloads and runs on
their own machine. It opens a WebSocket back to BotNesia; the cloud side
can then ask it to read/list files, run terminal commands, or use a local
browser. Read-only tools (`list_dir`, `read_file`, `search_text`, ...) run
immediately; risky tools (`run_command`, `write_file`, `edit_file`,
`delete_file`) are persisted as `pending_approval` rows in
`local_agent_commands` and only actually execute once a human approves
them from the "Antrian Izin — Local Agent" queue in Agent Center — the
approval is enforced server-side in the same code path that executes the
action, not just a UI gate.

**3. Billing (`bn_platform/billing.py`)** — checkout creates an internal
`invoices` row, then calls Midtrans's Snap API for a hosted payment page.
Payment status is written **only** by `midtrans_webhook` after verifying
Midtrans's SHA-512 signature — the browser redirect back to
`/dashboard/billing` is display-only and always re-checks the real status
from the database (`GET /api/billing/invoices/by-number/{invoice_number}`)
rather than trusting redirect query params. Webhook handling is
idempotent (`SELECT ... FOR UPDATE` + a unique partial index on
`(provider, provider_transaction_id)`), so duplicate Midtrans notification
retries can't double-activate a subscription or double-count a top-up.

## Data isolation

Every table carries `org_id`; every query is scoped by it. RBAC has 5
system roles (owner/admin/manager/viewer/agent) with a real
permission-per-domain matrix (e.g. `billing.read` vs `billing.manage`,
`local_agent.execute` vs `local_agent.read`), not a single admin flag.

## Tech stack

FastAPI + asyncpg (PostgreSQL 16 + pgvector) · DeepSeek + OpenRouter
(multi-provider LLM routing, Groq fallback available) · vanilla JS SPA
frontend (no build step) · Cloudflare Tunnel for HTTPS · Midtrans/Xendit
for billing · Casper Testnet for on-chain AI decision anchoring (see
[`README.md`](../../README.md#casper-agentic-workflow-buildathon-2026)).

## Infrastructure

Runs persistently via `systemd --user` services (`botnesia-api`,
`botnesia-postgres`, `botnesia-tunnel`, `botnesia-backup.timer`) — not an
ephemeral container. PostgreSQL data lives on persistent disk with a daily
automated backup (14-day retention).
