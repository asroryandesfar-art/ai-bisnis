"""long_term_memory.schema — DDL memori jangka-panjang semantik (P1-B.1).

Tabel `agent_memories` menyimpan memori yang bisa di-RETRIEVE saat reasoning
(bukan sekadar ditulis) — menutup temuan audit "memory write-only". Vektor
via pgvector (dim 384 = model lokal all-MiniLM). Additive & idempotent.

Degrade jujur: bila `CREATE EXTENSION vector` gagal (tak ada di server) → seluruh
ensure di-wrap try oleh pemanggil; SemanticMemory tetap jalan mode non-vektor
(retrieval fallback recency/teks).
"""
from __future__ import annotations

import asyncpg

EMBED_DIM = 384

MEMORY_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS agent_memories (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id           UUID REFERENCES bots(id) ON DELETE SET NULL,
    scope            TEXT NOT NULL DEFAULT 'semantic'
        CHECK (scope IN ('semantic','episodic','task','reasoning')),
    subject          TEXT,
    content          TEXT NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    embedding        vector({EMBED_DIM}),
    importance       REAL NOT NULL DEFAULT 0.5,
    access_count     INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_org
    ON agent_memories(org_id, scope, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_memories_subject
    ON agent_memories(org_id, scope, subject);
"""

# Index vektor (ANN) — coba HNSW dulu (pgvector>=0.5), lalu IVFFlat, lalu lewati.
_VECTOR_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_agent_memories_vec ON agent_memories "
    "USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_agent_memories_vec ON agent_memories "
    "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)",
)


async def ensure_memory_schema(pool: asyncpg.Pool) -> None:
    """Buat extension vector + tabel + index (idempotent). Index vektor best-effort."""
    await pool.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await pool.execute(MEMORY_SCHEMA_SQL)
    for idx_sql in _VECTOR_INDEXES:
        try:
            await pool.execute(idx_sql)
            break
        except Exception:
            continue
