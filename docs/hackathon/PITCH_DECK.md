# BotNesia — Pitch Deck
### Casper Agentic Buildathon 2026

*Markdown slide deck — one `##` heading per slide. Paste into your slide tool of choice, or present directly from this file.*

---

## 1. BotNesia is not a chatbot.

**It's an Enterprise Multi-Agent AI Platform** — a team of 25+ autonomous,
collaborating AI agents that run a business's customer operations *and*
its internal back office, side by side.

Live today at **botnesia.uk**. Multi-tenant. Production. Real customers.

---

## 2. The problem

Businesses adopting AI today get one of two things:
1. A single chatbot that answers FAQs and nothing else, or
2. A pile of disconnected point tools (one for support, one for CRM, one
   for analytics) that someone still has to glue together by hand.

Neither is a *workforce*. Neither remembers a customer across sessions,
collaborates across departments, or runs the business itself.

---

## 3. The solution: an AI Workforce, not an AI feature

BotNesia gives a company a Supervisor agent that orchestrates specialists —
Customer Service, Sales, Knowledge, Finance, Marketing, HR, Operations,
Security, Executive — that **collaborate on every request**, remember every
customer long-term, and run the company's own AI Workforce (invoicing,
campaign generation, candidate screening, ops monitoring) behind the scenes.

---

## 4. How it actually works (live pipeline, not a demo script)

```
Customer message
   → Intent classification + Prompt Routing (Standard vs Pro reasoning)
   → Parallel specialist fan-out (Sales + Knowledge + Memory, concurrently)
   → CS Agent synthesizes one answer from all specialist outputs
   → Verification / Devil's-Advocate critique loop
   → Escalation gate (hands off to a human when confidence is low)
```

Every step above is a real, tested code path — `supervisor.py`'s
`_process()` — not a mocked demo flow.

---

## 5. Long-term memory, not session memory

Most chatbots forget you the moment the tab closes. BotNesia's Memory Agent
persists a cumulative profile *and* a running conversation summary per
customer, so "Kalau yang Pro gimana?" three days later still has context.

---

## 6. The Knowledge Engine builds itself

Upload a PDF, a CSV, or just a URL. BotNesia chunks it, classifies it,
auto-drafts FAQs and SOPs, scores their quality — and a human approves
before anything goes live. No manual FAQ-writing required.

---

## 7. Autonomous, but never unsupervised on real-world actions

Every AI Workforce agent can *plan and execute* multi-step goals using real
tools (database queries, document generation, email reading, web search).
The one tool that can touch a real customer — sending a WhatsApp/Telegram
message — **always stops at a human-approval queue first.** Autonomy with
a brake pedal, by design.

---

## 8. Built for the enterprise, not just demoed for one

- **Multi-tenant** from day one — every table scoped by `org_id`, isolation
  enforced at the query layer.
- **RBAC**: owner / admin / manager / viewer / agent, with a real
  permission matrix, not a boolean "is_admin" flag.
- **Billing**: 5 real plans (Free → Enterprise), Midtrans/Xendit
  integration, usage metering, per-tenant AI cost tracking.
- **Security**: session management, suspicious-login detection, audit log,
  API key rotation — all live, all tested.

---

## 9. The numbers right now

- **911/911** automated backend tests passing.
- **25** wired, working agent classes (not files sitting unused).
- **2,464** tenants on the platform's own metrics dashboard.
- **35** dashboard pages, every one live-crawled and verified error-free.
- **5** customer channels: WhatsApp, Instagram, Facebook, Telegram, web
  widget — one unified inbox.

---

## 10. Why this matters for Casper Agentic Buildathon

This isn't a weekend build pretending to be a platform. It's a platform
that happens to be entering a buildathon. Multi-agent collaboration,
autonomous execution with human-in-the-loop safety, long-term memory, and
a knowledge engine aren't slide-ware here — they're the same code path
serving real tenants on botnesia.uk right now.

---

## 11. What's next

See [`ROADMAP.md`](ROADMAP.md) — voice channel, deeper calendar/CRM tool
integrations, agent marketplace for third-party specialist agents, and
expanding the Task Engine into fully autonomous multi-day workflows.

---

## 12. Ask

We're looking for: pilot enterprise customers, technical feedback from the
judging panel, and (if relevant to this track) investment to grow the AI
Workforce beyond a single founder's nights and weekends into a team.

**Try it live:** [botnesia.uk](https://botnesia.uk) · **Code:**
[github.com/asroryandesfar-art/ai-bisnis](https://github.com/asroryandesfar-art/ai-bisnis)
