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
    CREATE TYPE channel_type_t AS ENUM ('whatsapp', 'telegram', 'website', 'instagram', 'email', 'gmail');
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
CREATE INDEX IF NOT EXISTS idx_payhist_provtx  ON payment_history(provider, provider_transaction_id);

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
    key           TEXT NOT NULL UNIQUE,     -- 'toko-online' | 'travel' | 'klinik' | 'pesantren' | 'properti' | 'umkm'
    category      TEXT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    preview_image TEXT,
    system_prompt TEXT NOT NULL,
    greeting      TEXT NOT NULL,
    primary_color TEXT NOT NULL DEFAULT '#0066FF',
    sample_faqs   JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{"question":..,"answer":..}, ...]
    install_count INT NOT NULL DEFAULT 0,
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
 ('pro',        'Pro',        299000,  2990000,  5000,  5,  10, 50, 4,
  '{"description": "Untuk bisnis yang siap terhubung ke WhatsApp dengan tim lebih besar.", "highlights": ["5 AI Agents", "5.000 percakapan/bulan", "WhatsApp integration", "Analytics lengkap", "Multi-user"], "branding_botnesia": false, "knowledge_base": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "multi_user": true, "api_access": false, "priority_support": false, "multi_tenant": false, "white_label": false, "custom_pricing": false}', 2),
 ('business',   'Business',   999000,  9990000,  10000, 10, 20, 200, 8,
  '{"description": "Untuk UMKM, startup, dan tim kecil-menengah yang butuh kapasitas lebih besar.", "highlights": ["10 AI Agents", "10.000 percakapan/bulan", "WhatsApp Multi Number", "Advanced Analytics", "Team Management", "Priority Support", "Knowledge Base lebih besar"], "branding_botnesia": false, "knowledge_base": true, "knowledge_base_large": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "whatsapp_multi_number": true, "multi_user": true, "team_management": true, "priority_support": true, "api_access": false, "multi_tenant": false, "white_label": false, "custom_domain": false, "dedicated_support": false, "custom_integration": false, "sla": false, "advanced_security": false, "audit_log": false, "sso": false, "custom_pricing": false}', 3),
 ('enterprise', 'Enterprise', 0,       0,        -1,    -1, -1, -1, -1,
  '{"description": "Untuk perusahaan besar, agency, SaaS multi-cabang, dan white label reseller.", "highlights": ["Unlimited AI Agents", "Unlimited Conversations", "Multi Tenant", "White Label", "API Access", "Custom Domain", "Dedicated Support", "Custom Integration", "SLA Perusahaan", "Advanced Security", "Audit Log", "SSO (Single Sign-On)"], "branding_botnesia": false, "knowledge_base": true, "knowledge_base_large": true, "analytics": true, "analytics_advanced": true, "whatsapp": true, "whatsapp_multi_number": true, "multi_user": true, "team_management": true, "priority_support": true, "api_access": true, "multi_tenant": true, "white_label": true, "custom_domain": true, "dedicated_support": true, "custom_integration": true, "sla": true, "advanced_security": true, "audit_log": true, "sso": true, "custom_pricing": true}', 4)
ON CONFLICT (key) DO NOTHING;

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
 ('marketplace.install','settings',      'Memasang template dari marketplace')
ON CONFLICT (key) DO NOTHING;

-- 5 Role sistem baku (org_id NULL ⇒ template, di-clone otomatis ke setiap
-- tenant baru oleh bn_platform/rbac.py::ensure_default_roles()).
INSERT INTO roles (org_id, key, name, description, is_system) VALUES
 (NULL, 'owner',   'Owner',   'Akses penuh, termasuk billing & menghapus organisasi', TRUE),
 (NULL, 'admin',   'Admin',   'Mengelola bot, tim, knowledge, & pengaturan (tanpa billing)', TRUE),
 (NULL, 'manager', 'Manager', 'Mengelola percakapan, inbox, & melihat analitik', TRUE),
 (NULL, 'agent',   'Agent',   'Membalas percakapan yang ditugaskan (human handoff)', TRUE),
 (NULL, 'viewer',  'Viewer',  'Akses lihat-saja ke dashboard & laporan', TRUE)
