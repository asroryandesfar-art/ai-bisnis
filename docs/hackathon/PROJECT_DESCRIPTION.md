# BotNesia — Project Description

## One-line
BotNesia is an Enterprise Multi-Agent AI Platform — an AI Workforce
Operating System where a Supervisor agent orchestrates 25+ specialist AI
agents that collaborate to run a business's customer operations and its
internal back office, live in production at [botnesia.uk](https://botnesia.uk).

## The problem
Businesses adopting AI today get a single-purpose chatbot that forgets
context the moment a session ends, or a pile of disconnected point tools
someone has to stitch together manually. Neither approach gives a company
an actual *workforce* — agents that remember customers long-term,
collaborate across departments on a single request, and can be trusted to
take real action without becoming a liability.

## What BotNesia actually does
1. **Customer-facing pipeline**: every chat message goes through intent
   classification + prompt routing, a parallel fan-out to relevant
   specialist agents (Sales, Knowledge, FAQ), synthesis into one coherent
   answer, and a verification/critique pass before it ever reaches the
   customer — with automatic escalation to a human when confidence is low.
2. **Long-term memory**: a per-customer profile and running conversation
   summary persist across sessions, so follow-up questions days later
   still have context.
3. **Self-building Knowledge Engine**: upload a document or URL and the
   platform chunks, classifies, drafts FAQs/SOPs, and quality-scores them
   — a human approves before anything goes live.
4. **AI Workforce**: 7 domain agents (Finance, Marketing, HR, Operations,
   Security, Executive, Workforce Orchestrator) that run a tenant's own
   back office — generating invoices/reports, screening candidates,
   monitoring SLAs — reachable via authenticated REST and a dashboard "Run
   Task" form, never mixed into the customer chat pipeline (a deliberate
   security boundary).
5. **Real tool-calling with a safety net**: AI Workforce agents execute
   free-form goals using genuine LLM function-calling against real tools
   (database queries, document generation, web search, email reading).
   The one tool capable of reaching a real customer directly — outbound
   messaging — is architecturally forced through a human-approval queue
   before anything sends.
6. **Enterprise SaaS underneath**: multi-tenant data isolation, 5-tier
   RBAC, billing/subscriptions across 5 plans, audit logging, session
   security, and per-tenant AI cost tracking.

## Who it's for
SMBs and growing enterprises in Indonesia (and beyond) that want an AI
team handling customer support, sales conversations, and internal
operations — without hiring a large ops team or duct-taping together five
separate SaaS tools.

## What makes it different
- **It's actually multi-agent**, not a single LLM call with a different
  system prompt per "agent" — specialists run concurrently and a separate
  synthesis step reconciles their outputs.
- **Autonomy with a brake pedal**: every write-action tool that could
  affect a real customer is gated by a human-approval queue at the
  execution layer, not just a UI convention.
- **It's running in production today**, serving real multi-tenant
  customers, not a hackathon-only build — 911 automated tests, live
  security/billing/RBAC stack, and every dashboard page live-verified
  error-free before this submission.

## Casper Blockchain Integration

BotNesia anchors AI agent session hashes to the **Casper Testnet** blockchain,
making every AI decision permanently verifiable on-chain.

**How it works:**
1. After an AI session, the dashboard shows an **"Anchor to Casper"** button.
2. Clicking it calls `POST /api/casper/anchor` — the backend SHA-256 hashes the
   session data (org_id + session_id + summary), encodes the first 8 bytes of
   the hash as a `correlation_id`, and builds a signed Casper transfer deploy.
3. The deploy is submitted to the official **Casper 2.0 Testnet** via
   `https://node.testnet.casper.network/rpc`.
4. The response **deploy_hash** is displayed in the UI with a direct link to
   `testnet.cspr.live` so anyone can independently verify the anchor.

**Why this matters:** Each AI session's output is cryptographically pinned on a
public immutable ledger. No one — not even BotNesia — can retroactively alter
what an agent decided. This is foundational for auditable autonomous AI.

**Files added:** `casper_anchor.py` (backend), `frontend/casper_widget.js` (UI button),
`POST /api/casper/anchor` endpoint in `main.py`.

**Testnet account:** `012c833458db430f3c7d1cd629dc5206fd2979e7f750c97c75d799948436807783`
Verify deploys at: `https://testnet.cspr.live`

## Tech stack
FastAPI + asyncpg (PostgreSQL 16 + pgvector) on the backend, Groq
(Llama 4 Scout) for LLM inference, a vanilla-JS SPA frontend (no build
step), Cloudflare Tunnel for HTTPS, Midtrans/Xendit for billing,
**Casper Testnet** for immutable AI session anchoring.

## Links
- Live product: [botnesia.uk](https://botnesia.uk)
- Source: [github.com/asroryandesfar-art/ai-bisnis](https://github.com/asroryandesfar-art/ai-bisnis)
- Architecture deep-dive: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
