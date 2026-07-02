# BotNesia — Judging Checklist

A self-audit against the criteria judges typically use, with concrete
evidence for each — not just a claim. See
[`proof-of-work.md`](proof-of-work.md) for the underlying receipts.

| Criterion | Evidence |
|---|---|
| **Working product, not slides** | Live at [botnesia.uk](https://botnesia.uk). Login, dashboard, chat pipeline, billing, and Agent Center are all real and clickable today — not a static mockup. |
| **Technical depth** | Real multi-agent orchestration (`supervisor.py`), 25 wired agent classes, a real LLM-tool-calling framework, and a WebSocket-based local computer agent with a server-enforced human-approval gate — see [`architecture.md`](architecture.md). |
| **Automated testing** | 1126 backend tests, 1104 passing (honest count, not rounded up — see [`proof-of-work.md`](proof-of-work.md) for the 19 pre-existing unrelated failures). |
| **Real integrations, not mocks** | Midtrans payment integration confirmed against **Production** (not sandbox): real invoice, real Snap token, real hosted payment page, real signed webhook flipping invoice status. |
| **Security posture** | Multi-tenant `org_id` isolation on every table, 5-tier RBAC with per-domain permissions, JWT auth with revocable sessions, audit logging, webhook signature verification (Midtrans SHA-512, Meta HMAC), rate limiting. |
| **Human-in-the-loop safety** | Two independent approval gates: outbound customer messaging (Channel Messaging queue) and risky local-machine actions (Local Agent queue) — both enforced server-side, not just UI suggestions. |
| **Honesty about gaps** | [`README.md`](../../README.md#current-status) and [`FEATURES.md`](../hackathon/FEATURES.md) both explicitly list what's *not* built yet (voice channel, calendar integration, agent marketplace) instead of implying full coverage. |
| **Real-world relevance** | Built for Indonesian SMBs/enterprises that need customer support, sales, and back-office automation without hiring a large ops team or stitching together five separate SaaS tools. |
| **Live for real users** | Multi-tenant, in production, with a real merchant Midtrans account under business review — not a single-tenant hackathon fork. |

## What to actually click, if you have 5 minutes

Follow [`demo-script.md`](demo-script.md) — it's the exact click-path used
to verify every claim in this checklist, not a curated highlight reel.
