# BotNesia — Global Positioning

**Positioning:** BotNesia is **trusted AI-agent infrastructure for business** —
a multi-agent platform that runs real business operations and **anchors every
important AI decision on Casper** as an immutable, independently verifiable
proof. It is a *decentralized agent proof layer*, not an AI chatbot.

Chosen because the repo backs it: a live multi-tenant SaaS with 20+ specialized
agents, a supervisor router, tenant knowledge/RAG, tiered DeepSeek routing, and
a deployed Casper `ai_proof_registry` contract with confirmed testnet deploys.

## One-liner
> Trusted AI agents for business — every AI decision anchored on Casper as
> verifiable, tamper-proof on-chain proof.

## 3-sentence pitch
BotNesia is a multi-agent AI platform that automates customer service, sales,
finance, HR, and operations for businesses. Unlike ordinary AI tools, every
consequential agent decision is anchored on the Casper blockchain, so it can be
audited and independently verified — no one can rewrite what an agent decided.
It is live, multi-tenant, security-hardened, and already producing real
confirmed Casper Testnet transactions.

## 30-second pitch
Businesses are handing decisions to AI, but AI decisions are a black box:
untraceable and easy to dispute or alter after the fact. BotNesia is an AI-agent
operating system for business — a supervisor routes each task to the right
specialized agent (CS, sales, finance, HR, ops), grounded in the tenant's own
knowledge base, with strict multi-tenant isolation and security guards. The
differentiator: every important decision is hashed and anchored on Casper as an
immutable proof, verifiable on-chain by anyone. Trust becomes cryptographic, not
"trust me." It's live today with real testnet proofs.

## 90-second pitch
AI is now making real business calls — pricing changes, refunds, hiring signals,
customer commitments. But those decisions live in ephemeral logs that can be
edited, lost, or disputed. For regulated or high-trust businesses, that is a
dealbreaker.

BotNesia solves this with two layers. First, an **AI-agent operating system**: a
supervisor agent classifies each request and routes it to one of 20+ specialized
agents, grounded in the tenant's private knowledge base (RAG), with memory,
tool-calling, and a tiered DeepSeek model router (fast / reasoning / pro) gated
by the customer's plan. Second, a **Casper proof layer**: when an agent makes a
consequential decision, BotNesia hashes it and anchors it on the Casper Testnet
via the deployed `ai_proof_registry` contract. Anyone can verify the proof on
cspr.live — the decision, its timestamp, and its integrity are permanent.

It's not a demo. It's a live, multi-tenant SaaS with billing, omnichannel
(WhatsApp/Telegram/web), ~1126 tests, a documented security audit with
Critical/High issues fixed, and real confirmed Casper transactions. Casper turns
AI from "black box" into "auditable by design."

## Technical pitch (for developer judges)
- **Backend:** FastAPI + asyncpg (Postgres), strict multi-tenant isolation
  (`org_id` on every query), RBAC with server-side plan gating, IP-based rate
  limiting, signed media URLs, security headers, secret-strength startup guard.
- **Agents:** `SupervisorAgent` routes to specialized agents (cs, sales, finance,
  hr, operations, research, security, executive, planner, memory, …) via intent
  classification; tools registry (knowledge search, memory, analytics, channel
  messaging); DeepSeek 3-tier router (`deepseek_brain.py`) with plan gating,
  prompt-injection guard, output redaction, and PRO→THINKING→FAST fallback.
- **Casper:** `casper_anchor.py` (pycspr) deploys a keccak/session hash of each
  decision to the `ai_proof_registry` contract; results stored in `casper_proofs`
  with `deploy_hash`, `tx_status`, `explorer_url`. Rust contract source in
  `casper/contract/`.
- **Proofs:** contract package `897c4bd6…a9f0`; confirmed testnet deploys
  `fbb4b7e7…7b4e`, `cc2739a7…d04b` (verifiable on cspr.live).

## Business pitch (for non-technical judges)
Imagine an AI employee that handles your customers, sales, and back-office — and
keeps a permanent, tamper-proof receipt of every important decision it makes,
stored on a public blockchain. If a customer disputes what was promised, or an
auditor asks "who decided this and when," the answer is provable, not
he-said-she-said. That's BotNesia: AI that businesses can actually trust because
its decisions are anchored on Casper.

## Why Casper matters here (not blockchain-for-its-own-sake)
- **Immutability with a purpose:** AI decisions become non-repudiable audit
  records. This is a real need for regulated/high-trust commerce, not a token gimmick.
- **Low-cost, deterministic anchoring:** hashing + on-chain proof is cheap and
  scales per-decision.
- **Independent verification:** any third party (customer, auditor, judge)
  verifies on cspr.live without trusting BotNesia's servers.

## Why this is not "just another AI wrapper"
- It is a **multi-agent operating system**, not a single prompt: routing, memory,
  tools, RAG, guardrails, plan-gated model tiers.
- It is **multi-tenant and production-grade**: billing, RBAC, channels, security
  audit — the hard parts most wrappers skip.
- The **Casper proof layer** is a genuinely differentiated capability: verifiable
  AI accountability, which pure LLM wrappers cannot offer.

## Why this can scale globally
- SMBs everywhere need trustworthy AI automation; the proof layer is a natural
  fit for regulated markets and cross-border commerce.
- Architecture is horizontally scalable (stateless API + Postgres + per-tenant
  isolation) and channel-agnostic (WhatsApp/Telegram/web/IG).
- The on-chain proof pattern generalizes: any high-stakes AI action in any
  vertical can be anchored the same way.
