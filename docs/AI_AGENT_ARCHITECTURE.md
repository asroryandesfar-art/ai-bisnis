# BotNesia — AI Agent Architecture

This is not a single-prompt chatbot. It is a multi-agent system with a
supervisor router, tenant-scoped knowledge, tool-calling, guardrails, tiered
model routing, and on-chain proof anchoring.

## High-level flow

```
                        ┌─────────────────────────────────────────────┐
   Customer / Channel   │                 BotNesia API                │
  (Web, WhatsApp,       │                                             │
   Telegram, IG) ─────► │  1. Security Guard                          │
                        │     - prompt-injection block                │
                        │     - rate limit (per IP, per org/plan)     │
                        │                                             │
                        │  2. Tenant resolve (org_id)  ◄─ RBAC/plan   │
                        │                                             │
                        │  3. Supervisor Agent (intent routing)       │
                        │        │                                    │
                        │        ▼                                    │
                        │  4. Specialized Agent  ─────► Tools:        │
                        │     (cs/sales/finance/hr/     - KB search   │
                        │      ops/research/exec/…)     - memory      │
                        │        │                      - analytics   │
                        │        ▼                      - channel msg │
                        │  5. Tenant Knowledge / RAG (org-scoped)     │
                        │        │                                    │
                        │        ▼                                    │
                        │  6. DeepSeek 3-tier router                  │
                        │     FAST ─ THINKING(R1) ─ PRO  (plan-gated) │
                        │        │                                    │
                        │        ▼                                    │
                        │  7. Output Policy Check (secret redaction)  │
                        │        │                                    │
                        │        ▼                                    │
                        │  8. Casper Anchor (important decisions)     │
                        │     hash → ai_proof_registry → deploy_hash  │
                        └────────┬────────────────────────────────────┘
                                 ▼
                     Answer to customer  +  on-chain proof (cspr.live)
```

## The agents

A `SupervisorAgent` classifies each request and routes to a specialized agent.
Agents present in the repo include:

| Agent | Role |
|-------|------|
| `cs_agent` | Customer service / support replies |
| `sales_agent` | Sales, product Q&A, lead handling |
| `faq_agent` / `knowledge_agent` | Answer from tenant knowledge base |
| `finance_agent` | Invoices, expenses, financial reasoning |
| `hr_agent` | Candidates, employees, evaluations |
| `marketing_agent` | Campaigns, content, calendar |
| `operations_agent` | Health scores, ops alerts |
| `research_agent` | Web/lead research |
| `executive_agent` | Cross-agent executive brief |
| `planner_agent` / `reasoning_agent` / `first_principle_agent` / `devil_advocate_agent` | Deep reasoning + self-critique |
| `security_agent` | Risk/security signals |
| `memory_agent` | Conversation memory + user profile |
| `escalation_agent` | Human handoff |
| `verification_agent` | Answer verification / quality |
| `computer_agent` / local agent | Guarded computer/terminal actions |

Routing is deterministic-first (intent classifier + heuristics) with LLM
assistance, so it is cheap, testable, and explainable.

## Model routing (DeepSeek 3-brain)

`deepseek_brain.py` selects the model by complexity **and** plan:

- **FAST** — greetings, FAQ, clear KB answers.
- **THINKING (DeepSeek R1)** — ambiguity, moderate analysis, light complaints.
- **PRO** — heavy complaints, billing disputes, reputation risk, enterprise.

Plan gating is **backend-authoritative** (free=FAST … enterprise=PRO); a client
can never force PRO. Fallback is PRO→THINKING→FAST, then safe human escalation.
See `docs/DEEPSEEK_BOTNESIA_BRAIN.md`.

## Memory & knowledge

- **Memory:** `memory_agent` stores conversation history + a per-end-user
  profile, retrieved per turn for continuity.
- **Knowledge / RAG:** hybrid keyword + embedding search over the tenant's own
  documents/FAQ/SOP (`_retrieve_chunks`), always filtered by `org_id`.

## Tool calling

Tools are declared in a registry (`tool_registry.py`) and executed by
`tool_executor.py`. The database-query tool uses a **server-side allowlist** of
tables/columns and parameterized values scoped to `org_id` — agents cannot run
arbitrary SQL or reach another tenant's data.

## Guardrails

- **Prompt-injection guard**: blocks "ignore previous instructions", "show system
  prompt / API key", "read .env" before any model call.
- **Output policy check**: redacts secret-like patterns and system-prompt leakage
  from model output before it reaches the user.
- **Rate limiting**: per-IP (anti-spoof via CF-Connecting-IP) + per-org/plan.
- **Command guard**: the local/computer agent has a hard denylist, secret-file
  guard, working-dir restriction, and audit log.

## Tenant isolation

Every data path filters by `org_id`/`tenant_id`. RBAC enforces roles server-side;
plan gating and billing limits are checked in the backend, never trusted from the
client. A Postgres Row-Level Security migration is prepared for defense-in-depth
(`migrations/README_RLS_ROLLOUT.md`).

## Output verification & Casper anchoring

For consequential decisions, BotNesia hashes the decision (action, AI decision,
timestamp) and anchors it on Casper Testnet via `casper_anchor.py` →
`ai_proof_registry` contract. The resulting `deploy_hash` is stored in
`casper_proofs` and shown in the dashboard, independently verifiable on
`https://testnet.cspr.live/deploy/<deploy_hash>`. See
`docs/CASPER_TESTNET_PROOFS.md`.
```
decision → keccak/session hash → store_proof(contract) → deploy_hash → cspr.live
```
