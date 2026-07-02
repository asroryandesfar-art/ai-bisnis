# BotNesia — Pitch

*Judge-facing summary. Full 12-slide deck: [`docs/hackathon/PITCH_DECK.md`](../hackathon/PITCH_DECK.md).*

## What it is

BotNesia is an **Enterprise Multi-Agent AI Platform** — not a chatbot. A
Supervisor agent orchestrates 25+ specialist AI agents (Customer Service,
Sales, Knowledge, Finance, Marketing, HR, Operations, Security, Executive)
that collaborate in real time to run both a business's customer-facing chat
and its own internal back office.

Live today at **[botnesia.uk](https://botnesia.uk)** — multi-tenant,
production, real tenants, not a demo shell.

## The problem

Businesses adopting AI today get one of two things: a single chatbot that
answers FAQs and nothing else, or a pile of disconnected point tools
someone has to glue together by hand. Neither remembers a customer across
sessions, collaborates across departments, or runs the business itself.

## The solution

An AI Workforce, not an AI feature. One pipeline routes every customer
message through intent classification, a parallel specialist fan-out,
synthesis, and a verification/critique loop before it reaches a customer —
with automatic human escalation when confidence is low. The same
Supervisor also exposes 7 internal "AI Workforce" agents that run the
tenant's own finance, marketing, HR, and operations, always behind
authenticated endpoints, never mixed into the public chat pipeline.

## What's new since the last submission

- **Local Computer Agent** — a downloadable script connects a tenant's own
  PC to BotNesia over WebSocket, giving the AI file/terminal/browser access
  on that machine, gated by a real human-approval queue for anything risky
  (`run_command`, file writes). Previously this queue was a dead end
  (risky actions were shown but never actually approvable); it's now wired
  end-to-end and covered by automated tests.
- **Midtrans payments, confirmed live against Production** — invoice
  creation, Snap token generation, the hosted payment page, and a signed
  webhook notification flipping invoice status have all been verified with
  real API calls against Midtrans's Production endpoint. The only
  remaining gate is Midtrans's own merchant business review, not our code.

## The numbers, honestly

- **1126** automated backend tests, **1104** passing, 19 pre-existing
  failures in unrelated modules (document generator, AI language-quality
  checks) not touched this pass.
- **25** wired, working agent classes.
- **5** live customer channels (WhatsApp, Instagram, Facebook, Telegram,
  web widget) behind one unified inbox.

## Why this matters

BotNesia isn't a weekend build pretending to be a platform — it's a
platform that happens to be entering this program. Multi-agent
collaboration, autonomous execution with a real human-in-the-loop safety
gate, long-term memory, and a self-building knowledge engine are the same
code paths serving real tenants right now, not slideware.

## Ask

Pilot enterprise customers, technical feedback from the judging panel, and
(where relevant) support to grow this beyond one founder's nights and
weekends.

**Try it live:** [botnesia.uk](https://botnesia.uk)
