# BotNesia — Roadmap

## Now (shipped, live on botnesia.uk)
Multi-agent collaboration pipeline, 7-agent AI Workforce, Tool Framework
with human-approval gating, omnichannel (WhatsApp/Instagram/Facebook/
Telegram/web), multi-tenant RBAC + billing, Knowledge Engine, Workflow
Builder, Investor Demo mode. See [`FEATURES.md`](FEATURES.md) for the full
verified list.

## Near-term (next 1–3 months)
- **Voice channel** — phone/IVR entry point into the same Supervisor
  pipeline that already handles chat, so a customer can call in and reach
  the same AI Workforce.
- **Calendar integration** (Google/Outlook) — currently honestly marked
  unavailable in `tool_registry.py`; wire a real calendar tool once OAuth
  scopes are activated.
- **Agent Marketplace** — let verified third-party developers publish
  specialist agents (beyond the built-in 25) into a tenant's workforce,
  reusing the existing `marketplace_templates` infrastructure.
- **Outbound email** — currently inbound-only (Gmail polling); add a
  human-approval-gated send path mirroring `channel_messaging`'s pattern.

## Mid-term (3–6 months)
- **Fully autonomous multi-day workflows** — extend the Task Engine
  (`task_engine.py`) beyond single-session goals into long-running,
  checkpointed multi-day agent workflows with progress tracking
  (`workforce_tasks.progress_pct` already exists as a foundation).
- **Self-serve onboarding** — guided setup wizard so a new tenant can go
  from signup to a working AI Workforce without manual configuration.
- **Deeper CRM/ERP connectors** — beyond the internal Finance/HR/
  Operations tables, integrate with external CRM/accounting systems tenants
  already use.

## Long-term (6–12 months)
- **Horizontal scaling** — move from the current single-VM/single-Postgres
  topology to a managed, horizontally-scaled deployment as tenant count
  grows past what one VM can serve.
- **Fine-tuned / open-weight model option** — let enterprise tenants choose
  a self-hosted or fine-tuned model instead of the default Groq-hosted
  Llama, for data-residency-sensitive customers.
- **White-label reseller program** — productize the `white_label`/
  `custom_domain` Enterprise-plan features (already in the billing schema)
  into a full reseller onboarding flow.

## Explicitly not planned (by design)
- A light-mode toggle is not on the roadmap — the dashboard is intentionally
  dark-only for the premium enterprise aesthetic. Revisit only if real
  customer demand emerges.
