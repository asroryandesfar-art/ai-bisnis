-- ============================================================
-- BotNesia — Database Schema
-- PostgreSQL 15+
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUM TYPES
-- ============================================================

DO $$ BEGIN
    CREATE TYPE plan_tier AS ENUM ('starter', 'growth', 'scale');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE bot_status AS ENUM ('active', 'inactive', 'training');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE msg_role AS ENUM ('user', 'assistant', 'system');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE doc_status AS ENUM ('pending', 'processing', 'ready', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE billing_status AS ENUM ('active', 'past_due', 'canceled', 'trialing');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- ORGANIZATIONS (unit billing utama — satu perusahaan klien)
-- ============================================================

CREATE TABLE IF NOT EXISTS organizations (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name           TEXT        NOT NULL,
    slug           TEXT        NOT NULL UNIQUE,   -- untuk subdomain/URL
    plan           plan_tier   NOT NULL DEFAULT 'starter',
    billing_status billing_status NOT NULL DEFAULT 'trialing',
    trial_ends_at  TIMESTAMPTZ,
    bot_limit      INT         NOT NULL DEFAULT 1,
    conv_limit     INT         NOT NULL DEFAULT 500,  -- percakapan/bulan
    doc_limit      INT         NOT NULL DEFAULT 10,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug);

-- ============================================================
-- USERS (anggota tim dalam organisasi)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT        NOT NULL UNIQUE,
    hashed_password TEXT        NOT NULL,
    full_name       TEXT,
    role            TEXT        NOT NULL DEFAULT 'member',  -- owner | admin | member
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_org  ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ============================================================
-- BOTS (setiap chatbot yang dibuat oleh klien)
-- ============================================================

CREATE TABLE IF NOT EXISTS bots (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id         UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name           TEXT        NOT NULL,
    status         bot_status  NOT NULL DEFAULT 'active',
    -- konfigurasi tampilan widget
    primary_color  TEXT        NOT NULL DEFAULT '#0066FF',
    position       TEXT        NOT NULL DEFAULT 'bottom-right',
    greeting       TEXT        NOT NULL DEFAULT 'Halo! Ada yang bisa saya bantu?',
    language       TEXT        NOT NULL DEFAULT 'id',
    -- konfigurasi AI
    system_prompt  TEXT,                         -- instruksi dasar kepribadian bot
    temperature    FLOAT       NOT NULL DEFAULT 0.3,
    -- stats cache (di-update tiap jam via cron)
    total_convs    INT         NOT NULL DEFAULT 0,
    total_msgs     INT         NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bots_org ON bots(org_id);

-- ============================================================
-- DOCUMENTS (file yang di-upload untuk RAG knowledge base)
-- ============================================================

CREATE TABLE IF NOT EXISTS documents (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id       UUID        REFERENCES bots(id) ON DELETE SET NULL,  -- NULL = shared semua bot
    filename     TEXT        NOT NULL,
    file_size    INT,         -- bytes
    mime_type    TEXT,
    status       doc_status  NOT NULL DEFAULT 'pending',
    chunk_count  INT         NOT NULL DEFAULT 0,
    error_msg    TEXT,        -- pesan error kalau processing gagal
    storage_path TEXT,        -- path di object storage (S3/R2)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_docs_org   ON documents(org_id);
CREATE INDEX IF NOT EXISTS idx_docs_bot   ON documents(bot_id);
CREATE INDEX IF NOT EXISTS idx_docs_status ON documents(status);

-- ============================================================
-- DOC CHUNKS (hasil chunking dokumen, disimpan paralel di Vector DB)
-- Tabel ini menyimpan metadata; embedding-nya di Pinecone/pgvector
-- ============================================================

CREATE TABLE IF NOT EXISTS doc_chunks (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    org_id       UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    chunk_index  INT         NOT NULL,
    content      TEXT        NOT NULL,  -- teks asli chunk
    token_count  INT,
    vector_id    TEXT,                  -- ID di Pinecone/pgvector
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON doc_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_org ON doc_chunks(org_id);

-- ============================================================
-- CONVERSATIONS (satu sesi chat antara end-user & bot)
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id          UUID        NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- data end-user (opsional, dikirim via ChatbotWidget.identify())
    end_user_id     TEXT,       -- ID dari sistem klien
    end_user_name   TEXT,
    end_user_email  TEXT,
    end_user_meta   JSONB,      -- data tambahan (plan, order_count, dll)
    -- stats
    msg_count       INT         NOT NULL DEFAULT 0,
    resolved        BOOLEAN     NOT NULL DEFAULT FALSE,
    handoff_needed  BOOLEAN     NOT NULL DEFAULT FALSE,  -- bot minta human agent
    rating          SMALLINT,   -- 1–5, diisi end-user setelah chat
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_msg_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_convs_bot    ON conversations(bot_id);
CREATE INDEX IF NOT EXISTS idx_convs_org    ON conversations(org_id);
CREATE INDEX IF NOT EXISTS idx_convs_started ON conversations(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_convs_user   ON conversations(end_user_id) WHERE end_user_id IS NOT NULL;

-- ============================================================
-- MESSAGES (setiap pesan dalam percakapan)
-- ============================================================

CREATE TABLE IF NOT EXISTS messages (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            msg_role    NOT NULL,
    content         TEXT        NOT NULL,
    -- metadata AI response
    model           TEXT,       -- model yang dipakai, misal 'claude-sonnet-4-6'
    input_tokens    INT,
    output_tokens   INT,
    latency_ms      INT,        -- waktu generate respons
    -- sumber knowledge yang dipakai (untuk RAG transparency)
    source_chunks   UUID[],     -- array of doc_chunk IDs
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_msgs_conv    ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msgs_created ON messages(created_at DESC);

-- ============================================================
-- API KEYS (untuk akses programatik — Scale tier)
-- ============================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,   -- label: "Production Key", "Dev Key"
    key_hash    TEXT        NOT NULL UNIQUE,  -- bcrypt hash dari key
    key_prefix  TEXT        NOT NULL,         -- "bn_live_xxxx" tampil di UI
    last_used_at TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_apikeys_org ON api_keys(org_id);

-- ============================================================
-- USAGE SNAPSHOTS (rekam penggunaan bulanan untuk billing)
-- ============================================================

CREATE TABLE IF NOT EXISTS usage_snapshots (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    period_start  DATE        NOT NULL,
    period_end    DATE        NOT NULL,
    conv_count    INT         NOT NULL DEFAULT 0,
    msg_count     INT         NOT NULL DEFAULT 0,
    token_in      BIGINT      NOT NULL DEFAULT 0,
    token_out     BIGINT      NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_usage_org ON usage_snapshots(org_id, period_start DESC);

-- ============================================================
-- WEBHOOK CONFIGS (untuk notifikasi ke sistem klien)
-- ============================================================

CREATE TABLE IF NOT EXISTS webhook_configs (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    url         TEXT        NOT NULL,
    secret      TEXT        NOT NULL,   -- untuk validasi HMAC signature
    events      TEXT[]      NOT NULL,   -- ['conversation.started', 'handoff.needed']
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- HELPER: auto-update updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_orgs_updated ON organizations;
CREATE TRIGGER trg_orgs_updated BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_bots_updated ON bots;
CREATE TRIGGER trg_bots_updated BEFORE UPDATE ON bots
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- VIEWS: ringkasan untuk dashboard
-- ============================================================

-- Stats per bot bulan ini
CREATE OR REPLACE VIEW bot_stats_current_month AS
SELECT
    b.id              AS bot_id,
    b.org_id,
    b.name            AS bot_name,
    COUNT(DISTINCT c.id)                                 AS conv_count,
    COUNT(m.id)                                          AS msg_count,
    ROUND(AVG(c.rating) FILTER (WHERE c.rating IS NOT NULL), 2) AS avg_rating,
    SUM(m.latency_ms) / NULLIF(COUNT(m.id), 0)          AS avg_latency_ms
FROM bots b
LEFT JOIN conversations c ON c.bot_id = b.id
    AND c.started_at >= DATE_TRUNC('month', NOW())
LEFT JOIN messages m ON m.conversation_id = c.id
    AND m.role = 'assistant'
GROUP BY b.id, b.org_id, b.name;

-- Top pertanyaan yang sering masuk (untuk analytics)
CREATE OR REPLACE VIEW top_user_messages AS
SELECT
    c.org_id,
    c.bot_id,
    m.content,
    COUNT(*) AS frequency
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.role = 'user'
    AND m.created_at >= NOW() - INTERVAL '30 days'
GROUP BY c.org_id, c.bot_id, m.content
ORDER BY frequency DESC;

-- ============================================================
-- AI OBSERVABILITY (request traces and per-agent lifecycle)
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_traces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_question TEXT NOT NULL,
    final_answer TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_ms INT,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trace_id UUID NOT NULL REFERENCES ai_traces(id) ON DELETE CASCADE,
    parent_execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    sequence_no INT NOT NULL DEFAULT 0,
    execution_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_end TIMESTAMPTZ,
    duration_ms INT,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    confidence_score NUMERIC(7,3),
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_traces_tenant_created ON ai_traces(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_traces_conversation ON ai_traces(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_exec_trace_sequence ON agent_executions(trace_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_agent_exec_tenant_created ON agent_executions(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_exec_agent_status ON agent_executions(agent_name, status, created_at DESC);

-- ============================================================
-- COST INTELLIGENCE (per-call AI provider cost ledger)
-- ============================================================
CREATE TABLE IF NOT EXISTS cost_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    trace_id UUID REFERENCES ai_traces(id) ON DELETE SET NULL,
    execution_id UUID REFERENCES agent_executions(id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    token_count INT NOT NULL DEFAULT 0,
    estimated_cost NUMERIC(18,8) NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    channel TEXT NOT NULL DEFAULT 'widget',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_cost_budgets (
    tenant_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    monthly_budget_usd NUMERIC(18,2) NOT NULL DEFAULT 0,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS routed_model TEXT;
ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS task_complexity TEXT;
ALTER TABLE ai_traces ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'widget';

CREATE INDEX IF NOT EXISTS idx_cost_records_tenant_created ON cost_records(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_records_conversation ON cost_records(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_records_agent ON cost_records(tenant_id, agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_records_model ON cost_records(tenant_id, model_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_records_channel ON cost_records(tenant_id, channel, created_at DESC);

-- HUMAN HANDOFF (extends the existing conversation lifecycle; no rebuild)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS human_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE UNIQUE,
    reason TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'waiting',
    assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT,
    sla_due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_handoff_org ON human_queue(org_id, status);
CREATE INDEX IF NOT EXISTS idx_handoff_assignee ON human_queue(assigned_agent_id) WHERE status = 'assigned';

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
-- AGENT MARKETPLACE (template catalog + tenant installs)
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
    primary_color TEXT NOT NULL DEFAULT '#0066FF',
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

CREATE OR REPLACE VIEW agent_templates AS
SELECT
    id,
    name,
    description,
    category,
    version,
    CASE WHEN is_active THEN 'active' ELSE 'inactive' END AS status
FROM marketplace_templates;

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
