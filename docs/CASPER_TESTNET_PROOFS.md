# Casper Testnet Proofs — BotNesia AI Proof Registry

**Network:** Casper **Testnet** (`casper-test`)
**Explorer:** https://testnet.cspr.live

BotNesia anchors AI agent business decisions on-chain as immutable, auditable
proofs. Every anchored decision produces a Casper Testnet deploy that can be
independently verified on the block explorer.

> All values below are real and taken from the deployed contract
> (`casper_anchor.py`) and the `casper_proofs` table. Verify each link on
> https://testnet.cspr.live.

## Smart contract

| Field | Value |
|-------|-------|
| Contract name | `ai_proof_registry` (WASM: `ai_proof_registry.wasm`) |
| **Contract package hash** | `897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0` |
| **Contract hash** | `15009cd4a6489c904b699c0a1f292e7e5557e823e54c236539c9ce9973ee2323` |
| Contract explorer | https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0 |

**Description:** The `ai_proof_registry` contract stores a keccak/session hash
of each AI agent decision (action name, AI decision, timestamp). It exposes a
`store_proof` entry point; the anchored hash is written to global state and is
permanently verifiable on-chain. Source of truth for these hashes:
`casper_anchor.py` lines 32–34.

## Sample Testnet transactions (deploys)

These are real, **confirmed** anchoring deploys produced by the running app.
Look each one up at `https://testnet.cspr.live/deploy/<deploy_hash>`.

| # | Deploy (transaction) hash | Status | Date (UTC) | Description |
|---|---------------------------|--------|------------|-------------|
| 1 | `fbb4b7e766c0275980074d070d446d8e64703c2c2eb81be84637dfa531aa7b4e` | confirmed | 2026-07-04 13:51 | Real AI-decision proof anchored via `store_proof` (proof_mode = `real`). |
| 2 | `cc2739a746eb1916ffaa1b4ce150266039b09cedc566d28cbf3090c53df3d04b` | confirmed | 2026-06-27 21:52 | Real AI-decision proof anchored via `store_proof` (proof_mode = `real`). |

Direct explorer links:
- https://testnet.cspr.live/deploy/fbb4b7e766c0275980074d070d446d8e64703c2c2eb81be84637dfa531aa7b4e
- https://testnet.cspr.live/deploy/cc2739a746eb1916ffaa1b4ce150266039b09cedc566d28cbf3090c53df3d04b

## Sender account

The deploys above are signed by the platform's Casper Testnet account. The
signing account's **public key / account hash** is visible on each deploy's
explorer page (the "sender" field). The private/secret key is **never** stored
in this repository — it is provided at runtime via environment/secret manager.

> TODO (optional, for the BUIDL page): add the sender **public** account hash if
> you want it listed explicitly. Get it from any deploy explorer page above
> (field "From"/"Sender"), or run: `casper-client account-address --public-key <path-to-public-key.pem>`.

## How to reproduce / get fresh hashes

1. Open the dashboard Casper tab: `http://localhost:8000/casper` (or the live
   URL) and trigger an AI decision that anchors a proof, **or** call the API:
   ```
   POST /api/casper/anchor
   ```
2. The response includes `deploy_hash`, `contract_package_hash`, `explorer_url`,
   and `contract_url` (see `main.py` around the `/api/casper/anchor` handler,
   ~line 6409).
3. Query stored proofs directly:
   ```sql
   SELECT deploy_hash, tx_status, proof_mode, submitted_at
   FROM casper_proofs
   WHERE deploy_hash IS NOT NULL
   ORDER BY submitted_at DESC;
   ```
4. Verify any `deploy_hash` at `https://testnet.cspr.live/deploy/<deploy_hash>`.

## For the DoraHacks BUIDL page

Copy-paste block (all values are real Casper Testnet data):

```
Network: Casper Testnet (casper-test)
Contract package hash: 897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
Contract hash:         15009cd4a6489c904b699c0a1f292e7e5557e823e54c236539c9ce9973ee2323
Contract explorer:     https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
Sample tx 1 (confirmed): fbb4b7e766c0275980074d070d446d8e64703c2c2eb81be84637dfa531aa7b4e
Sample tx 2 (confirmed): cc2739a746eb1916ffaa1b4ce150266039b09cedc566d28cbf3090c53df3d04b
```
