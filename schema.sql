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

CREATE TYPE plan_tier      AS ENUM ('starter', 'growth', 'scale');
CREATE TYPE bot_status     AS ENUM ('active', 'inactive', 'training');
CREATE TYPE msg_role       AS ENUM ('user', 'assistant', 'system');
CREATE TYPE doc_status     AS ENUM ('pending', 'processing', 'ready', 'failed');
CREATE TYPE billing_status AS ENUM ('active', 'past_due', 'canceled', 'trialing');

-- ============================================================
-- ORGANIZATIONS (unit billing utama — satu perusahaan klien)
-- ============================================================

CREATE TABLE organizations (
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

CREATE INDEX idx_orgs_slug ON organizations(slug);

-- ============================================================
-- USERS (anggota tim dalam organisasi)
-- ============================================================

CREATE TABLE users (
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

CREATE INDEX idx_users_org  ON users(org_id);
CREATE INDEX idx_users_email ON users(email);

-- ============================================================
-- BOTS (setiap chatbot yang dibuat oleh klien)
-- ============================================================

CREATE TABLE bots (
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

CREATE INDEX idx_bots_org ON bots(org_id);

-- ============================================================
-- DOCUMENTS (file yang di-upload untuk RAG knowledge base)
-- ============================================================

CREATE TABLE documents (
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

CREATE INDEX idx_docs_org   ON documents(org_id);
CREATE INDEX idx_docs_bot   ON documents(bot_id);
CREATE INDEX idx_docs_status ON documents(status);

-- ============================================================
-- DOC CHUNKS (hasil chunking dokumen, disimpan paralel di Vector DB)
-- Tabel ini menyimpan metadata; embedding-nya di Pinecone/pgvector
-- ============================================================

CREATE TABLE doc_chunks (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    org_id       UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    chunk_index  INT         NOT NULL,
    content      TEXT        NOT NULL,  -- teks asli chunk
    token_count  INT,
    vector_id    TEXT,                  -- ID di Pinecone/pgvector
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_doc ON doc_chunks(document_id);
CREATE INDEX idx_chunks_org ON doc_chunks(org_id);

-- ============================================================
-- CONVERSATIONS (satu sesi chat antara end-user & bot)
-- ============================================================

CREATE TABLE conversations (
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

CREATE INDEX idx_convs_bot    ON conversations(bot_id);
CREATE INDEX idx_convs_org    ON conversations(org_id);
CREATE INDEX idx_convs_started ON conversations(started_at DESC);
CREATE INDEX idx_convs_user   ON conversations(end_user_id) WHERE end_user_id IS NOT NULL;

-- ============================================================
-- MESSAGES (setiap pesan dalam percakapan)
-- ============================================================

CREATE TABLE messages (
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

CREATE INDEX idx_msgs_conv    ON messages(conversation_id);
CREATE INDEX idx_msgs_created ON messages(created_at DESC);

-- ============================================================
-- API KEYS (untuk akses programatik — Scale tier)
-- ============================================================

CREATE TABLE api_keys (
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

CREATE INDEX idx_apikeys_org ON api_keys(org_id);

-- ============================================================
-- USAGE SNAPSHOTS (rekam penggunaan bulanan untuk billing)
-- ============================================================

CREATE TABLE usage_snapshots (
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

CREATE INDEX idx_usage_org ON usage_snapshots(org_id, period_start DESC);

-- ============================================================
-- WEBHOOK CONFIGS (untuk notifikasi ke sistem klien)
-- ============================================================

CREATE TABLE webhook_configs (
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

CREATE TRIGGER trg_orgs_updated BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_bots_updated BEFORE UPDATE ON bots
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- VIEWS: ringkasan untuk dashboard
-- ============================================================

-- Stats per bot bulan ini
CREATE VIEW bot_stats_current_month AS
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
CREATE VIEW top_user_messages AS
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
