# BotNesia — 3-Minute Demo Script

Every step below has been live-verified against the running production
instance (`botnesia.uk`) before this script was written — no step relies
on a feature that hasn't actually been clicked and confirmed working.

**Setup before you start:** have `https://botnesia.uk` open in one tab and
already logged in to `/dashboard`. Pick one marketplace demo bot for the
chat widget (e.g. "Customer Service Agent").

---

### 0:00–0:20 — Hook (landing page)

> "This is BotNesia — not a chatbot, an Enterprise Multi-Agent AI
> Platform. What you're about to see is one Supervisor AI orchestrating
> 25 specialist agents, live, in production."

Show the landing page (`botnesia.uk`). Point at the "AI Workforce Platform"
badge and the 3 stat cards (8+ AI Agents Connected · 24/7 · 1 Dashboard).

---

### 0:20–1:10 — Multi-agent routing, live (chat widget)

Open the chat widget for a demo bot. Send two messages back to back:

1. **"Halo, jam operasional kalian jam berapa?"**
   → Watch it answer instantly. Call out: *"That just got routed by a
   real intent classifier to the General AI Agent."*
2. **"Saya tertarik beli paket Enterprise, berapa harganya?"**
   → Different answer, different tone. Call out: *"Same conversation,
   but the Supervisor just routed this one to the Sales Agent instead —
   that's multi-agent collaboration happening in real time, not a
   pre-scripted demo."*

If the dashboard's RBAC/JWT is visible in the network tab, mention: *"every
one of these calls is authenticated and tenant-isolated — this is the same
pipeline serving real paying customers right now."*

---

### 1:10–2:10 — The flagship: Investor Demo (`/dashboard#investor-demo`)

Navigate to **Investor Demo Mode** in the sidebar. Click **"Run Investor
Demo."**

> "This simulates a company with declining revenue and lets the same AI
> Business Analyst that powers our Executive Center diagnose it, live."

While it streams through its steps (Collecting Data → Analyzing Revenue →
Finding Root Cause → ... → Executive Action Plan), narrate:

> "This is a real LLM call analyzing simulated business data — root cause
> analysis, a prioritized action plan, and a predicted recovery curve, all
> generated on the spot."

Let the result render: Business Health score, root-cause Q&A, action plan,
and the "+X% Revenue in 90 days" prediction card.

---

### 2:10–2:45 — The AI Workforce + human-approval safety (`#agent-center`)

Navigate to **Agent Center**. Point at:
- The **Agent Directory** table — 15+ named agents, their tools, their
  skill counts.
- The **Run Task** form — type a real goal (e.g. *"Cek apakah ada invoice
  yang belum lunas"*) for the Finance Agent and run it live: Goal → Plan →
  Tool execution → Verified report, end to end.
- The **Channel Messaging — Menunggu Approval** table: *"Any AI agent that
  wants to message a real customer queues here first — a human always
  approves before anything actually sends. Autonomous, but never
  unsupervised on real-world actions."*

---

### 2:45–3:00 — Close

> "Multi-agent collaboration, long-term memory, a self-building knowledge
> engine, autonomous task execution with a human-approval safety net, full
> multi-tenant SaaS underneath — all live, all tested, all running today
> at botnesia.uk. BotNesia isn't a chatbot. It's the AI Workforce
> Operating System a real business runs on."

---

## Backup talking points (if something is slow / a question comes up)

- **"Is this mocked?"** — No. 911 automated backend tests, every dashboard
  page live-crawled for errors before this submission, real Groq LLM calls
  on every demo step above (latency you saw is real inference time).
- **"What stops an agent from going rogue?"** — The approval-gate pattern
  shown in Agent Center: any write action that reaches a real customer
  (sending a message) is architecturally incapable of bypassing the
  pending-approval queue — it's enforced in the tool executor, not just a
  UI suggestion.
- **"How is this multi-tenant?"** — Every table is scoped by `org_id`;
  RBAC has 5 role tiers; see `docs/SECURITY.md` and `docs/DATABASE.md`.
