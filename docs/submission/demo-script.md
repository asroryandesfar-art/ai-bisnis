# BotNesia — Demo Script (judge-facing summary)

*Full script with narration cues: [`docs/hackathon/DEMO_SCRIPT.md`](../hackathon/DEMO_SCRIPT.md). This is the condensed click-path.*

**What kind of demo is this?** A guided click-through of **real production
features on the founder's own live tenant** — not a synthetic seeded demo
workspace. Investor Demo Mode is the one explicitly-simulated part (a
fabricated business scenario feeding a real LLM call, and it says so on
screen). Everything else — chat routing, Agent Center, the Local Agent, and
billing — is the actual system a paying tenant uses.

## 3-minute core path

1. **0:00–0:20 — Landing page** (`botnesia.uk`): one Supervisor AI
   orchestrating 25 specialist agents, live, in production.
2. **0:20–1:10 — Multi-agent routing, live**: send two different messages
   to a demo bot's chat widget and watch them route to different
   specialist agents (General AI vs. Sales) in real time.
3. **1:10–2:10 — Investor Demo Mode** (`#investor-demo`): a simulated
   declining-revenue scenario, diagnosed live by a real LLM call — root
   cause, action plan, predicted recovery curve.
4. **2:10–2:45 — Agent Center + human-approval safety** (`#agent-center`):
   Agent Directory, live "Run Task" against the Finance Agent, and the
   Channel Messaging approval queue — any outbound customer message stops
   for human approval first.
5. **2:45–3:00 — Close.**

## Extended cut (4–5 minutes)

- **Billing → real Midtrans payment** (`#billing`): Top Up Percakapan →
  smallest package (Rp25.000) → real Midtrans Snap **Production** payment
  page → back on `/dashboard/billing`, a live status banner sourced only
  from Midtrans's server-to-server webhook, never from the redirect URL.
- **Local Agent + approval queue** (`#agent-center`): show the connection
  status, run a read-only local command, then trigger a risky one via
  "Tanya Agent" — it lands in **Antrian Izin — Local Agent** instead of
  running immediately; approve it from the queue and watch it execute.

## Backup talking points

- **"Is this mocked?"** — No. 1126 automated backend tests (1104 passing),
  every dashboard page live-crawled for errors, real LLM calls
  (DeepSeek/OpenRouter) on every step above.
- **"What stops an agent from going rogue?"** — Any write action that
  reaches a real customer, or a risky local-machine action, is
  architecturally forced through a pending-approval queue — enforced at
  the execution layer, not a UI suggestion.
- **"How is this multi-tenant?"** — Every table is scoped by `org_id`;
  RBAC has 5 role tiers; see [`docs/SECURITY.md`](../SECURITY.md) and
  [`docs/DATABASE.md`](../DATABASE.md).
