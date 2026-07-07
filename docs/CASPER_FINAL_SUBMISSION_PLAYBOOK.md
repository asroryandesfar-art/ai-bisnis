# BotNesia — Casper Buildathon Testing Playbook

A step-by-step guide for reviewers/testers. This is an operational guide, not
marketing copy. Follow it top to bottom to verify the MVP and the Casper
Testnet integration.

> Replace `https://botnesia.uk` below with the exact live demo URL if it
> differs. A fully local run is also documented in the "Local run" section.

## 1. Prerequisites

- A modern browser (Chrome/Firefox/Safari).
- For on-chain verification: access to https://testnet.cspr.live (no wallet
  needed — you are only *reading* the explorer).
- For a local run: Python 3.12, PostgreSQL 16, and one AI provider key.

## 2. Open the demo

- Live: open **https://botnesia.uk** (landing) and click **Dashboard**, or go
  directly to **https://botnesia.uk/dashboard**.
- Casper tab directly: **https://botnesia.uk/casper** (redirects to the
  "Casper Agentic Workflow" dashboard tab).

Expected: the dashboard SPA loads (no login wall for the landing page).

## 3. Create an account / log in

1. On the dashboard, choose **Sign up / Mulai Gratis**.
2. Register with:
   - Organization name (any)
   - Email (any valid format)
   - Password (>= 8 chars)
3. You are logged in as the organization **owner** and land on the dashboard.

Notes:
- Each registration creates an isolated tenant (organization). Data is scoped
  by `org_id` — you will only ever see your own org's data.
- The session token is a JWT stored client-side; it is sent as a Bearer header.

## 4. Main demo flow (AI agent → on-chain proof)

1. **Create a bot**: Dashboard → Agents → *Create agent* (any name/greeting).
2. **Chat with the agent**: open the chat, send a business question, e.g.
   *"Naikkan harga produk A sebesar 10% mulai minggu depan"* or a customer
   complaint. The multi-tier DeepSeek router picks FAST/THINKING/PRO based on
   complexity and your plan (see `docs/DEEPSEEK_BOTNESIA_BRAIN.md`).
3. **Anchor an AI decision to Casper**: open the **Casper Agentic Workflow** tab
   (`/casper`). Trigger/anchor a decision. The card shows:
   `Action Name · AI Decision · Casper Status · Tx Hash · Timestamp`.
4. **Copy the Tx Hash** shown ("deploy_hash") — you will verify it in step 6.

API equivalent (if you prefer curl / Postman):
```
POST /api/casper/anchor
# Response includes: deploy_hash, contract_package_hash, explorer_url, contract_url
```

## 5. Run the tests

```bash
# Pure/unit tests (no DB, no secrets) — same set CI runs:
python -m pytest test_deepseek_brain.py test_rbac_privilege_escalation.py -q

# Casper workflow unit tests:
python -m pytest casper/test_casper_workflow.py test_casper_workflow.py -q

# Full suite (needs a live DB + AI keys):
python -m pytest -q
```

Expected: the pure/unit and Casper tests pass. A small number of full-suite
tests need live AI providers and will be skipped/failed without keys — that is
expected and documented.

## 6. Verify the Casper Testnet integration

1. Take the `deploy_hash` (Tx Hash) from step 4, **or** use a known confirmed
   sample from `docs/CASPER_TESTNET_PROOFS.md`:
   - `fbb4b7e766c0275980074d070d446d8e64703c2c2eb81be84637dfa531aa7b4e`
2. Open: `https://testnet.cspr.live/deploy/<deploy_hash>`.
   - Expected: deploy status **Success**, network **casper-test**, and the
     called contract matches the package hash below.
3. Open the contract package:
   `https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0`
   - Expected: the `ai_proof_registry` contract with recent deploys.

## 7. Expected results (summary)

| Step | Expected result |
|------|-----------------|
| Open demo | Dashboard SPA loads; `/casper` opens the Casper tab |
| Register | New isolated org; logged in as owner |
| Chat | Agent replies; tier = FAST/THINKING/PRO by complexity + plan |
| Anchor | Card shows a `deploy_hash` and Casper status |
| Explorer | Deploy resolves as Success on casper-test |
| Contract | Package hash `897c4bd6…a9f0` resolves to `ai_proof_registry` |
| Tests | Pure/unit + Casper tests pass |

## 8. Troubleshooting

- **Dashboard blank / assets 404** → hard-refresh (Ctrl/Cmd+Shift+R); the app
  serves the SPA and API from the same origin.
- **"Database schema belum siap" on register/login** → PostgreSQL is not
  reachable; check `DATABASE_URL`. Schema auto-migrates on first request.
- **Chat returns a safe fallback / escalation** → the AI provider key is missing
  or the DeepSeek model is unavailable; the router falls back to the legacy
  pipeline. Set a valid `DEEPSEEK_API_KEY` (and `DEEPSEEK_BRAIN_ENABLED=1` to use
  the 3-tier router).
- **Anchor shows `proof_mode = demo`** → Casper signing key not configured; the
  app records a demo proof instead of a real deploy. Provide the Casper account
  key via env to produce real deploys.
- **`/docs` returns 404** → intended in production (`ENABLE_API_DOCS=0`).

## Local run (self-contained)

```bash
git clone https://github.com/asroryandesfar-art/ai-bisnis.git
cd ai-bisnis
pip install -r requirements.txt
cp .env.example .env      # fill DATABASE_URL, SECRET_KEY (>=32 chars), an AI key
python -m uvicorn main:app --host 127.0.0.1 --port 8000
# Dashboard: http://localhost:8000/dashboard   Casper: http://localhost:8000/casper
```
