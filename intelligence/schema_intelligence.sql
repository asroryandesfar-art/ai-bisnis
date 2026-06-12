-- ============================================================
-- BotNesia Intelligence Platform — Skema tambahan
-- PostgreSQL 15+ dengan ekstensi pgvector
--
-- Cara apply:
--   psql "$DATABASE_URL" -f schema.sql                       (sekali, sudah ada)
--   psql "$DATABASE_URL" -f intelligence/schema_intelligence.sql
--
-- Semua statement idempotent (CREATE ... IF NOT EXISTS) supaya
-- aman dijalankan berulang kali, mengikuti pola ensure_optional_schema()
-- di main.py.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;            -- pgvector

-- Dimensi embedding lokal (lihat intelligence/embeddings.py — hashing-trick 384-d).
-- Jika nanti ganti provider embedding (mis. OpenAI 1536-d / Cohere 1024-d),
-- buat kolom baru + index baru, JANGAN ubah kolom existing (data lama jadi tak valid).

-- ============================================================
-- ENUM TYPES (khusus modul intelligence)
-- ============================================================

DO $$ BEGIN
    CREATE TYPE lead_status_t AS ENUM ('none', 'cold', 'warm', 'hot', 'converted', 'lost');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE purchase_status_t AS ENUM ('none', 'considering', 'purchased', 'cancelled', 'refunded');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE escalation_status_t AS ENUM ('none', 'flagged', 'escalated', 'resolved');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE kg_node_type_t AS ENUM ('user', 'product', 'question', 'problem', 'solution', 'sale');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ============================================================
-- 1. CONVERSATION MEMORY
--    Hasil ekstraksi terstruktur per percakapan + ringkasan + embedding
-- ============================================================

