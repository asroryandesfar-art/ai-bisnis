-- ============================================================
-- BotNesia — Phase 2: Business Platform Schema (multi-tenant SaaS)
-- PostgreSQL 15+ — dijalankan SETELAH schema.sql + intelligence/schema_intelligence.sql
--
-- PRINSIP PENTING — TIDAK REBUILD:
--   `organizations` pada schema.sql SUDAH MERUPAKAN unit tenant
--   (1 baris = 1 perusahaan klien, semua tabel anak punya org_id).
--   Maka di Phase 2 kita TIDAK membuat tabel `tenants` baru yang akan
--   duplikat & memecah graph FK yang sudah ada di puluhan tabel.
--   Sebagai gantinya: `organizations.id` BERPERAN sebagai `tenant_id`.
--   Lihat VIEW `tenants` di bagian bawah untuk kompatibilitas penamaan
--   ("tenant" adalah istilah bisnis, "organization" adalah nama tabel).
--
-- Semua tabel baru WAJIB punya kolom org_id (tenant isolation) dan
-- semua query WAJIB difilter `WHERE org_id = $current_tenant`
-- (lihat bn_platform/tenancy.py — guard di level repository).
-- ============================================================

-- ============================================================
-- 0. EXTENSION & ENUM TYPES BARU
-- ============================================================

DO $$ BEGIN
    CREATE TYPE permission_scope_t AS ENUM ('platform', 'tenant');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE handoff_priority_t AS ENUM ('low', 'medium', 'high', 'urgent');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE handoff_status_t AS ENUM ('waiting', 'assigned', 'resolved', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE channel_type_t AS ENUM ('whatsapp', 'telegram', 'website', 'instagram', 'facebook', 'email', 'gmail');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE subscription_status_t AS ENUM ('trialing', 'active', 'past_due', 'canceled', 'paused');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE invoice_status_t AS ENUM ('draft', 'open', 'paid', 'void', 'uncollectible');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE payment_provider_t AS ENUM ('midtrans', 'xendit', 'manual');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE lead_category_t AS ENUM ('cold', 'warm', 'hot');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE audit_action_t AS ENUM (
        'create', 'update', 'delete', 'login', 'logout',
        'login_failed', 'permission_denied', 'export', 'invite',
        'role_change', 'plan_change', 'payment', 'security_scan'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 1. RBAC — roles, permissions
-- ============================================================
-- Katalog permission GLOBAL (sama untuk semua tenant). Role bisa
-- bersifat sistem (5 role baku: owner/admin/manager/agent/viewer,
-- org_id = NULL, tidak bisa dihapus tenant) ATAU custom per tenant.

CREATE TABLE IF NOT EXISTS permissions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key         TEXT NOT NULL UNIQUE,     -- 'bots.write', 'billing.manage', dst (lihat bn_platform/rbac.py::PERMISSIONS)
    category    TEXT NOT NULL,            -- 'bots' | 'conversations' | 'billing' | 'team' | 'analytics' | 'settings'
    description TEXT NOT NULL,
    scope       permission_scope_t NOT NULL DEFAULT 'tenant'
);

CREATE TABLE IF NOT EXISTS roles (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = role sistem (berlaku semua tenant)
    key         TEXT NOT NULL,            -- 'owner' | 'admin' | 'manager' | 'agent' | 'viewer' | custom slug
    name        TEXT NOT NULL,
    description TEXT,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE = tidak bisa diedit/dihapus tenant
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, key)
);

