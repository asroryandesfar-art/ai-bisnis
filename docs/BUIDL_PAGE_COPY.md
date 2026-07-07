# DoraHacks / BUIDL Page — Copy-Paste Content

Paste these blocks into the BUIDL page. All facts are verifiable in the repo or
on Casper Testnet. Replace `TODO` items with your final links.

---

## Project title
**BotNesia — Trusted AI Agents for Business, Anchored on Casper**

## Short description (one line)
Multi-agent AI platform that runs real business operations and anchors every
important AI decision on Casper as an immutable, verifiable proof.

## Full description
BotNesia is trusted AI-agent infrastructure for business. A supervisor agent
routes each request to one of 20+ specialized agents (customer service, sales,
finance, HR, operations, research, executive), grounded in the tenant's own
knowledge base, with memory, tool-calling, and a tiered DeepSeek model router
(fast / reasoning / pro) gated by the customer's plan.

What makes it different: when an agent makes a consequential decision, BotNesia
hashes it and anchors it on the **Casper Testnet** via a deployed
`ai_proof_registry` smart contract. The decision, its integrity, and its
timestamp become permanent and independently verifiable on cspr.live — turning AI
accountability from "trust me" into cryptographic proof.

It is a live, multi-tenant SaaS with billing and omnichannel messaging
(WhatsApp/Telegram/web), ~1126 automated tests, a documented security audit with
Critical/High issues fixed, and real confirmed Casper Testnet transactions.

## Problem statement
Businesses increasingly let AI make real decisions — pricing, refunds, customer
commitments, hiring signals. But those decisions live in editable logs: they can
be altered, lost, or disputed after the fact. For regulated or high-trust
commerce, unverifiable AI decisions are a dealbreaker.

## Solution
1. An **AI-agent operating system** that actually runs the business workflow
   (routing, RAG, memory, tools, guardrails, plan-gated model tiers).
2. A **Casper proof layer** that anchors important decisions on-chain, so anyone
   can verify what an agent decided and when — without trusting BotNesia's servers.

## Key innovation
Verifiable AI accountability: every high-stakes agent decision produces an
on-chain proof on Casper. This is a capability pure LLM wrappers cannot offer.

## How it uses Casper
- Smart contract `ai_proof_registry` deployed on Casper Testnet.
- `casper_anchor.py` (pycspr) submits a deploy that stores a keccak/session hash
  of each decision via the contract's `store_proof` entry point.
- Results (`deploy_hash`, status, explorer URL) are stored and shown in-app, and
  are verifiable on https://testnet.cspr.live.

## AI agent capabilities
- 20+ specialized agents + supervisor routing.
- Tenant knowledge base / RAG (org-isolated), conversation memory, tool-calling.
- DeepSeek 3-tier router (FAST / THINKING-R1 / PRO) with backend plan gating,
  prompt-injection guard, output redaction, and safe fallback.

## Testnet proof
```
Network: Casper Testnet (casper-test)
Contract package hash: 897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
Contract hash:         15009cd4a6489c904b699c0a1f292e7e5557e823e54c236539c9ce9973ee2323
Contract explorer:     https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
Sample tx 1 (confirmed): fbb4b7e766c0275980074d070d446d8e64703c2c2eb81be84637dfa531aa7b4e
Sample tx 2 (confirmed): cc2739a746eb1916ffaa1b4ce150266039b09cedc566d28cbf3090c53df3d04b
```
Verify a deploy: `https://testnet.cspr.live/deploy/<tx-hash>`

## Demo instructions
See the step-by-step tester playbook: `docs/CASPER_FINAL_SUBMISSION_PLAYBOOK.md`.
Demo video: **TODO: add demo video link**.

## Technical architecture
FastAPI + Postgres (asyncpg), multi-tenant (`org_id`), RBAC + plan gating,
supervisor + 20+ agents, DeepSeek 3-tier router, tenant RAG, pycspr Casper
anchoring, web dashboard + Expo mobile app. Details:
`docs/AI_AGENT_ARCHITECTURE.md`.

## Security notes
Security-hardened MVP: white-box audit performed; Critical/High issues fixed
(secret guard, RBAC, billing, rate-limit, command guard); CodeQL + Dependabot
enabled; no secrets committed. Details: `docs/SECURITY_STORY_FOR_JUDGES.md`.
We do not claim "100% secure" — we document defensive controls and a hardening
checklist.

## Team / builder notes
Solo/lean builder. Contact: asroryandesfar@gmail.com.
Repository: https://github.com/asroryandesfar-art/ai-bisnis

## Future roadmap
- Mainnet anchoring + batched proofs for cost efficiency.
- Verifiable proof widget customers can embed.
- Per-decision on-chain audit trails for regulated verticals.
- Expanded agent marketplace + more channels.

## Why this deserves to win
It is a real, deployed, security-hardened product that uses Casper for a genuine
purpose — verifiable AI accountability — backed by confirmed on-chain
transactions a judge can verify in one click. It solves a real, growing problem
(untrustworthy AI decisions) with a differentiated architecture, not a wrapper.

## Links to fill in (manual)
- Live demo URL: **TODO** (e.g. https://botnesia.uk)
- Demo video: **TODO**
- GitHub: https://github.com/asroryandesfar-art/ai-bisnis