CREATE TABLE IF NOT EXISTS conversation_analysis (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id    UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    bot_id             UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id             UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    end_user_id        TEXT,
    channel            TEXT        NOT NULL DEFAULT 'widget',   -- widget | whatsapp | instagram | telegram | api
    intent             TEXT,
    sentiment_label    TEXT,                                    -- positive | neutral | negative
    sentiment_score    FLOAT,                                   -- -1.0 .. 1.0
    topics             TEXT[]      NOT NULL DEFAULT '{}',
    outcome            TEXT,                                    -- resolved | unresolved | abandoned | escalated
    lead_status        lead_status_t       NOT NULL DEFAULT 'none',
    purchase_status    purchase_status_t   NOT NULL DEFAULT 'none',
    escalation_status  escalation_status_t NOT NULL DEFAULT 'none',
    summary            TEXT,                                    -- ringkasan otomatis (LLM)
    quality_score      FLOAT,                                   -- 0..10, dari TrainerAgent
    raw_metrics        JSONB       NOT NULL DEFAULT '{}',       -- payload tambahan (friction_points, dll)
    analyzed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_analysis_bot      ON conversation_analysis(bot_id, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_org      ON conversation_analysis(org_id);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_intent   ON conversation_analysis(bot_id, intent);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_lead     ON conversation_analysis(bot_id, lead_status);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_purchase ON conversation_analysis(bot_id, purchase_status);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_topics   ON conversation_analysis USING GIN(topics);
CREATE INDEX IF NOT EXISTS idx_conv_analysis_enduser  ON conversation_analysis(bot_id, end_user_id);


CREATE TABLE IF NOT EXISTS conversation_embeddings (
    conversation_id UUID PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    embedding       vector(384) NOT NULL,
    model           TEXT        NOT NULL DEFAULT 'local-hash-384',
    source_text     TEXT,                       -- teks yang di-embed (ringkasan / cuplikan)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_emb_bot ON conversation_embeddings(bot_id);
-- ANN index untuk semantic search skala besar (cosine distance)
CREATE INDEX IF NOT EXISTS idx_conv_emb_ann
    ON conversation_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);


-- ============================================================
-- 2. FAQ ENGINE
--    Pertanyaan→Jawaban yang terbentuk otomatis dari clustering
-- ============================================================

CREATE TABLE IF NOT EXISTS faq_entries (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id             UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id             UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    question           TEXT        NOT NULL,         -- pertanyaan kanonik (representatif cluster)
    answer             TEXT        NOT NULL,         -- jawaban terbaik (dipilih dari respons ber-skor tinggi)
    topic              TEXT,
    embedding          vector(384),                  -- untuk pencocokan semantik pertanyaan baru
    frequency_score    INT         NOT NULL DEFAULT 1,   -- berapa kali pertanyaan serupa muncul
    success_score      FLOAT       NOT NULL DEFAULT 0,   -- 0..1, rasio jawaban dianggap memuaskan (rating/quality)
    conversion_score   FLOAT       NOT NULL DEFAULT 0,   -- 0..1, rasio percakapan yg memuat FAQ ini berakhir purchase
    status             TEXT        NOT NULL DEFAULT 'auto',  -- auto | reviewed | published | archived
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_faq_bot        ON faq_entries(bot_id);
CREATE INDEX IF NOT EXISTS idx_faq_org        ON faq_entries(org_id);
CREATE INDEX IF NOT EXISTS idx_faq_freq       ON faq_entries(bot_id, frequency_score DESC);
CREATE INDEX IF NOT EXISTS idx_faq_conversion ON faq_entries(bot_id, conversion_score DESC);
CREATE INDEX IF NOT EXISTS idx_faq_emb_ann
    ON faq_entries USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);


-- Jejak pertanyaan-pertanyaan asal yang digabung menjadi satu FAQ
-- (audit trail + bahan re-cluster saat nightly job berikutnya)
-- faq_id NULL = kandidat baru menunggu di-cluster oleh nightly job;
-- terisi setelah digabung ke sebuah faq_entries (audit trail asal-usul FAQ).
CREATE TABLE IF NOT EXISTS faq_source_messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    faq_id          UUID REFERENCES faq_entries(id) ON DELETE CASCADE,
    bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    message_text    TEXT NOT NULL,
    answer_text     TEXT,                       -- jawaban bot saat itu (kandidat jawaban FAQ)
    embedding       vector(384),
    similarity      FLOAT,                      -- skor kemiripan ke pertanyaan kanonik saat clustering
    outcome         TEXT,                       -- resolved | unresolved | purchased ...
    quality_score   FLOAT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_faq_src_faq    ON faq_source_messages(faq_id);
CREATE INDEX IF NOT EXISTS idx_faq_src_conv   ON faq_source_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_faq_src_unclustered ON faq_source_messages(bot_id) WHERE faq_id IS NULL;


-- ============================================================
-- 3. SALES INTELLIGENCE
--    Pola Trigger → Objection → Solution dan tingkat konversinya
-- ============================================================

CREATE TABLE IF NOT EXISTS sales_patterns (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id            UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    pattern_type      TEXT        NOT NULL,   -- trigger | objection_price | objection_product | objection_service | reason_buy | reason_cancel
    trigger_text      TEXT,                   -- pertanyaan/ucapan yang memicu (mis. "ada promo gak?")
    objection_text    TEXT,                   -- keberatan yang muncul (mis. "kemahalan dibanding kompetitor")
    solution_text     TEXT,                   -- respons/solusi yang terbukti efektif meredakan objection
    occurrences       INT         NOT NULL DEFAULT 1,
    conversions       INT         NOT NULL DEFAULT 0,  -- berapa dari occurrences berakhir purchase
    conversion_rate   FLOAT       NOT NULL DEFAULT 0,  -- conversions / occurrences
    confidence_score  FLOAT       NOT NULL DEFAULT 0,  -- 0..1, makin banyak data makin tinggi
    embedding         vector(384),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_pat_bot   ON sales_patterns(bot_id, pattern_type);
CREATE INDEX IF NOT EXISTS idx_sales_pat_conv  ON sales_patterns(bot_id, conversion_rate DESC);
CREATE INDEX IF NOT EXISTS idx_sales_pat_emb_ann
    ON sales_patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);


-- Sinyal mentah per percakapan (sebelum diagregasi jadi sales_patterns)
CREATE TABLE IF NOT EXISTS sales_signals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    signal_type     TEXT NOT NULL,   -- pre_purchase_question | reason_buy | reason_cancel | objection_price | objection_product | objection_service
    text_snippet    TEXT NOT NULL,
    resulted_in_purchase BOOLEAN,
    pattern_id      UUID REFERENCES sales_patterns(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_sig_bot     ON sales_signals(bot_id, signal_type);
CREATE INDEX IF NOT EXISTS idx_sales_sig_pattern ON sales_signals(pattern_id);
CREATE INDEX IF NOT EXISTS idx_sales_sig_unprocessed ON sales_signals(bot_id) WHERE pattern_id IS NULL;


-- ============================================================
-- 4. KNOWLEDGE GRAPH
--    Relasi User ↔ Produk ↔ Pertanyaan ↔ Masalah ↔ Solusi ↔ Penjualan
-- ============================================================

CREATE TABLE IF NOT EXISTS kg_nodes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id      UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    node_type   kg_node_type_t NOT NULL,
    label       TEXT        NOT NULL,             -- nama tampilan (mis. "Paket Growth", "Login gagal")
    ref_id      TEXT,                             -- id eksternal (end_user_id, conversation_id, faq_id, ...)
    metadata    JSONB       NOT NULL DEFAULT '{}',
    weight      INT         NOT NULL DEFAULT 1,   -- berapa kali node ini "disebut" (mempengaruhi ukuran node di viz)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (bot_id, node_type, label)
);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_bot  ON kg_nodes(bot_id, node_type);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_ref  ON kg_nodes(bot_id, ref_id);


CREATE TABLE IF NOT EXISTS kg_edges (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id      UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_id   UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    target_id   UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    relation    TEXT        NOT NULL,             -- asks | has_problem | resolved_by | leads_to_sale | interested_in | mentions
    weight      INT         NOT NULL DEFAULT 1,   -- frekuensi co-occurrence (menebal saat berulang)
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (source_id, target_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_kg_edges_bot    ON kg_edges(bot_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_id);


-- ============================================================
-- 5. CUSTOMER INTELLIGENCE
--    Profil & akumulasi fakta per end-user lintas percakapan
-- ============================================================

CREATE TABLE IF NOT EXISTS customer_profiles (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id             UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id             UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    end_user_id        TEXT NOT NULL,
    display_name       TEXT,
    email              TEXT,
    total_conversations INT        NOT NULL DEFAULT 0,
    total_purchases    INT         NOT NULL DEFAULT 0,
    lifetime_value     NUMERIC(14,2) NOT NULL DEFAULT 0,
    lead_score         FLOAT       NOT NULL DEFAULT 0,   -- 0..1
    churn_risk         FLOAT       NOT NULL DEFAULT 0,   -- 0..1
    preferred_topics   TEXT[]      NOT NULL DEFAULT '{}',
    last_interaction_at TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (bot_id, end_user_id)
);

CREATE INDEX IF NOT EXISTS idx_cust_profile_bot   ON customer_profiles(bot_id);
CREATE INDEX IF NOT EXISTS idx_cust_profile_score ON customer_profiles(bot_id, lead_score DESC);

-- Fakta granular tentang customer (ekstensi dari LongTermFact di memory_agent.py,
-- dipersist agar bertahan lintas restart & bisa dianalisis lintas-bot)
CREATE TABLE IF NOT EXISTS customer_facts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id  UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
    fact_key    TEXT NOT NULL,         -- mis. "preferred_payment", "last_order_id"
    fact_value  JSONB NOT NULL,
    confidence  FLOAT NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL DEFAULT 'extracted',  -- extracted | explicit | inferred
    times_used  INT  NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (profile_id, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_cust_facts_profile ON customer_facts(profile_id);


-- ============================================================
-- 6. AUTO LEARNING — laporan harian
-- ============================================================

CREATE TABLE IF NOT EXISTS learning_reports (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id                 UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    org_id                 UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    report_date            DATE NOT NULL,
    conversations_analyzed INT  NOT NULL DEFAULT 0,
    new_faq_count          INT  NOT NULL DEFAULT 0,
    new_pattern_count      INT  NOT NULL DEFAULT 0,
    top_faq                JSONB NOT NULL DEFAULT '[]',
    top_complaint          JSONB NOT NULL DEFAULT '[]',
    top_sales_trigger      JSONB NOT NULL DEFAULT '[]',
    top_conversion_path    JSONB NOT NULL DEFAULT '[]',
    top_failed_conversation JSONB NOT NULL DEFAULT '[]',
    generated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (bot_id, report_date)
);

CREATE INDEX IF NOT EXISTS idx_learning_reports_bot ON learning_reports(bot_id, report_date DESC);


-- ============================================================
-- 7. Kolom tambahan pada tabel existing (aman dijalankan berulang)
-- ============================================================

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'widget';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS revenue_amount NUMERIC(14,2);
