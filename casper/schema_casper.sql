-- Casper Agentic Buildathon 2026 — additive migration
-- Records every AI business decision and its immutable Casper Testnet proof.
-- These tables do NOT touch any existing BotNesia tables.

CREATE TABLE IF NOT EXISTS agent_actions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id           UUID REFERENCES bots(id) ON DELETE SET NULL,
    conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
    agent_name       TEXT        NOT NULL DEFAULT 'BotNesia AI',
    action_type      TEXT        NOT NULL,          -- e.g. "hire", "price_change", "marketing"
    action_summary   TEXT        NOT NULL,
    decision_detail  JSONB       NOT NULL DEFAULT '{}',
    user_message     TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_actions_org ON agent_actions(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_actions_type ON agent_actions(org_id, action_type);

CREATE TABLE IF NOT EXISTS casper_proofs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id             UUID NOT NULL REFERENCES agent_actions(id) ON DELETE CASCADE,
    org_id                UUID NOT NULL,
    session_hash          TEXT NOT NULL,
    deploy_hash           TEXT,
    tx_status             TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | failed
    contract_package_hash TEXT,
    account_key           TEXT,
    proof_mode            TEXT NOT NULL DEFAULT 'real',     -- real | demo
    explorer_url          TEXT,
    contract_url          TEXT,
    error_message         TEXT,
    submitted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at          TIMESTAMPTZ,
    UNIQUE(action_id)
);
CREATE INDEX IF NOT EXISTS ix_casper_proofs_org ON casper_proofs(org_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS ix_casper_proofs_status ON casper_proofs(tx_status);