ON CONFLICT (org_id, key) DO NOTHING;

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
                'team.read', 'billing.read')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'agent'
  AND p.key IN ('bots.read', 'conversations.read', 'conversations.reply', 'knowledge.read')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.org_id IS NULL AND r.key = 'viewer'
  AND p.key IN ('bots.read', 'conversations.read', 'analytics.read', 'knowledge.read')
ON CONFLICT DO NOTHING;

-- 6 Template Marketplace (instal 1-klik -> membuat bot baru terisi konfigurasi & FAQ awal)
INSERT INTO marketplace_templates (key, category, name, description, system_prompt, greeting, primary_color, sample_faqs) VALUES
 ('toko-online', 'E-Commerce', 'Toko Online',
  'Asisten penjualan untuk toko online: jawab pertanyaan produk, ongkir, status pesanan, dan dorong checkout.',
  'Kamu adalah asisten penjualan toko online yang ramah dan persuasif. Jawab pertanyaan produk, stok, harga, ongkos kirim, metode pembayaran, dan status pesanan. Selalu tawarkan rekomendasi produk relevan dan ajak pelanggan menyelesaikan pembelian.',
  'Halo! Selamat datang di toko kami 🛍️ Mau cari produk apa hari ini?', '#FF6B35',
  '[{"question":"Berapa lama pengiriman?","answer":"Pengiriman reguler 2-4 hari kerja, ekspres 1-2 hari kerja tergantung lokasi."},
    {"question":"Apakah bisa COD?","answer":"Bisa untuk wilayah yang didukung kurir kami, pilih metode COD saat checkout."},
    {"question":"Bagaimana cara retur barang?","answer":"Hubungi kami maksimal 2x24 jam setelah barang diterima dengan menyertakan foto produk dan nomor pesanan."}]'),

 ('travel', 'Travel & Pariwisata', 'Travel & Tour',
  'Asisten agen perjalanan: rekomendasi paket wisata, cek ketersediaan, dan bantu proses booking.',
  'Kamu adalah konsultan perjalanan yang membantu pelanggan memilih paket wisata, menjelaskan itinerary, harga, dan ketersediaan tanggal. Bersikap antusias, berikan rekomendasi sesuai budget & preferensi, dan arahkan ke proses booking.',
  'Halo traveler! ✈️ Mau liburan ke mana nih? Aku bantu carikan paket terbaik untukmu.', '#0EA5E9',
  '[{"question":"Apa saja paket yang tersedia?","answer":"Kami punya paket domestik dan internasional, mulai dari 3D2N hingga 7D6N. Sebutkan destinasi impianmu, nanti aku rekomendasikan!"},
    {"question":"Apakah harga sudah termasuk tiket pesawat?","answer":"Tergantung paket — ada yang land-only dan ada yang all-in termasuk tiket. Aku bisa cek detail sesuai paket yang kamu minati."},
    {"question":"Bagaimana cara booking?","answer":"Cukup pilih paket, isi data peserta, lalu lakukan pembayaran DP 30% untuk mengunci tanggal keberangkatan."}]'),

 ('klinik', 'Kesehatan', 'Klinik & Layanan Medis',
  'Asisten klinik: jadwal dokter, booking janji temu, info layanan, dan triase awal non-darurat.',
  'Kamu adalah asisten administrasi klinik yang sopan dan empatik. Bantu pasien menjadwalkan janji temu, memberi info jam praktik dokter, layanan yang tersedia, dan estimasi biaya. Untuk keluhan medis serius, sarankan segera ke IGD/hubungi dokter, jangan memberi diagnosis.',
  'Halo, selamat datang di klinik kami 🏥 Ada yang bisa kami bantu terkait jadwal atau layanan?', '#10B981',
  '[{"question":"Bagaimana cara booking janji temu dokter?","answer":"Sebutkan dokter/poli yang dituju serta tanggal yang diinginkan, kami bantu cek jadwal yang tersedia."},
    {"question":"Apa saja layanan yang tersedia?","answer":"Kami melayani pemeriksaan umum, gigi, laboratorium, dan konsultasi spesialis. Sebutkan kebutuhanmu untuk info lebih detail."},
    {"question":"Apakah menerima BPJS/asuransi?","answer":"Ya, kami bekerja sama dengan BPJS dan beberapa asuransi swasta. Mohon siapkan kartu/identitas saat kunjungan."}]'),

 ('pesantren', 'Pendidikan', 'Pesantren & Lembaga Pendidikan',
  'Asisten pendaftaran santri/siswa baru: info kurikulum, biaya, jadwal, dan proses pendaftaran.',
  'Kamu adalah admin pendaftaran pesantren/lembaga pendidikan yang ramah dan informatif. Jelaskan program, kurikulum, fasilitas, biaya pendaftaran & SPP, jadwal seleksi, dan bantu calon wali santri menyelesaikan pendaftaran.',
  'Assalamualaikum, selamat datang 🌙 Ada yang ingin ditanyakan seputar pendaftaran santri baru?', '#7C3AED',
  '[{"question":"Berapa biaya pendaftaran?","answer":"Biaya pendaftaran dan SPP bervariasi sesuai jenjang & program. Sebutkan jenjang yang dituju agar kami berikan rincian lengkap."},
    {"question":"Apa saja syarat pendaftaran?","answer":"Umumnya: fotokopi akta kelahiran, KK, ijazah/rapor terakhir, dan pas foto. Detail lengkap akan kami kirimkan sesuai jenjang."},
    {"question":"Kapan jadwal tes seleksi masuk?","answer":"Jadwal seleksi diumumkan tiap gelombang pendaftaran — beri tahu kami gelombang yang ingin diikuti untuk info tanggal pastinya."}]'),

 ('properti', 'Properti', 'Agen Properti',
  'Asisten agen properti: info listing, jadwal survei lokasi, simulasi KPR, dan follow-up calon pembeli/penyewa.',
  'Kamu adalah agen properti yang profesional dan persuasif. Bantu calon pembeli/penyewa menemukan unit sesuai budget & lokasi, jelaskan spesifikasi, harga, skema KPR/cicilan, dan tawarkan jadwal survei lokasi.',
  'Halo! 🏠 Sedang mencari rumah, apartemen, atau ruko? Ceritakan kriteria yang kamu inginkan.', '#F59E0B',
  '[{"question":"Apakah bisa KPR?","answer":"Bisa, kami bekerja sama dengan beberapa bank untuk simulasi KPR dengan DP ringan. Sebutkan budget & penghasilan agar bisa kami hitungkan estimasinya."},
    {"question":"Bagaimana jadwal survei lokasi?","answer":"Kami bisa atur jadwal survei sesuai waktu luangmu — sebutkan hari & lokasi yang diminati."},
    {"question":"Apakah harga bisa nego?","answer":"Untuk beberapa unit harga masih bisa dinegosiasikan, akan kami sampaikan ke pemilik/developer dan kabari hasilnya."}]'),

 ('umkm', 'UMKM', 'UMKM & Usaha Kecil',
  'Asisten serbaguna untuk UMKM: jawab pertanyaan produk/jasa, harga, pemesanan, dan jam operasional.',
  'Kamu adalah asisten ramah untuk usaha kecil menengah. Jawab pertanyaan seputar produk/jasa, harga, ketersediaan, cara pemesanan, jam operasional & lokasi usaha. Bersikap hangat seperti pemilik usaha yang melayani pelanggan langsung.',
  'Halo, terima kasih sudah menghubungi kami! 😊 Ada yang bisa dibantu hari ini?', '#EC4899',
  '[{"question":"Jam operasional buka jam berapa?","answer":"Kami buka setiap hari pukul 08.00–20.00 WIB, kecuali hari libur nasional."},
    {"question":"Bagaimana cara pesan?","answer":"Kamu bisa pesan langsung lewat chat ini — sebutkan produk/jasa yang diinginkan beserta jumlahnya, nanti kami bantu prosesnya."},
    {"question":"Apakah bisa custom/request khusus?","answer":"Bisa! Ceritakan kebutuhan khususmu, nanti kami infokan apakah bisa kami penuhi beserta estimasi harga & waktu pengerjaan."}]')
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- 12. TRIGGER updated_at untuk subscriptions
-- ============================================================

DROP TRIGGER IF EXISTS trg_subs_updated ON subscriptions;
CREATE TRIGGER trg_subs_updated BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
