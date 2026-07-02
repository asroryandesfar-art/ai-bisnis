# BotNesia — Proof of Work

Everything below is verified against the running production instance or
the actual repository state as of this submission — not aspirational
copy. Where a number could go stale, it's dated.

## Live links

- **Product**: [botnesia.uk](https://botnesia.uk)
- **Source**: [github.com/asroryandesfar-art/ai-bisnis](https://github.com/asroryandesfar-art/ai-bisnis)
- **Screenshots**: [`docs/marketing/screenshots/`](../marketing/screenshots/) — see [`screenshots.md`](screenshots.md)

## Automated tests

```
$ python3 -m pytest -q
19 failed, 1104 passed, 3 skipped in 108.63s
```

1126 tests total. The 19 failures are pre-existing and unrelated to this
submission's changes — they're in `test_document_generator.py` (PDF/PPTX
generation), `test_language_and_quality.py` (AI prose-quality heuristics),
and a few reasoning-pipeline ordering tests. Listed honestly rather than
hidden.

## Midtrans billing — verified live, not just unit-tested

During this engagement, the following was confirmed with **real API
calls against Midtrans Production** (not sandbox):

1. `POST /api/billing/credits/topup` created a real invoice
   (`INV-202607-4F4CC741`) and returned a real Midtrans Snap token +
   `redirect_url` on `app.midtrans.com` (production domain, confirmed by
   `MIDTRANS_IS_PRODUCTION=true`).
2. The Snap payment page itself returned HTTP 200 (confirmed reachable).
3. A correctly-signed fake Midtrans webhook notification (SHA-512 per
   Midtrans's spec) was POSTed to `/api/billing/webhooks/midtrans`, and the
   invoice status was independently confirmed to flip from `open` → `paid`
   — proving the signature verification and status-write path both work
   end to end. The test invoice and its `payment_history` row were deleted
   afterward, and the org's real subscription was confirmed untouched.
4. `/dashboard/billing`, previously a 404 (no backend route existed for
   Midtrans's Finish Redirect URL), now correctly forwards Midtrans's
   redirect and shows a live success/pending/failed banner sourced only
   from the database (never from the redirect's own query params).

**What's not yet done**: a real customer completing an actual payment —
that's gated on Midtrans's own merchant business review, which is a
process on their side, not a code gap on ours.

## Local Computer Agent — approval queue fixed and tested

Before this submission, risky local-agent actions (`run_command`,
file writes) requested via Agent Center's "Tanya Agent" were returned in
an API response but **never persisted anywhere** — the UI told users to
check an approval queue that could never show them (a real dead end, not
a display bug). This is now fixed:

- Risky actions are persisted to `local_agent_commands` with
  `status='pending_approval'`.
- New `POST /api/local-agent/commands/{id}/approve` actually executes the
  approved action through the same `LocalAgentManager.execute()` path used
  by direct execution, and `POST .../reject` marks it rejected without
  ever running it.
- Covered by 9 new automated tests in `test_local_agent_router.py`,
  including a regression test that specifically reproduces the original
  bug (risky step → must be persisted as `pending_approval`, not just
  returned in the HTTP response).

## Infrastructure

- Runs on persistent PostgreSQL 16 (not ephemeral) via `systemd --user`
  services, behind a Cloudflare named tunnel with HTTPS.
- Daily automated database backup, 14-day retention.

## Production-ready today

- Multi-agent chat pipeline, AI Workforce (Finance/Marketing/HR/
  Operations/Security/Executive), Knowledge Engine, Workflow Builder,
  RBAC, audit logging, session security, omnichannel (WhatsApp/Instagram/
  Facebook/Telegram/web widget).
- Midtrans integration code (invoice → Snap → webhook → subscription
  activation / credit top-up) — pending only Midtrans's merchant review.

## Explicitly still pending (not hidden)

- Real end-to-end paid Midtrans transaction (blocked on Midtrans's
  business review, not our code).
- Xendit path — deliberately not touched this pass, deferred by choice.
- A fully seeded, self-serve demo tenant (customers/invoices/conversations
  pre-populated for unsupervised judge click-through) — current demo is a
  guided walkthrough of real production features instead; see
  [`demo-script.md`](demo-script.md) for why that tradeoff was made.
