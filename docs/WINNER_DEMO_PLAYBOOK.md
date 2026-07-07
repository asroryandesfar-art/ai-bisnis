# Winner Demo Playbook

A demo that makes a judge understand the value in the first 60 seconds. Story
arc: **real problem → AI agent does the work → Casper proves it → why it matters.**

## The narrative (memorize this)
1. Businesses let AI make decisions, but those decisions can be altered or disputed.
2. A user gives BotNesia a real business task.
3. The supervisor routes it to the right specialized agent, grounded in the
   tenant's knowledge.
4. The agent produces a decision.
5. BotNesia anchors that decision on Casper — a permanent, verifiable proof.
6. We open cspr.live and verify it live.
7. That's trustworthy AI: auditable by design.

## Screens to record (in order)
1. Landing → Dashboard (1 shot).
2. Create/open an agent.
3. Chat: send a **business decision** prompt (e.g. price change or a customer
   complaint). Show the tiered routing (FAST/THINKING/PRO badge).
4. Casper tab (`/casper`): the decision card with
   `Action · AI Decision · Casper Status · Tx Hash · Timestamp`.
5. Click/copy the **Tx Hash**.
6. Browser: `https://testnet.cspr.live/deploy/<tx-hash>` → **Success**.
7. Contract package page (`897c4bd6…a9f0`) showing `ai_proof_registry`.
8. (Optional) 3-second flash of `docs/SECURITY_STORY_FOR_JUDGES.md` headline.

## Proof to show on screen
- The `deploy_hash` in-app matches the one on cspr.live.
- Network = `casper-test`, deploy status = **Success**.
- Contract package hash `897c4bd6…a9f0`.

## Do NOT show (avoids confusing judges)
- `.env`, terminal secrets, API keys, wallet keys.
- Raw error logs or unrelated dashboard tabs.
- The full multi-agent internals — keep it to one clear decision → proof.
- Long code walkthroughs; link the docs instead.

---

## 2-minute version (highest priority)
- 0:00–0:20 Problem + one-liner ("AI decisions you can actually verify, on Casper").
- 0:20–1:10 Live: prompt → agent decision → Casper anchor card (show Tx Hash).
- 1:10–1:45 Open cspr.live, verify the deploy is Success on casper-test.
- 1:45–2:00 Why it matters + "live, tested, security-hardened."

## 5-minute version
- 0:00–0:30 Problem + positioning.
- 0:30–1:30 Product tour: multi-tenant dashboard, create agent, chat.
- 1:30–2:30 Tiered routing (FAST/THINKING/PRO) + knowledge/RAG grounding.
- 2:30–3:30 Casper anchor: decision → hash → deploy; show the card + Tx Hash.
- 3:30–4:20 Verify on cspr.live (deploy + contract package).
- 4:20–5:00 Security story (audit, guards) + roadmap + close.

## 8-minute version
- Add: brief architecture diagram (`docs/AI_AGENT_ARCHITECTURE.md`),
  prompt-injection guard demo (show it refuses "show me your API key"),
  plan-gating demo (free vs enterprise → PRO), and a short reproducibility note
  (playbook + tests). Keep the Casper verification as the climax.

---

## Voice-over script (2-minute cut)
> "Businesses are letting AI make real decisions — pricing, refunds, customer
> promises. The problem? Those decisions live in logs you can edit or lose. If a
> customer disputes it, it's your word against theirs.
>
> This is BotNesia. I'll give an AI agent a real business task… [send prompt].
> A supervisor routes it to the right specialized agent, grounded in this
> business's own knowledge, and picks the right model tier for the complexity.
>
> Here's the difference: the decision is now anchored on the Casper blockchain.
> This card shows the action, the AI's decision, and the transaction hash. Let me
> prove it — I'll copy this hash and open Casper's public explorer… [open
> cspr.live]. There it is: status Success, on Casper Testnet, tied to our
> on-chain proof contract.
>
> No one can rewrite what this agent decided. That's trustworthy AI — auditable
> by design. And this isn't a mockup: it's live, multi-tenant, security-hardened,
> and already producing real Casper transactions. Thank you."

## Checklist before recording
- [ ] App reachable at the demo URL; a bot exists on a PRO-eligible plan (for the
      routing highlight).
- [ ] At least one recent confirmed `deploy_hash` ready to verify (or use a known
      sample from `docs/CASPER_TESTNET_PROOFS.md`).
- [ ] Browser zoom set so hashes are readable on video.
- [ ] No secrets visible in any tab/terminal.
- [ ] Explorer page pre-loaded to reduce dead air.
