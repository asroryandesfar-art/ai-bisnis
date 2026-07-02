# BotNesia — Video Script

Shot-by-shot version of [`demo-script.md`](demo-script.md) / the full
[`docs/hackathon/DEMO_SCRIPT.md`](../hackathon/DEMO_SCRIPT.md), formatted
for recording a submission video. Every step has been live-verified against
production before this script was written.

**Before recording:** have `https://botnesia.uk` open and already logged
in to `/dashboard`. Pick one marketplace demo bot for the chat widget.

| Timestamp | Screen | Narration |
|---|---|---|
| 0:00–0:20 | Landing page (`botnesia.uk`) | "This is BotNesia — not a chatbot, an Enterprise Multi-Agent AI Platform. One Supervisor AI orchestrating 25 specialist agents, live, in production." |
| 0:20–1:10 | Chat widget, two messages sent | Message 1 (general question) routes to General AI Agent; message 2 (pricing question) routes to Sales Agent. "Same conversation, but the Supervisor just routed this one differently — that's multi-agent collaboration happening in real time." |
| 1:10–2:10 | `#investor-demo` → "Run Investor Demo" | "This simulates a company with declining revenue and lets the same AI Business Analyst that powers our Executive Center diagnose it, live — a real LLM call, not canned text." |
| 2:10–2:45 | `#agent-center` | Agent Directory table, live "Run Task" against Finance Agent, Channel Messaging approval queue: "Any AI agent that wants to message a real customer queues here first — a human always approves before anything sends." |
| 2:45–3:15 *(new)* | `#billing` → Top Up Rp25.000 | Real Midtrans Snap **Production** payment page opens. "Real payment gateway, real webhook — the only thing gating a completed charge right now is Midtrans's own business review, not our code." |
| 3:15–3:45 *(new)* | `#agent-center` → Local Agent | Show connection status, run a read-only local command live, trigger a risky one, show it land in **Antrian Izin — Local Agent**, approve it. "A real human-in-the-loop safety gate for an agent that can touch a user's own computer." |
| 3:45–4:00 | Close | "Multi-agent collaboration, long-term memory, a self-building knowledge engine, autonomous task execution with a human-approval safety net, full multi-tenant SaaS — all live, all tested, all running today at botnesia.uk." |

## If time-constrained (3-minute cut)

Drop the two *(new)* rows and go straight from Agent Center (2:10–2:45) to
the close — this matches the original core script exactly.

## Recording notes

- Prefer a real browser session over a screen-recorded mockup — every
  claim above should be independently reproducible by a judge following
  [`demo-script.md`](demo-script.md).
- If the local agent isn't connected when recording, show the honest
  offline state (install instructions + disabled test button) rather than
  faking a connected state — this is itself proof the offline/online
  states are real, not decorative.