CREATE INDEX IF NOT EXISTS idx_roles_org ON roles(org_id);
-- UNIQUE (org_id, key) di atas TIDAK berlaku untuk role sistem (org_id NULL)
-- -- Postgres menganggap NULL selalu berbeda satu sama lain di unique
-- constraint, jadi ON CONFLICT (org_id, key) tidak pernah ke-trigger untuk
-- baris ini. Index partial ini menutup celahnya (lihat scripts/dedupe_system_roles.sql
-- untuk pembersihan data lama yang sudah terlanjur terduplikasi).
CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_system_key_unique ON roles(key) WHERE org_id IS NULL;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Tabel pivot user<->role (mendukung multi-role per user di masa depan;
-- saat ini bn_platform/rbac.py memetakan users.role lama ke role sistem
-- yang sesuai sehingga kompatibel mundur tanpa migrasi data paksa).
CREATE TABLE IF NOT EXISTS user_roles (
    user_id    UUID NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    role_id    UUID NOT NULL REFERENCES roles(id)  ON DELETE CASCADE,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_org  ON user_roles(org_id);

-- ============================================================
-- 2. SUBSCRIPTION & BILLING
-- ============================================================

CREATE TABLE IF NOT EXISTS plans (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key               TEXT NOT NULL UNIQUE,   -- 'free' | 'starter' | 'pro' | 'business' | 'enterprise'
    name              TEXT NOT NULL,
    price_monthly_idr BIGINT NOT NULL DEFAULT 0,
    price_yearly_idr  BIGINT NOT NULL DEFAULT 0,
    max_conversations_per_month INT NOT NULL DEFAULT 100,   -- -1 = unlimited
    max_agents        INT NOT NULL DEFAULT 1,               -- jumlah AI agent/bot aktif
    max_users         INT NOT NULL DEFAULT 1,               -- anggota tim
    max_knowledge_docs INT NOT NULL DEFAULT 5,
    max_channels      INT NOT NULL DEFAULT 1,               -- jumlah channel omnichannel terhubung
    features          JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"analytics": true, "api_access": false, ...}
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order        INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Phase 3 Multimodal: kuota image generation per paket (-1 = unlimited)
ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_image_generations_per_month INT NOT NULL DEFAULT 10;

-- Credit & Free Trial system (additive)
ALTER TABLE plans ADD COLUMN IF NOT EXISTS free_trial_eligible BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS is_free_trial BOOLEAN NOT NULL DEFAULT FALSE;

-- Credit ledger: setiap top-up dan debit dicatat di sini
CREATE TABLE IF NOT EXISTS credit_ledger (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,               -- 'topup' | 'debit' | 'refund' | 'bonus'
    amount_idr    BIGINT NOT NULL DEFAULT 0,   -- nilai rupiah top-up (hanya topup/bonus), untuk invoice
    credits       BIGINT NOT NULL DEFAULT 0,   -- legacy field, tidak dipakai lagi di UI
    conversations BIGINT NOT NULL DEFAULT 0,   -- +N percakapan (topup/bonus) atau -N (debit)
    description   TEXT NOT NULL DEFAULT '',
    invoice_id    UUID REFERENCES invoices(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Additive: tambah kolom conversations jika tabel sudah ada tanpa kolom ini
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS conversations BIGINT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_credit_ledger_org ON credit_ledger(org_id, created_at DESC);

-- Cached balance: stores addon conversation count (bukan Rupiah)
CREATE TABLE IF NOT EXISTS credit_balances (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    balance     BIGINT NOT NULL DEFAULT 0,   -- jumlah percakapan tambahan tersisa
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plan_id             UUID NOT NULL REFERENCES plans(id),
    status              subscription_status_t NOT NULL DEFAULT 'trialing',
    billing_cycle       TEXT NOT NULL DEFAULT 'monthly',  -- 'monthly' | 'yearly'
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end   TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at         TIMESTAMPTZ,
    trial_ends_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id)   -- satu tenant = satu subscription aktif (riwayat ada di invoices)
);

CREATE INDEX IF NOT EXISTS idx_subs_org    ON subscriptions(org_id);
CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subs_period_end ON subscriptions(current_period_end);

-- Grandfathering (P2): harga terkunci saat aktivasi. Bila admin menaikkan harga
-- plan, pelanggan lama tetap membayar harga yang mereka setujui (locked). NULL =
-- belum terkunci → pakai harga live plan (paket free/legacy). Lock dipertahankan
-- selama tetap di plan yang sama; berpindah plan mengunci ulang harga plan baru.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS locked_price_monthly_idr BIGINT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS locked_price_yearly_idr  BIGINT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS price_locked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS invoices (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    invoice_number  TEXT NOT NULL UNIQUE,    -- 'INV-2026-000123'
    status          invoice_status_t NOT NULL DEFAULT 'open',
    amount_idr      BIGINT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'IDR',
    description     TEXT,
    provider        payment_provider_t,
    provider_invoice_id TEXT,                -- ID dari Midtrans/Xendit
    provider_payment_url TEXT,               -- redirect URL pembayaran (Snap/Xendit invoice page)
    due_date        TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '3 days'),
    paid_at         TIMESTAMPTZ,
    voided_at       TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_org    ON invoices(org_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_provider_ref ON invoices(provider, provider_invoice_id);

CREATE TABLE IF NOT EXISTS payment_history (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id                 UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    invoice_id             UUID REFERENCES invoices(id) ON DELETE SET NULL,
    provider               payment_provider_t NOT NULL,
    provider_transaction_id TEXT,
    amount_idr             BIGINT NOT NULL,
    status                 TEXT NOT NULL,     -- raw status dari provider: 'settlement' | 'PAID' | 'expire' | dst
    payment_method         TEXT,              -- 'qris' | 'bank_transfer' | 'credit_card' | 'ewallet' dst
    raw_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- payload notifikasi mentah (utk audit/debug)
    received_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payhist_org     ON payment_history(org_id);
CREATE INDEX IF NOT EXISTS idx_payhist_invoice ON payment_history(invoice_id);
-- idx_payhist_provtx dulu non-unique -- webhook retry dari Midtrans/Xendit yang
-- datang bersamaan bisa lolos check-then-act di aplikasi dan keduanya INSERT,
-- dobel-hitung di payment_history/revenue_intel. DROP dulu supaya "IF NOT EXISTS"
-- di bawah tidak diam-diam skip upgrade ke UNIQUE pada DB yang sudah punya index lama.
DROP INDEX IF EXISTS idx_payhist_provtx;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payhist_provtx ON payment_history(provider, provider_transaction_id)
    WHERE provider_transaction_id IS NOT NULL;

-- ============================================================
-- 3. HUMAN HANDOFF QUEUE
-- ============================================================

CREATE TABLE IF NOT EXISTS human_queue (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL,            -- 'low_confidence' | 'angry_sentiment' | 'heavy_complaint' | 'manual'
    priority        handoff_priority_t NOT NULL DEFAULT 'medium',
    status          handoff_status_t  NOT NULL DEFAULT 'waiting',
    assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at     TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    sla_due_at      TIMESTAMPTZ,              -- target waktu respon berdasarkan priority
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id)                  -- satu percakapan hanya satu entri antrean aktif
);

CREATE INDEX IF NOT EXISTS idx_handoff_org      ON human_queue(org_id, status);
CREATE INDEX IF NOT EXISTS idx_handoff_assignee ON human_queue(assigned_agent_id) WHERE status = 'assigned';
CREATE INDEX IF NOT EXISTS idx_handoff_priority ON human_queue(org_id, priority, created_at) WHERE status = 'waiting';

-- Human Handoff compatibility contract. `human_queue` remains canonical.
CREATE OR REPLACE VIEW handoffs AS
SELECT
    id,
    org_id AS tenant_id,
    conversation_id,
    reason,
    CASE WHEN status::text = 'waiting' THEN 'pending' ELSE status::text END AS status,
    assigned_agent_id AS assigned_to,
    created_at
FROM human_queue;


-- ============================================================
-- 4. OMNICHANNEL — channel accounts & unified inbox
-- ============================================================

CREATE TABLE IF NOT EXISTS channel_accounts (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id        UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    channel_type  channel_type_t NOT NULL,
    display_name  TEXT NOT NULL,
    external_id   TEXT,             -- nomor WA / username Telegram bot / domain website
    credentials   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- token terenkripsi, lihat bn_platform/security.py::encrypt_value
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    connected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sync_at  TIMESTAMPTZ,
    UNIQUE (org_id, channel_type, external_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_accounts_org ON channel_accounts(org_id);
CREATE INDEX IF NOT EXISTS idx_channel_accounts_bot ON channel_accounts(bot_id);

-- Kolom tambahan ke `conversations` agar mendukung Unified Inbox
-- (channel & revenue_amount sudah ditambahkan oleh intelligence/schema_intelligence.sql;
--  di sini kita tambah kepemilikan channel & status assignment utk inbox).
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS channel_account_id UUID REFERENCES channel_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assigned_agent_id   UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS unread_count        INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS language             TEXT NOT NULL DEFAULT 'id',
    ADD COLUMN IF NOT EXISTS closed_at           TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_convs_channel_account ON conversations(channel_account_id);
CREATE INDEX IF NOT EXISTS idx_convs_assigned_agent  ON conversations(assigned_agent_id);

-- VIEW: status inbox terpadu — dipakai langsung oleh dashboard Unified Inbox
CREATE OR REPLACE VIEW unified_inbox AS
SELECT
    c.id                AS conversation_id,
    c.org_id,
    c.bot_id,
    c.channel_account_id,
    COALESCE(NULLIF(c.channel, 'widget'), 'website') AS channel,
    c.end_user_id, c.end_user_name, c.end_user_email,
    c.assigned_agent_id,
    c.unread_count,
    c.last_msg_at,
    c.resolved,
    c.handoff_needed,
    CASE
        WHEN c.handoff_needed AND hq.status IN ('waiting', 'assigned') THEN 'escalation'
        WHEN c.resolved OR c.closed_at IS NOT NULL                     THEN 'closed'
        WHEN c.assigned_agent_id IS NOT NULL                           THEN 'assigned'
        ELSE 'unread'
    END AS inbox_state,
    hq.priority   AS handoff_priority,
    hq.status     AS handoff_status
FROM conversations c
LEFT JOIN human_queue hq ON hq.conversation_id = c.id;

-- Canonical Omni Channel Phase 1 schema. organizations.id remains the tenant identity,
-- while these tables expose the explicit tenant_id contract used by ChannelManager.
ALTER TYPE channel_type_t ADD VALUE IF NOT EXISTS 'facebook';

CREATE TABLE IF NOT EXISTS channels (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id    UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    channel_type channel_type_t NOT NULL,
    display_name TEXT NOT NULL,
    is_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel_type)
);
CREATE INDEX IF NOT EXISTS idx_channels_tenant ON channels(tenant_id);

CREATE TABLE IF NOT EXISTS channel_connections (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    channel_id           UUID NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    legacy_account_id    UUID REFERENCES channel_accounts(id) ON DELETE SET NULL,
    bot_id               UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    external_id          TEXT NOT NULL DEFAULT '',
    display_name         TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('connected','disconnected','pending','error')),
    credentials          JSONB NOT NULL DEFAULT '{}'::jsonb,
    config               JSONB NOT NULL DEFAULT '{}'::jsonb,
    connected_at         TIMESTAMPTZ,
    disconnected_at      TIMESTAMPTZ,
    last_activity_at     TIMESTAMPTZ,
    last_health_check_at TIMESTAMPTZ,
    error_message        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_connections_tenant ON channel_connections(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_channel_connections_bot ON channel_connections(tenant_id, bot_id);

CREATE TABLE IF NOT EXISTS channel_messages (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connection_id       UUID NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    external_message_id TEXT,
    direction           TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    user_id             TEXT NOT NULL,
    username            TEXT,
    message             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'received',
    response_time_ms    INT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_messages_external ON channel_messages(connection_id, external_message_id, direction) WHERE external_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_channel_messages_tenant_time ON channel_messages(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_channel_messages_user ON channel_messages(tenant_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS channel_events (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connection_id UUID REFERENCES channel_connections(id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL DEFAULT 'pending',
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_channel_events_tenant ON channel_events(tenant_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS channel_logs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connection_id UUID REFERENCES channel_connections(id) ON DELETE CASCADE,
    level         TEXT NOT NULL DEFAULT 'info',
    action        TEXT NOT NULL,
    message       TEXT NOT NULL,
    context       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_channel_logs_tenant ON channel_logs(tenant_id, created_at DESC);

-- ============================================================
-- 5. AUDIT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = aksi level platform
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_email   TEXT,                       -- snapshot, jaga2 user dihapus
    action        audit_action_t NOT NULL,
    resource_type TEXT NOT NULL,              -- 'bot' | 'user' | 'subscription' | 'api_key' | dst
    resource_id   TEXT,
    ip_address    TEXT,
    user_agent    TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_org     ON audit_logs(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor   ON audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, resource_id);

-- Perluasan api_keys: scope granular (mis. ['chat:write','analytics:read'])
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT ARRAY['*']::TEXT[];

-- ============================================================
-- 6. LEAD GENERATION ENGINE
-- ============================================================
-- Skor & kategori prospek; riwayat tersimpan agar tren bisa dianalisis
-- (snapshot per perhitungan, bukan overwrite) — sumber sinyal dari
-- intelligence.customer_profiles & intelligence.sales_signals.

CREATE TABLE IF NOT EXISTS lead_scores (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    end_user_id     TEXT NOT NULL,
    score           NUMERIC(5,2) NOT NULL,        -- 0-100
    category        lead_category_t NOT NULL,
    signals         JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"purchase_intent":0.7,"engagement":0.4,...}
    recommended_action TEXT,                      -- ringkasan rekomendasi follow-up dari LLM/heuristik
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leadscore_org_cat ON lead_scores(org_id, category, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_leadscore_user    ON lead_scores(org_id, bot_id, end_user_id, computed_at DESC);

-- ============================================================
-- 7. MARKETPLACE TEMPLATE
-- ============================================================

CREATE TABLE IF NOT EXISTS marketplace_templates (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key           TEXT NOT NULL UNIQUE,
    category      TEXT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    preview_image  TEXT,
    system_prompt TEXT NOT NULL,
    greeting      TEXT NOT NULL,
    primary_color TEXT NOT NULL DEFAULT '#2C4477',
    sample_faqs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    install_count INT NOT NULL DEFAULT 0,
    version       TEXT NOT NULL DEFAULT '1.0.0',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_template_installs (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    template_id  UUID NOT NULL REFERENCES marketplace_templates(id),
    bot_id       UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    installed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_installs_org ON tenant_template_installs(org_id);

DROP VIEW IF EXISTS agent_templates;
CREATE VIEW agent_templates AS
SELECT
    id,
    key AS agent_id,
    key,
    name,
    description,
    category,
    version,
    icon,
    primary_color AS color,
    tools,
    knowledge_sources,
    starter_questions,
    visibility,
    rating,
    popularity_score,
    install_count,
    CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status
FROM marketplace_templates;

-- ============================================================
-- 8. REVENUE INTELLIGENCE — snapshot harian utk tren cepat
-- ============================================================
-- org_id NULL  => agregat seluruh platform (admin view)
-- org_id NOT NULL => khusus perhitungan per-tenant (Enterprise self-serve)

CREATE TABLE IF NOT EXISTS revenue_snapshots (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id              UUID REFERENCES organizations(id) ON DELETE CASCADE,
    snapshot_date       DATE NOT NULL,
    mrr_idr             BIGINT NOT NULL DEFAULT 0,
    arr_idr             BIGINT NOT NULL DEFAULT 0,
    active_subscriptions INT NOT NULL DEFAULT 0,
    new_subscriptions   INT NOT NULL DEFAULT 0,
    canceled_subscriptions INT NOT NULL DEFAULT 0,
    churn_rate          NUMERIC(6,4) NOT NULL DEFAULT 0,   -- 0..1
    ltv_idr             BIGINT NOT NULL DEFAULT 0,
    cac_idr             BIGINT NOT NULL DEFAULT 0,
    projected_mrr_idr   BIGINT NOT NULL DEFAULT 0,         -- proyeksi 30 hari ke depan (linear trend)
    raw_metrics         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_revenue_snap_date ON revenue_snapshots(snapshot_date DESC);

-- ============================================================
-- 9. AI QUALITY — penilaian per jawaban (accuracy/helpfulness/conversion)
-- ============================================================
-- Melengkapi conversation_analysis (intelligence) dgn skor per-MESSAGE
-- supaya self-improvement loop (Trainer Agent) py bahan lebih granular.

CREATE TABLE IF NOT EXISTS ai_answer_quality (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    message_id      UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    accuracy_score      NUMERIC(4,3) NOT NULL DEFAULT 0,   -- 0..1
    helpfulness_score   NUMERIC(4,3) NOT NULL DEFAULT 0,
    conversion_impact   NUMERIC(4,3) NOT NULL DEFAULT 0,   -- estimasi kontribusi ke konversi
    overall_score       NUMERIC(4,3) NOT NULL DEFAULT 0,
    feedback_label      TEXT,           -- 'good' | 'needs_review' | 'poor'
    improvement_note    TEXT,           -- saran perbaikan dari Trainer Agent
    evaluated_by        TEXT NOT NULL DEFAULT 'trainer_agent',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (message_id)
);

CREATE INDEX IF NOT EXISTS idx_aiq_org  ON ai_answer_quality(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_aiq_conv ON ai_answer_quality(conversation_id);
CREATE INDEX IF NOT EXISTS idx_aiq_label ON ai_answer_quality(org_id, feedback_label);

-- ============================================================
-- 10. KOMPATIBILITAS PENAMAAN — VIEW `tenants`
-- ============================================================
-- Memenuhi kebutuhan istilah bisnis "tenant" tanpa memecah skema FK
-- existing yang sudah memakai `organizations`/`org_id` di puluhan tabel.
-- Semua kode baru WAJIB pakai bn_platform.tenancy yang membungkus akses
-- ini (lihat ARCHITECTURE.md §1).

CREATE OR REPLACE VIEW tenants AS
SELECT
    o.id            AS tenant_id,
    o.id            AS org_id,
    o.name, o.slug, o.plan, o.billing_status,
    o.bot_limit, o.conv_limit, o.doc_limit,
    o.created_at, o.updated_at
FROM organizations o;

-- ============================================================
-- 10b. FINANCE AGENT (AI Workforce Phase 1)
-- ============================================================
-- Keuangan BISNIS TENANT sendiri (invoice ke pelanggan mereka, expense,
-- laporan) -- terpisah total dari tabel `invoices`/`subscriptions` di atas
-- (itu billing SaaS BotNesia ke tenant). Nama tabel diberi prefix
-- `finance_` justru untuk menghindari tabrakan nama dengan `invoices` yang
-- sudah dipakai billing.

CREATE TABLE IF NOT EXISTS finance_invoices (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id          UUID REFERENCES bots(id) ON DELETE SET NULL,
    invoice_number  TEXT NOT NULL,           -- 'INV-2026-000001', unik per tenant (bukan global)
    customer_name   TEXT NOT NULL,
    customer_contact TEXT,                   -- email/telepon pelanggan tenant (opsional)
    amount_idr      BIGINT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'IDR',
    line_items      JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{"name":..,"qty":..,"price_idr":..}]
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','overdue','cancelled')),
    is_recurring    BOOLEAN NOT NULL DEFAULT FALSE,        -- dasar hitung MRR/ARR/churn tenant
    notes           TEXT,
    due_date        TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    sent_at         TIMESTAMPTZ,
    paid_at         TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_org_created ON finance_invoices(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_status      ON finance_invoices(org_id, status);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_due         ON finance_invoices(org_id, due_date);

CREATE TABLE IF NOT EXISTS finance_payments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    invoice_id  UUID REFERENCES finance_invoices(id) ON DELETE SET NULL,
    amount_idr  BIGINT NOT NULL,
    method      TEXT NOT NULL DEFAULT 'transfer',  -- 'cash'|'transfer'|'qris'|'other'
    paid_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes       TEXT,
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_finance_payments_org_paid ON finance_payments(org_id, paid_at DESC);
CREATE INDEX IF NOT EXISTS idx_finance_payments_invoice  ON finance_payments(invoice_id);

CREATE TABLE IF NOT EXISTS finance_expenses (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    category     TEXT NOT NULL DEFAULT 'lainnya',  -- 'operasional'|'gaji'|'marketing'|'sewa'|'lainnya'
    description  TEXT NOT NULL,
    amount_idr   BIGINT NOT NULL,
    expense_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status       TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded','approved','rejected')),
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_finance_expenses_org_date ON finance_expenses(org_id, expense_date DESC);
CREATE INDEX IF NOT EXISTS idx_finance_expenses_status   ON finance_expenses(org_id, status);

-- Ledger gabungan (auto-terisi tiap kali invoice dibayar / payment dicatat /
-- expense dicatat) -- satu sumber data konsisten untuk semua laporan
-- (revenue/profit/cashflow), supaya logika agregasi tidak terduplikasi
-- di banyak tempat.
CREATE TABLE IF NOT EXISTS finance_transactions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK (type IN ('income','expense')),
    category    TEXT NOT NULL DEFAULT 'lainnya',
    amount_idr  BIGINT NOT NULL,
    source_type TEXT NOT NULL,        -- 'invoice'|'payment'|'expense'|'manual'
    source_id   UUID,
    description TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_finance_tx_org_occurred ON finance_transactions(org_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_finance_tx_org_type     ON finance_transactions(org_id, type);

-- Snapshot laporan yang sudah dihasilkan (revenue/profit/cashflow/forecast)
-- -- cache ringan untuk histori, bukan satu-satunya sumber data (laporan
-- selalu bisa dihitung ulang langsung dari finance_transactions).
CREATE TABLE IF NOT EXISTS finance_reports (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    report_type   TEXT NOT NULL CHECK (report_type IN ('revenue','profit','cashflow','forecast')),
    period_start  TIMESTAMPTZ NOT NULL,
    period_end    TIMESTAMPTZ NOT NULL,
    data          JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_finance_reports_org_type ON finance_reports(org_id, report_type, created_at DESC);

-- ============================================================
-- 10c. MARKETING AGENT (AI Workforce Phase 2)
-- ============================================================
-- Generate konten (IG/TikTok/Facebook/Blog/Email/WhatsApp), kalender
-- konten, dan pencatatan engagement/konversi. Tidak ada integrasi publish
-- API Instagram/TikTok/Facebook sungguhan di codebase ini -- publikasi ke
-- platform tetap MANUAL oleh tenant (AI hanya menyiapkan & menjadwalkan
-- draft); engagement/konversi juga dicatat manual (tenant input angka dari
-- dashboard platform aslinya), bukan auto-fetch. Konsisten dengan
-- Truthfulness Policy yang sudah ada di tool_registry.py.

CREATE TABLE IF NOT EXISTS marketing_campaigns (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id          UUID REFERENCES bots(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    goal            TEXT,
    target_audience TEXT,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','completed','cancelled')),
    start_date      TIMESTAMPTZ,
    end_date        TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_org ON marketing_campaigns(org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS marketing_content (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    campaign_id  UUID REFERENCES marketing_campaigns(id) ON DELETE SET NULL,
    bot_id       UUID REFERENCES bots(id) ON DELETE SET NULL,
    platform     TEXT NOT NULL CHECK (platform IN ('instagram','tiktok','facebook','blog','email','whatsapp')),
    title        TEXT,
    body         TEXT NOT NULL,
    hashtags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','scheduled','ready_to_publish','published','cancelled')),
    scheduled_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    approved_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at  TIMESTAMPTZ,
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_marketing_content_org_created  ON marketing_content(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_marketing_content_campaign     ON marketing_content(campaign_id);
CREATE INDEX IF NOT EXISTS idx_marketing_content_status       ON marketing_content(org_id, status);
CREATE INDEX IF NOT EXISTS idx_marketing_content_scheduled    ON marketing_content(org_id, scheduled_at);

-- Engagement & konversi -- dicatat manual (tenant input angka dari
-- Instagram/TikTok/Facebook Insights mereka sendiri).
CREATE TABLE IF NOT EXISTS marketing_engagement (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    content_id  UUID NOT NULL REFERENCES marketing_content(id) ON DELETE CASCADE,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('likes','comments','shares','views','clicks','conversions')),
    value       BIGINT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_marketing_engagement_content ON marketing_engagement(content_id);
CREATE INDEX IF NOT EXISTS idx_marketing_engagement_org     ON marketing_engagement(org_id, recorded_at DESC);

-- ============================================================
-- 10d. HR AGENT (AI Workforce Phase 3)
-- ============================================================
-- CV screening, candidate scoring, interview question generator, employee
-- evaluation, training recommendation, performance tracking -- untuk
-- bisnis TENANT sendiri (data karyawan/kandidat mereka, bukan karyawan
-- BotNesia). Prefix `hr_` mengikuti konvensi finance_/marketing_ supaya
-- konsisten & aman dari tabrakan nama.

CREATE TABLE IF NOT EXISTS hr_candidates (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id           UUID REFERENCES bots(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    email            TEXT,
    phone            TEXT,
    position_applied TEXT,
    cv_text          TEXT,
    cv_filename      TEXT,
    score            INT CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    score_breakdown  JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','screened','interview','offered','hired','rejected')),
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hr_candidates_org_created ON hr_candidates(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hr_candidates_status       ON hr_candidates(org_id, status);

CREATE TABLE IF NOT EXISTS hr_employees (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id      UUID REFERENCES bots(id) ON DELETE SET NULL,
    full_name   TEXT NOT NULL,
    email       TEXT,
    position    TEXT,
    department  TEXT,
    hire_date   TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','on_leave','terminated')),
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hr_employees_org ON hr_employees(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hr_employees_status ON hr_employees(org_id, status);

CREATE TABLE IF NOT EXISTS hr_evaluations (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    employee_id      UUID NOT NULL REFERENCES hr_employees(id) ON DELETE CASCADE,
    period_start     TIMESTAMPTZ,
    period_end       TIMESTAMPTZ,
    score            INT CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    strengths        TEXT,
    areas_to_improve TEXT,
    status           TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','finalized')),
    evaluator_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    finalized_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    finalized_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hr_evaluations_employee ON hr_evaluations(employee_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hr_evaluations_org       ON hr_evaluations(org_id);

CREATE TABLE IF NOT EXISTS hr_training_records (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES hr_employees(id) ON DELETE CASCADE,
    training_name  TEXT NOT NULL,
    reason         TEXT,
    recommended_by TEXT NOT NULL DEFAULT 'manual' CHECK (recommended_by IN ('ai','manual')),
    status         TEXT NOT NULL DEFAULT 'recommended' CHECK (status IN ('recommended','in_progress','completed')),
    completed_at   TIMESTAMPTZ,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hr_training_employee ON hr_training_records(employee_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hr_training_org       ON hr_training_records(org_id, status);

-- ============================================================
-- 10e. OPERATIONS AGENT (AI Workforce Phase 4)
-- ============================================================
-- Tenant health/workflow/SLA monitoring + weekly/monthly report + critical
-- alert. SENGAJA tidak menduplikasi data -- hanya AGREGASI read-only dari
-- tabel yang sudah ada (workflow_executions, human_queue,
-- ai_improvement_recommendations, conversations), mirip pola
-- improvement_engine.py. Hanya 2 tabel baru: alert + snapshot laporan.

CREATE TABLE IF NOT EXISTS ops_alerts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    severity        TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    category        TEXT NOT NULL,   -- 'sla_breach' | 'workflow_failure' | 'tenant_inactivity' | 'improvement_backlog'
    message         TEXT NOT NULL,
    source_type     TEXT,
    source_id       UUID,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
    acknowledged_by UUID REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ops_alerts_org_status ON ops_alerts(org_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_alerts_category    ON ops_alerts(org_id, category);

CREATE TABLE IF NOT EXISTS ops_reports (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    report_type  TEXT NOT NULL CHECK (report_type IN ('weekly','monthly')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end   TIMESTAMPTZ NOT NULL,
    data         JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary      TEXT,
    generated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ops_reports_org_type ON ops_reports(org_id, report_type, created_at DESC);

-- ============================================================
-- 10f. SECURITY AGENT (AI Workforce Phase 5)
-- ============================================================
-- Reuse ops_alerts/ops_reports dari Phase 4 (Operations Agent) -- bukan
-- tabel baru. `source` membedakan asal alert/report: 'operations'
-- (default, data lama tetap valid) vs 'security' (threat/abuse/isolation
-- findings dari security_agent.py, lapisan tipis di atas
-- bn_platform/security.py::run_security_scan() yang sudah ada).
ALTER TABLE ops_alerts
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'operations';
ALTER TABLE ops_reports
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'operations';
CREATE INDEX IF NOT EXISTS idx_ops_alerts_source  ON ops_alerts(org_id, source, status);
CREATE INDEX IF NOT EXISTS idx_ops_reports_source ON ops_reports(org_id, source, created_at DESC);

-- ============================================================
-- 10g. WORKFORCE ORCHESTRATION (AI Workforce Phase 7)
-- ============================================================
-- Koordinasi lintas-agent (Finance/Marketing/HR/Operations/Security/
-- Executive): assign task, deteksi konflik, eskalasi, human approval.
-- SENGAJA terpisah total dari supervisor.py (orchestrator chat pelanggan)
-- -- tidak ada perubahan ke pipeline chat produksi sama sekali. Eksekusi
-- task tetap lewat endpoint domain masing-masing (manual/human-driven);
-- tabel ini hanya tracking/koordinasi, bukan execution engine otomatis.
CREATE TABLE IF NOT EXISTS workforce_tasks (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    domain            TEXT NOT NULL CHECK (domain IN ('finance','marketing','hr','operations','security','executive')),
    title             TEXT NOT NULL,
    description       TEXT,
    priority          TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','critical')),
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','blocked','completed','cancelled','escalated')),
    source_type       TEXT,             -- mis. 'ops_alert' | 'manual' | 'executive_brief'
    source_id         UUID,
    assigned_to       UUID REFERENCES users(id) ON DELETE SET NULL,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at       TIMESTAMPTZ,
    has_conflict      BOOLEAN NOT NULL DEFAULT FALSE,
    conflict_note     TEXT,
    due_at            TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    escalated_at      TIMESTAMPTZ,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workforce_tasks_org_status ON workforce_tasks(org_id, status, due_at);
CREATE INDEX IF NOT EXISTS idx_workforce_tasks_domain     ON workforce_tasks(org_id, domain);

-- SubTask + Progress% (AI Agent Platform Phase 4 -- Task Execution Engine).
-- Sengaja TIDAK ada cascade/rollup otomatis (progress_pct parent tidak
-- dihitung ulang dari subtask, status 'completed' tidak mensyaratkan 100%)
-- -- murni field deklaratif untuk fase ini, bukan otomasi penuh.
ALTER TABLE workforce_tasks
    ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES workforce_tasks(id) ON DELETE SET NULL;
ALTER TABLE workforce_tasks
    ADD COLUMN IF NOT EXISTS progress_pct INT NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100);
CREATE INDEX IF NOT EXISTS idx_workforce_tasks_parent ON workforce_tasks(parent_task_id);

-- ============================================================
-- 10h. SELF LEARNING COMPANY (AI Workforce Phase 8)
-- ============================================================
-- Insight terdistilasi dari conversations/sales/complaints/outcomes --
-- BUKAN duplikat ai_improvement_recommendations (yang fokus ke masalah/
-- gap), melainkan pola yang TERBUKTI BERHASIL (sales pattern, resolusi
-- komplain, pendekatan sukses). Hanya insight berstatus 'approved' yang
-- disuntikkan balik ke system prompt chat (lihat
-- self_learning_engine.py::build_organizational_learning_context) --
-- butuh review manusia dulu sebelum memengaruhi jawaban bot ke pelanggan.
CREATE TABLE IF NOT EXISTS organizational_memory (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id           UUID REFERENCES bots(id) ON DELETE SET NULL,   -- NULL = berlaku org-wide
    category         TEXT NOT NULL CHECK (category IN ('sales_pattern','complaint_resolution','successful_approach')),
    insight          TEXT NOT NULL,
    evidence         JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurrence_count INT NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','approved','rejected','archived')),
    reviewed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at      TIMESTAMPTZ,
    dedup_key        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, dedup_key)
);
CREATE INDEX IF NOT EXISTS idx_org_memory_org_status ON organizational_memory(org_id, status, category);

-- ============================================================
-- 10i. COMPUTER AGENT (AI Agent Platform Phase 3)
-- ============================================================
-- Browser automation tasks (navigate/read/screenshot/click/fill/submit) yang
-- dipicu dari chat (publik maupun tenant) atau endpoint internal. Aksi
-- baca-saja (read) auto-execute dan tetap tercatat di sini untuk audit trail;
-- aksi tulis (write: click/fill/submit) WAJIB approval manusia sebelum
-- dieksekusi (requires_approval/approved_by/approved_at), mirror pola
-- workforce_tasks tapi tabel terpisah karena bentuk datanya beda
-- (target_url/plan/result), bukan menumpangi domain CHECK constraint
-- workforce_tasks yang sudah dipakai 6 agent lain.
CREATE TABLE IF NOT EXISTS computer_agent_tasks (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id            UUID REFERENCES bots(id) ON DELETE SET NULL,
    conversation_id   UUID,
    goal              TEXT NOT NULL,
    action_type       TEXT NOT NULL CHECK (action_type IN ('read','write')),
    status            TEXT NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('completed','pending_approval','approved','rejected','failed')),
    target_url        TEXT,
    plan              JSONB NOT NULL DEFAULT '[]'::jsonb,
    result            JSONB,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at       TIMESTAMPTZ,
    rejected_reason   TEXT,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_computer_agent_tasks_org_status ON computer_agent_tasks(org_id, status);

-- ============================================================
-- 10j. AGENT TASK EXECUTIONS (AI Workforce Phase 2 -- Task Engine)
-- ============================================================
-- Log Goal->Plan->Subtasks->Tool Selection->Execution->Verification->Report
-- (task_engine.run_agent_task()) untuk SETIAP digital employee yang
-- menjalankan goal bebas (bukan single-intent seperti
-- finance_agent.parse_intent() dkk, yang TETAP tidak berubah/tidak
-- menulis ke tabel ini). Cabang ke-5 di VIEW agent_execution_log di bawah.
CREATE TABLE IF NOT EXISTS agent_task_executions (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id        UUID REFERENCES bots(id) ON DELETE SET NULL,
    agent_name    TEXT NOT NULL,
    goal          TEXT NOT NULL,
    plan          JSONB NOT NULL DEFAULT '{}'::jsonb,
    tool_calls    JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification  JSONB,
    report        TEXT,
    status        TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_task_executions_org ON agent_task_executions(org_id, created_at DESC);

-- ============================================================
-- 10k2. CHANNEL MESSAGE TASKS (Tool Framework Phase 7)
-- ============================================================
-- Satu-satunya tool di tool_executor.py yang WRITE (kirim pesan nyata ke
-- pelanggan asli via WhatsApp/Telegram/Instagram/Facebook) -- semua tool
-- lain di Tool Framework read/generate-only. Mengikuti pola persis
-- computer_agent_tasks: agent TIDAK PERNAH mengirim langsung, hanya
-- membuat baris berstatus 'pending_approval' lewat tool_executor.py;
-- pengiriman SUNGGUHAN (lewat ChannelManager.send_message()) hanya
-- terjadi di channel_messaging.approve_task() setelah manusia menyetujui.
-- Tabel terpisah dari computer_agent_tasks karena bentuk datanya beda
-- (channel/recipient/message, bukan target_url/plan). Didefinisikan di
-- sini (sebelum VIEW 10k di bawah) supaya VIEW-nya bisa langsung
-- menyertakan tabel ini sebagai cabang ke-6.
CREATE TABLE IF NOT EXISTS channel_message_tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id          UUID REFERENCES bots(id) ON DELETE SET NULL,
    agent_name      TEXT NOT NULL,
    channel         TEXT NOT NULL CHECK (channel IN ('whatsapp','telegram','instagram','facebook')),
    recipient       TEXT NOT NULL,
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval','sent','failed','rejected')),
    result          JSONB,
    rejected_reason TEXT,
    approved_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_channel_message_tasks_org_status ON channel_message_tasks(org_id, status);

-- Action executions are referenced by agent_execution_log below. Keep this
-- definition before the view so fresh/partial databases can migrate cleanly.
CREATE TABLE IF NOT EXISTS agent_action_executions (
    id            TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    org_id        UUID NOT NULL,
    bot_id        UUID,
    goal          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'completed',
    plan          JSONB NOT NULL DEFAULT '[]',
    observations  JSONB NOT NULL DEFAULT '[]',
    verification  JSONB NOT NULL DEFAULT '{}',
    summary       TEXT,
    duration_ms   INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_action_exec_org
    ON agent_action_executions(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_action_exec_status
    ON agent_action_executions(org_id, status, created_at DESC);

-- ============================================================
-- 10k. UNIFIED EXECUTION LOG (AI Agent Platform Phase 4 + Tool Framework Phase 7)
-- ============================================================
-- Enam sistem task/eksekusi di platform ini (agent_executions untuk
-- pipeline chat, workforce_tasks untuk AI Workforce, computer_agent_tasks
-- untuk browser automation, workflow_executions untuk Workflow Builder,
-- agent_task_executions untuk Task Engine §10j, channel_message_tasks
-- untuk Tool Framework Phase 7 §10k2) masing-masing punya tabel sendiri
-- dan TIDAK pernah disatukan jadi satu permukaan query. View ini MURNI
-- membaca (UNION ALL) ke-6 sumber yang sudah ada -- tidak ada write-path
-- baru di view ini, tidak ada perubahan ke
-- agent_observability.py/workflow_engine.py/computer_agent.py. Fondasi untuk
-- Agent Center dashboard (Fase 5).
CREATE OR REPLACE VIEW agent_execution_log AS
SELECT
    'chat_agent'::text     AS source_type,
    ae.id                  AS source_id,
    ae.tenant_id            AS org_id,
    ae.agent_name           AS label,
    ae.status               AS status,
    ae.execution_start      AS started_at,
    ae.execution_end        AS finished_at,
    ae.metadata             AS detail
FROM agent_executions ae
UNION ALL
SELECT
    'workforce_task',
    wt.id,
    wt.org_id,
    wt.title,
    wt.status,
    wt.created_at,
    COALESCE(wt.completed_at, wt.escalated_at),
    jsonb_build_object('domain', wt.domain, 'priority', wt.priority, 'progress_pct', wt.progress_pct)
FROM workforce_tasks wt
UNION ALL
SELECT
    'computer_agent',
    cat.id,
    cat.org_id,
    cat.goal,
    cat.status,
    cat.created_at,
    cat.updated_at,
    cat.result
FROM computer_agent_tasks cat
UNION ALL
SELECT
    'workflow',
    we.id,
    we.org_id,
    we.trigger_type,
    we.status,
    we.started_at,
    we.finished_at,
    we.trigger_payload
FROM workflow_executions we
UNION ALL
SELECT
    'agent_task',
    ate.id,
    ate.org_id,
    ate.agent_name,
    ate.status,
    ate.created_at,
    ate.created_at,
    jsonb_build_object('goal', ate.goal, 'report', ate.report, 'tool_call_count', jsonb_array_length(ate.tool_calls))
FROM agent_task_executions ate
UNION ALL
SELECT
    'channel_message',
    cmt.id,
    cmt.org_id,
    cmt.agent_name,
    cmt.status,
    cmt.created_at,
    cmt.updated_at,
    jsonb_build_object('channel', cmt.channel, 'recipient', cmt.recipient, 'result', cmt.result)
FROM channel_message_tasks cmt
UNION ALL
SELECT
    'action_execution',
    aae.id::uuid,
    aae.org_id,
    aae.goal,
    aae.status,
    aae.created_at,
    aae.created_at,
    jsonb_build_object('summary', aae.summary, 'duration_ms', aae.duration_ms,
                       'step_count', jsonb_array_length(aae.plan))
FROM agent_action_executions aae;

-- ============================================================
-- 11. SEED DATA — plans, permissions, roles, marketplace templates
-- ============================================================

INSERT INTO plans (key, name, price_monthly_idr, price_yearly_idr,
                   max_conversations_per_month, max_agents, max_users,
                   max_knowledge_docs, max_channels, features, sort_order)
VALUES
 ('free',       'Free',       0,      0,        100,   1,  1,  3,  1,
  '{"description": "Cocok untuk mencoba BotNesia dan UMKM yang baru mulai.", "highlights": ["1 AI Agent", "100 percakapan/bulan", "Branding BotNesia"], "branding_botnesia": true, "knowledge_base": false, "analytics": false, "analytics_advanced": false, "whatsapp": false, "multi_user": false, "api_access": false, "priority_support": false, "multi_tenant": false, "white_label": false, "custom_pricing": false}', 0),
 ('starter',    'Starter',    99000,   990000,   1000,  2,  3,  10, 2,
  '{"description": "Untuk bisnis kecil yang mulai serius pakai AI chatbot.", "highlights": ["2 AI Agents", "1.000 percakapan/bulan", "Knowledge Base dasar", "Analytics dasar"], "branding_botnesia": false, "knowledge_base": true, "analytics": true, "analytics_advanced": false, "whatsapp": false, "multi_user": false, "api_access": false, "priority_support": false, "multi_tenant": false, "white_label": false, "custom_pricing": false}', 1),
 ('pro',        'Pro',        349000,  3490000,  5000,  5,  10, 50, 4,
  '{"description": "Untuk bisnis yang siap terhubung ke WhatsApp dengan tim lebih besar.", "highlights": ["5 AI Agents", "5.000 percakapan/bulan", "WhatsApp integration", "Analytics lengkap", "Multi-user"], "branding_botnesia": false, "knowledge_base": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "multi_user": true, "api_access": false, "priority_support": false, "multi_tenant": false, "white_label": false, "custom_pricing": false}', 2),
 ('business',   'Business',   990000,  9900000,  16500, 10, 20, 200, 8,
  '{"description": "Untuk UMKM, startup, dan tim kecil-menengah yang butuh kapasitas lebih besar.", "highlights": ["10 AI Agents", "16.500 percakapan/bulan", "WhatsApp Multi Number", "Advanced Analytics", "Team Management", "Priority Support", "Knowledge Base lebih besar"], "branding_botnesia": false, "knowledge_base": true, "knowledge_base_large": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "whatsapp_multi_number": true, "multi_user": true, "team_management": true, "priority_support": true, "api_access": false, "multi_tenant": false, "white_label": false, "custom_domain": false, "dedicated_support": false, "custom_integration": false, "sla": false, "advanced_security": false, "audit_log": false, "sso": false, "custom_pricing": false}', 3),
 ('enterprise', 'Enterprise', 4000000, 40000000, 100000, -1, -1, -1, -1,
  '{"description": "Untuk perusahaan besar, agency, SaaS multi-cabang, dan white label reseller.", "highlights": ["Unlimited AI Agents", "100.000+ percakapan/bulan", "Multi Tenant", "White Label", "API Access", "Custom Domain", "Dedicated Support", "Custom Integration", "SLA Perusahaan", "Advanced Security", "Audit Log", "SSO (Single Sign-On)"], "branding_botnesia": false, "knowledge_base": true, "knowledge_base_large": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "whatsapp_multi_number": true, "multi_user": true, "team_management": true, "priority_support": true, "api_access": true, "multi_tenant": true, "white_label": true, "custom_domain": true, "dedicated_support": true, "custom_integration": true, "sla": true, "advanced_security": true, "audit_log": true, "sso": true, "custom_pricing": true}', 4)
ON CONFLICT (key) DO NOTHING;

-- Kuota image generation per paket (UPDATE terpisah karena ON CONFLICT DO NOTHING
-- di atas tidak menyentuh baris yang sudah ada dari migrasi sebelumnya).
UPDATE plans SET max_image_generations_per_month = 10  WHERE key = 'free';
UPDATE plans SET max_image_generations_per_month = 50  WHERE key = 'starter';
UPDATE plans SET max_image_generations_per_month = 200 WHERE key = 'pro';
UPDATE plans SET max_image_generations_per_month = 500 WHERE key = 'business';
UPDATE plans SET max_image_generations_per_month = -1  WHERE key = 'enterprise';

-- Free trial eligibility (1 bulan gratis untuk paket berbayar non-Enterprise)
UPDATE plans SET free_trial_eligible = FALSE WHERE key = 'free';
UPDATE plans SET free_trial_eligible = TRUE  WHERE key = 'starter';
UPDATE plans SET free_trial_eligible = TRUE  WHERE key = 'pro';
UPDATE plans SET free_trial_eligible = TRUE  WHERE key = 'business';
UPDATE plans SET free_trial_eligible = FALSE WHERE key = 'enterprise';

-- P0-2: kurva harga monoton (idempoten; menimpa baris lama krn INSERT di atas
-- ON CONFLICT DO NOTHING). Rp/percakapan HARUS turun tiap naik paket:
--   Starter 99.000/1.000 = Rp99  >  Pro 349.000/5.000 = Rp69,8  >  Business 990.000/16.500 = Rp60
-- Sebelumnya Business (999.000/10.000 = Rp99,9) LEBIH mahal/percakapan dari Pro
-- (Rp59,8) -> upgrade tidak masuk akal. Pro dinaikkan sedikit utk spasi bersih;
-- Business ~harga sama tapi +65% kuota shg jadi value/rupiah terbaik.
UPDATE plans SET price_monthly_idr = 349000, price_yearly_idr = 3490000 WHERE key = 'pro';
UPDATE plans SET price_monthly_idr = 990000, price_yearly_idr = 9900000,
                 max_conversations_per_month = 16500 WHERE key = 'business';
-- Sinkronkan teks highlight yang ditampilkan (frontend membaca features.highlights).
UPDATE plans SET features = replace(features::text, '10.000 percakapan/bulan', '16.500 percakapan/bulan')::jsonb
 WHERE key = 'business' AND features::text LIKE '%10.000 percakapan/bulan%';

-- P0-4: lantai harga Enterprise + kuota percakapan FINITE (idempoten).
-- Sebelumnya 0/0 & max_conversations=-1 (unlimited) -> satu tenant bisa pakai
-- percakapan tak terbatas tanpa bayar. Beri lantai Rp4.000.000/bln (anchor;
-- tetap custom_pricing=Hubungi Sales) dan ceiling 100.000 conv/bln (deal nyata
-- dinegosiasikan lebih tinggi lewat sales). Dimensi lain tetap -1 (unlimited)
-- karena bukan biaya linear seperti percakapan. Rp/conv = 40 < Business Rp60 ✓.
UPDATE plans SET price_monthly_idr = 4000000, price_yearly_idr = 40000000,
                 max_conversations_per_month = 100000 WHERE key = 'enterprise';
UPDATE plans SET features = replace(features::text, 'Unlimited Conversations', '100.000+ percakapan/bulan')::jsonb
 WHERE key = 'enterprise' AND features::text LIKE '%Unlimited Conversations%';

-- Katalog permission (dipakai bn_platform/rbac.py — harus sinkron dgn PERMISSIONS const)
INSERT INTO permissions (key, category, description) VALUES
 ('bots.read',          'bots',          'Melihat daftar & konfigurasi bot'),
 ('bots.write',         'bots',          'Membuat & mengubah bot'),
 ('bots.delete',        'bots',          'Menghapus bot'),
 ('conversations.read', 'conversations', 'Melihat percakapan & inbox'),
 ('conversations.reply','conversations', 'Membalas percakapan (human handoff)'),
 ('conversations.assign','conversations','Menugaskan percakapan ke agent lain'),
 ('knowledge.read',     'knowledge',     'Melihat dokumen knowledge base'),
 ('knowledge.write',    'knowledge',     'Mengunggah/menghapus dokumen knowledge base'),
 ('analytics.read',     'analytics',     'Melihat dashboard analitik & laporan'),
 ('billing.read',       'billing',       'Melihat invoice, riwayat pembayaran, status langganan'),
 ('billing.manage',     'billing',       'Mengubah paket langganan & metode pembayaran'),
 ('team.read',          'team',          'Melihat anggota tim & role'),
 ('team.manage',        'team',          'Mengundang, menghapus, mengubah role anggota tim'),
 ('settings.manage',    'settings',      'Mengubah pengaturan organisasi, channel, integrasi'),
 ('apikeys.manage',     'settings',      'Membuat & mencabut API key'),
 ('audit.read',         'security',      'Melihat audit log'),
 ('marketplace.install','settings',      'Memasang template dari marketplace'),
 ('marketplace.publish','settings',      'Membuat, mengubah, dan mem-publish template agent sendiri ke marketplace'),
 ('finance.read',       'finance',       'Melihat invoice, expense, dan laporan keuangan tenant'),
 ('finance.write',      'finance',       'Membuat/mengubah invoice, expense, dan pembayaran tenant'),
 ('finance.approve',    'finance',       'Menyetujui/menolak expense dan keputusan keuangan penting'),
 ('marketing.read',     'marketing',     'Melihat campaign, konten, kalender, dan analitik marketing'),
 ('marketing.write',    'marketing',     'Membuat/mengubah campaign, konten, dan menjadwalkan publikasi'),
 ('marketing.approve',  'marketing',     'Menyetujui konten sebelum dipublikasikan'),
 ('hr.read',            'hr',            'Melihat data kandidat, karyawan, evaluasi, dan training'),
 ('hr.write',           'hr',            'Membuat/mengubah kandidat, karyawan, dan rencana training'),
 ('hr.approve',         'hr',            'Menyetujui (finalisasi) evaluasi karyawan'),
 ('operations.read',    'operations',    'Melihat health score, alert, dan laporan operasional'),
 ('operations.write',   'operations',    'Menjalankan scan operasional dan menindaklanjuti alert'),
 ('security.read',      'security',      'Melihat risk level, security alert, dan laporan keamanan'),
 ('security.write',     'security',      'Menjalankan security scan dan menindaklanjuti security alert'),
 ('executive.read',     'executive',     'Melihat company health score dan executive brief'),
 ('executive.write',    'executive',     'Membuat executive brief (sintesis lintas-agent)'),
 ('workforce.read',     'workforce',     'Melihat task koordinasi lintas-agent AI Workforce'),
 ('workforce.write',    'workforce',     'Membuat/mengubah task koordinasi lintas-agent'),
 ('workforce.approve',  'workforce',     'Menyetujui task yang butuh human approval'),
 ('learning.read',      'learning',      'Melihat insight organizational memory (Self-Learning Company)'),
 ('learning.write',     'learning',      'Menjalankan learning scan (membuat insight kandidat)'),
 ('learning.approve',   'learning',      'Menyetujui/menolak insight yang akan memengaruhi jawaban bot'),
 ('research.read',      'research',      'Menjalankan riset web/lead discovery (Research Agent)'),
 ('computer_agent.read',    'computer_agent', 'Melihat riwayat/status task Computer Agent (browser automation)'),
 ('computer_agent.write',   'computer_agent', 'Memicu task Computer Agent baca-saja secara manual'),
 ('computer_agent.approve', 'computer_agent', 'Menyetujui/menolak aksi tulis (klik/isi form/submit) Computer Agent'),
 ('execution_log.read',     'execution_log',  'Melihat log eksekusi terpadu lintas-sistem (chat agent, AI Workforce, Computer Agent, Workflow Builder)'),
 ('channel_messaging.read',    'channel_messaging', 'Melihat riwayat/status pesan keluar yang dibuat agent lewat Tool Framework'),
 ('channel_messaging.approve', 'channel_messaging', 'Menyetujui/menolak pengiriman pesan keluar (WhatsApp/Telegram/Instagram/Facebook) yang dibuat agent'),
 ('terminal.read',    'terminal', 'Melihat riwayat eksekusi terminal dan audit log'),
 ('terminal.execute', 'terminal', 'Menjalankan perintah shell/terminal melalui agent'),
 ('terminal.approve', 'terminal', 'Menyetujui/menolak perintah terminal berbahaya'),
 ('sandbox.manage',   'sandbox',  'Membuat dan mengelola sandbox session terisolasi'),
 ('action_executor.read',    'action_executor', 'Melihat riwayat eksekusi goal agent (Action Executor)'),
 ('action_executor.execute', 'action_executor', 'Menjalankan goal multi-langkah via Action Executor pipeline'),
 ('permission_grants.manage', 'permission_grants', 'Mengelola grant izin aksi agent (permit/deny per-permission)'),
 ('local_agent.manage',  'local_agent', 'Install, hubungkan, dan putus BotNesia Local Agent di komputer user'),
 ('local_agent.execute', 'local_agent', 'Kirim perintah ke Local Agent (akses file, terminal, browser lokal)'),
 ('local_agent.read',    'local_agent', 'Lihat riwayat perintah Local Agent')
ON CONFLICT (key) DO NOTHING;

-- 5 Role sistem baku (org_id NULL ⇒ template, di-clone otomatis ke setiap
-- tenant baru oleh bn_platform/rbac.py::ensure_default_roles()).
INSERT INTO roles (org_id, key, name, description, is_system) VALUES
 (NULL, 'owner',   'Owner',   'Akses penuh, termasuk billing & menghapus organisasi', TRUE),
 (NULL, 'admin',   'Admin',   'Mengelola bot, tim, knowledge, & pengaturan (tanpa billing)', TRUE),
 (NULL, 'manager', 'Manager', 'Mengelola percakapan, inbox, & melihat analitik', TRUE),
 (NULL, 'agent',   'Agent',   'Membalas percakapan yang ditugaskan (human handoff)', TRUE),
 (NULL, 'viewer',  'Viewer',  'Akses lihat-saja ke dashboard & laporan', TRUE)
ON CONFLICT (key) WHERE org_id IS NULL DO NOTHING;

-- Pemetaan role sistem -> permission (least-privilege per level)
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'owner'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'admin'
  AND p.key NOT IN ('billing.manage', 'bots.delete')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'manager'
  AND p.key IN ('bots.read', 'conversations.read', 'conversations.reply',
                'conversations.assign', 'knowledge.read', 'analytics.read',
                'team.read', 'billing.read', 'finance.read', 'finance.write',
                'marketing.read', 'marketing.write', 'hr.read', 'hr.write',
                'operations.read', 'operations.write', 'workforce.read', 'workforce.write',
                'learning.read', 'learning.write', 'research.read',
                'computer_agent.read', 'computer_agent.write', 'execution_log.read',
                'channel_messaging.read',
                'terminal.read', 'terminal.execute',
                'sandbox.manage',
                'action_executor.read', 'action_executor.execute',
                'permission_grants.manage',
                'local_agent.manage', 'local_agent.execute', 'local_agent.read')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'agent'
  AND p.key IN ('bots.read', 'conversations.read', 'conversations.reply', 'knowledge.read')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'viewer'
  AND p.key IN ('bots.read', 'conversations.read', 'analytics.read', 'knowledge.read', 'finance.read', 'marketing.read', 'operations.read', 'workforce.read', 'learning.read', 'research.read', 'terminal.read', 'action_executor.read')
ON CONFLICT DO NOTHING;

-- 6 Template Marketplace (instal 1-klik -> membuat bot baru terisi konfigurasi & FAQ awal)
INSERT INTO marketplace_templates (key, category, name, description, system_prompt, greeting, primary_color, sample_faqs, version) VALUES
 ('customer-service', 'Business', 'Customer Service Agent',
  'Agent layanan pelanggan untuk menjawab pertanyaan umum, komplain, dan status permintaan.',
  'Kamu adalah customer service agent yang sopan, cepat, dan solutif. Jawab pertanyaan umum, bantu komplain, jelaskan status layanan, dan selalu arahkan ke langkah berikutnya yang jelas.',
  'Halo! Saya siap membantu pertanyaan atau kendala pelanggan Anda.', '#2563EB',
  '[{"question":"Bagaimana cara menghubungi support?","answer":"Anda bisa menghubungi support melalui chat ini dan menyertakan nomor pesanan atau detail akun agar kami bisa membantu lebih cepat."},
    {"question":"Berapa lama proses balasan?","answer":"Balasan awal biasanya kami kirim secepat mungkin, lalu kami lanjutkan sesuai kompleksitas kasusnya."},
    {"question":"Apa yang harus disiapkan saat komplain?","answer":"Sertakan nomor pesanan, kronologi singkat, dan foto atau tangkapan layar jika relevan."}]', '1.0.0'),

 ('sales', 'Business', 'Sales Agent',
  'Agent penjualan untuk menangkap prospek, menjelaskan manfaat produk, dan mendorong konversi.',
  'Kamu adalah sales agent yang persuasif namun tidak memaksa. Pahami kebutuhan prospek, cocokkan solusi, dan arahkan ke tindakan pembelian atau follow-up yang jelas.',
  'Halo! Saya bisa bantu cari solusi yang paling cocok untuk kebutuhan Anda.', '#7C3AED',
  '[{"question":"Apa keunggulan produk ini?","answer":"Keunggulan utamanya ada pada kemudahan penggunaan, dukungan tim, dan hasil yang cepat terlihat untuk bisnis."},
    {"question":"Apakah ada demo?","answer":"Ya, kami bisa jadwalkan demo singkat agar Anda bisa melihat alur kerja dan fiturnya secara langsung."},
    {"question":"Bagaimana proses pembeliannya?","answer":"Setelah kebutuhan Anda jelas, kami bantu pilih paket yang sesuai lalu lanjut ke pembayaran dan aktivasi."}]', '1.0.0'),

 ('faq', 'Business', 'FAQ Agent',
  'Agent tanya jawab generik untuk basis pertanyaan yang paling sering muncul.',
  'Kamu adalah FAQ agent yang ringkas, akurat, dan to the point. Jawab hanya berdasarkan informasi yang tersedia, dan jika belum yakin, minta klarifikasi atau arahkan ke human handoff.',
  'Halo! Kirim pertanyaan Anda, saya bantu jawab sejelas mungkin.', '#0F766E',
  '[{"question":"Apa jam layanan?","answer":"Jam layanan mengikuti konfigurasi tenant. Jika belum ditentukan, silakan cek pengumuman resmi atau hubungi support."},
    {"question":"Di mana saya bisa membaca panduan?","answer":"Panduan biasanya tersedia di knowledge base atau pusat bantuan tenant."},
    {"question":"Bagaimana jika jawabannya belum ada?","answer":"Saya akan meneruskan ke tim terkait atau meminta manusia membantu jika konteksnya belum lengkap."}]', '1.0.0'),

 ('school', 'Education', 'School Agent',
  'Agent sekolah untuk pendaftaran siswa, informasi akademik, dan komunikasi orang tua.',
  'Kamu adalah admin sekolah yang ramah dan informatif. Jelaskan program, pendaftaran, biaya, jadwal akademik, dan bantu orang tua atau siswa mendapatkan informasi yang mereka butuhkan.',
  'Halo! Ada informasi sekolah yang bisa saya bantu?', '#D97706',
  '[{"question":"Bagaimana cara mendaftar?","answer":"Silakan siapkan data siswa, dokumen pendukung, dan jenjang yang dituju. Kami bantu proses pendaftarannya."},
    {"question":"Apakah ada info biaya?","answer":"Biaya tergantung jenjang dan program. Sebutkan kebutuhan Anda agar kami berikan rincian yang sesuai."},
    {"question":"Kapan jadwal kegiatan sekolah?","answer":"Jadwal kegiatan akan kami informasikan sesuai kalender akademik yang berlaku."}]', '1.0.0'),

 ('clinic', 'Healthcare', 'Clinic Agent',
  'Agent klinik untuk jadwal dokter, booking janji temu, dan pertanyaan layanan kesehatan non-darurat.',
  'Kamu adalah asisten klinik yang sopan dan empatik. Bantu pasien menjadwalkan janji temu, menjelaskan layanan, dan mengarahkan kasus serius ke penanganan medis yang sesuai.',
  'Halo! Saya bantu untuk jadwal dan layanan klinik.', '#10B981',
  '[{"question":"Bagaimana booking dokter?","answer":"Sebutkan poli atau dokter yang dituju serta tanggal yang diinginkan agar kami cek jadwalnya."},
    {"question":"Apakah menerima asuransi?","answer":"Ketersediaan asuransi tergantung kebijakan klinik. Silakan sebutkan provider yang Anda gunakan."},
    {"question":"Apa layanan yang tersedia?","answer":"Layanan yang tersedia mengikuti cabang atau unit klinik yang terdaftar."}]', '1.0.0'),

 ('travel', 'Travel', 'Travel Agent',
  'Agent travel untuk rekomendasi paket wisata, itinerary, dan proses booking.',
  'Kamu adalah konsultan perjalanan yang membantu pelanggan memilih paket wisata, menjelaskan itinerary, harga, dan ketersediaan tanggal secara antusias dan jelas.',
  'Halo traveler! Mau liburan ke mana?', '#0EA5E9',
  '[{"question":"Apa saja paket yang tersedia?","answer":"Kami punya paket domestik dan internasional. Sebutkan destinasi atau budget Anda agar kami rekomendasikan opsi terbaik."},
    {"question":"Apakah harga sudah termasuk tiket?","answer":"Tergantung paketnya. Ada opsi land-only dan ada juga paket all-in."},
    {"question":"Bagaimana cara booking?","answer":"Setelah memilih paket, kami bantu lanjut ke data peserta dan pembayaran DP untuk mengunci tanggal."}]', '1.0.0'),

 ('property', 'Business', 'Property Agent',
  'Agent properti untuk listing, jadwal survei, dan simulasi pembelian atau sewa.',
  'Kamu adalah agen properti yang profesional dan persuasif. Bantu calon pembeli atau penyewa menemukan unit sesuai budget, lokasi, dan kebutuhan mereka.',
  'Halo! Sedang mencari rumah, apartemen, atau ruko?', '#F59E0B',
  '[{"question":"Apakah bisa KPR?","answer":"Bisa, kami bisa bantu simulasi KPR berdasarkan budget dan penghasilan Anda."},
    {"question":"Bagaimana jadwal survei?","answer":"Silakan beri tahu waktu luang dan lokasi yang diminati, kami bantu atur jadwal survei."},
    {"question":"Apakah harga bisa nego?","answer":"Untuk beberapa unit harga masih dapat dinegosiasikan sesuai persetujuan pemilik."}]', '1.0.0'),

 ('e-commerce', 'E-commerce', 'E-commerce Agent',
  'Agent e-commerce untuk pertanyaan produk, stok, ongkir, dan status pesanan.',
  'Kamu adalah asisten e-commerce yang ramah, cepat, dan persuasif. Bantu pelanggan menemukan produk, menjelaskan ongkir, metode pembayaran, dan status pesanan.',
  'Halo! Cari produk apa hari ini?', '#FF6B35',
  '[{"question":"Berapa lama pengiriman?","answer":"Pengiriman reguler biasanya 2-4 hari kerja dan ekspres 1-2 hari kerja tergantung lokasi."},
    {"question":"Apakah bisa COD?","answer":"Bisa untuk wilayah yang didukung kurir kami."},
    {"question":"Bagaimana cara retur barang?","answer":"Hubungi kami maksimal 2x24 jam setelah barang diterima dengan foto produk dan nomor pesanan."}]', '1.0.0')
ON CONFLICT (key) DO UPDATE SET
    category = EXCLUDED.category,
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    system_prompt = EXCLUDED.system_prompt,
    greeting = EXCLUDED.greeting,
    primary_color = EXCLUDED.primary_color,
    sample_faqs = EXCLUDED.sample_faqs,
    version = EXCLUDED.version,
    is_active = TRUE;

-- ============================================================
-- 12. TRIGGER updated_at untuk subscriptions
-- ============================================================

DROP TRIGGER IF EXISTS trg_subs_updated ON subscriptions;
CREATE TRIGGER trg_subs_updated BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- FEEDBACK LEARNING (per-answer feedback and actionable queue)
-- ============================================================
CREATE TABLE IF NOT EXISTS feedback_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE UNIQUE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    rating TEXT NOT NULL CHECK (rating IN ('helpful','not_helpful')),
    comment TEXT,
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback_learning_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE UNIQUE,
    feedback_id UUID REFERENCES feedback_records(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    failure_reason TEXT,
    action_type TEXT NOT NULL CHECK (action_type IN ('knowledge','prompt','workflow')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','resolved','dismissed')),
    occurrence_count INT NOT NULL DEFAULT 1,
    resolution_note TEXT,
    resolved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_tenant_created ON feedback_records(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback_records(tenant_id, rating, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_queue_status ON feedback_learning_queue(tenant_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_queue_action ON feedback_learning_queue(tenant_id, action_type, occurrence_count DESC);

-- ============================================================
-- AUTO KNOWLEDGE BUILDER (AI-generated FAQ/SOP/summary/quality)
-- ============================================================
ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS suggested_intents JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS kb_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS kb_error TEXT;

CREATE TABLE IF NOT EXISTS kb_generated_faqs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT,
    source TEXT NOT NULL DEFAULT 'ai',
    status TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','approved','rejected')),
    chunk_id UUID REFERENCES doc_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_generated_sops (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested','approved','rejected')),
    chunk_id UUID REFERENCES doc_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kb_quality_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    completeness_score INT NOT NULL DEFAULT 0,
    redundancy_score INT NOT NULL DEFAULT 0,
    coverage_score INT NOT NULL DEFAULT 0,
    overall_score INT NOT NULL DEFAULT 0,
    missing_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    duplicate_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_faqs_org ON kb_generated_faqs(org_id, bot_id, status);
CREATE INDEX IF NOT EXISTS idx_kb_faqs_document ON kb_generated_faqs(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_sops_org ON kb_generated_sops(org_id, bot_id, status);
CREATE INDEX IF NOT EXISTS idx_kb_sops_document ON kb_generated_sops(document_id);
CREATE INDEX IF NOT EXISTS idx_kb_quality_org ON kb_quality_reports(org_id, bot_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kb_quality_document ON kb_quality_reports(document_id, created_at DESC);


-- ============================================================
-- AI WORKFLOW BUILDER (visual automation: trigger -> condition
-- -> agent -> action -> notification, n8n/Zapier-style for AI agents)
-- ============================================================
CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','disabled')),
    trigger_type TEXT NOT NULL DEFAULT 'manual_trigger',
    nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
    edges JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    trigger_type TEXT NOT NULL,
    trigger_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed')),
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_ms INT
);

CREATE TABLE IF NOT EXISTS workflow_execution_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed','skipped')),
    attempt INT NOT NULL DEFAULT 1,
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_ms INT
);

CREATE INDEX IF NOT EXISTS idx_workflows_org ON workflows(org_id, bot_id, status);
CREATE INDEX IF NOT EXISTS idx_workflows_trigger ON workflows(org_id, trigger_type, status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_org ON workflow_executions(org_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_execution_steps_execution ON workflow_execution_steps(execution_id, started_at);


-- ============================================================
-- ENTERPRISE SECURITY PLATFORM
-- Session management (active sessions, revoke, suspicious login)
-- + API key rotation/expiration/usage tracking.
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    ip_address    TEXT,
    user_agent    TEXT,
    is_suspicious BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    revoked_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, revoked_at);
CREATE INDEX IF NOT EXISTS idx_sessions_org  ON sessions(org_id, revoked_at);

-- Rotasi & usage tracking untuk API key (POST /api-keys, /api/security/api-keys)
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS usage_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rotated_at  TIMESTAMPTZ;

-- ============================================================
-- AI IMPROVEMENT ENGINE — rekomendasi hasil deteksi otomatis
-- ============================================================
-- AI hanya mendeteksi & merekomendasikan (knowledge gap, prompt,
-- workflow, agent). Admin yang memutuskan via status (reviewed/applied/dismissed).
CREATE TABLE IF NOT EXISTS ai_improvement_recommendations (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id           UUID REFERENCES bots(id) ON DELETE SET NULL,
    category         TEXT NOT NULL CHECK (category IN ('knowledge_gap','prompt_improvement','workflow_improvement','agent_improvement')),
    severity         TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    title            TEXT NOT NULL,
    description      TEXT NOT NULL,
    evidence         JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurrence_count INT NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','reviewed','applied','dismissed')),
    resolution_note  TEXT,
    reviewed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at      TIMESTAMPTZ,
    dedup_key        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_air_org      ON ai_improvement_recommendations(org_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_air_category ON ai_improvement_recommendations(org_id, category, status);
CREATE INDEX IF NOT EXISTS idx_air_bot      ON ai_improvement_recommendations(bot_id);

-- Global Meta asset routing registry. A Page/Instagram asset can belong to one
-- active tenant route, preventing cross-tenant webhook delivery.
CREATE TABLE IF NOT EXISTS meta_asset_routes (
    channel_type  TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id        UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    connection_id UUID REFERENCES channel_connections(id) ON DELETE SET NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel_type, external_id)
);
CREATE INDEX IF NOT EXISTS idx_meta_asset_routes_org ON meta_asset_routes(org_id, channel_type);

-- ============================================================
-- 12. AI AGENT PLATFORM TABLES
--     agent_permission_grants, agent_audit_log,
--     agent_session_memory, agent_action_executions
-- ============================================================

-- 12a. Permission Grants — enterprise permission model
-- Allow Once / Allow Always / Deny per resource per org
CREATE TABLE IF NOT EXISTS agent_permission_grants (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    permission    TEXT NOT NULL,
    grant_mode    TEXT NOT NULL CHECK (grant_mode IN ('allow_once','allow_always','deny')),
    resource      TEXT NOT NULL DEFAULT '*',
    granted_by    TEXT NOT NULL DEFAULT 'user',
    context       TEXT,
    granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at       TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_permission_grants_org
    ON agent_permission_grants(org_id, permission, revoked_at);

-- 12b. Audit Log — semua aksi agent yang dijalankan
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id               UUID NOT NULL,
    agent_name           TEXT NOT NULL,
    action_type          TEXT NOT NULL,
    target               TEXT,
    status               TEXT NOT NULL DEFAULT 'completed',
    permission_grant_id  UUID,
    initiated_by         TEXT NOT NULL DEFAULT 'agent',
    approved_by          TEXT,
    metadata             JSONB DEFAULT '{}',
    error                TEXT,
    duration_ms          INT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_org
    ON agent_audit_log(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_type
    ON agent_audit_log(org_id, action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_log_status
    ON agent_audit_log(org_id, status, created_at DESC);

-- 12c. Agent Session Memory — per-session context memory
CREATE TABLE IF NOT EXISTS agent_session_memory (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL,
    session_id    TEXT NOT NULL DEFAULT 'default',
    memory_state  JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, session_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_session_memory_org
    ON agent_session_memory(org_id, updated_at DESC);

-- 12d. Action Executions — defined before agent_execution_log because the view reads it.

-- 12e. Seed permissions baru untuk AI Agent Platform
INSERT INTO permissions (key, category, description)
VALUES
  ('agent.read_files',    'agent_platform', 'Izin agent membaca file sistem'),
  ('agent.write_files',   'agent_platform', 'Izin agent menulis/mengedit file sistem'),
  ('agent.delete_files',  'agent_platform', 'Izin agent menghapus file sistem'),
  ('agent.run_terminal',  'agent_platform', 'Izin agent menjalankan command di terminal'),
  ('agent.browser_use',   'agent_platform', 'Izin agent mengakses browser (read-only)'),
  ('agent.browser_write', 'agent_platform', 'Izin agent melakukan aksi tulis di browser'),
  ('agent.audit_view',    'agent_platform', 'Melihat audit log aksi agent'),
  ('agent.permission_manage', 'agent_platform', 'Mengelola permission grant agent')
ON CONFLICT (key) DO NOTHING;
