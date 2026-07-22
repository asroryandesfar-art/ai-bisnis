"""prompt_registry.schema — DDL Prompt Management (P2-B).

Tabel `agent_prompts`: versi prompt agen dengan riwayat immutable, rollback
(aktifkan versi lama), dan A/B (>1 varian aktif berbobot). Additive & idempotent.

`org_id` NULLABLE: NULL = override global default; baris ber-org menang atas global
saat resolusi. Versi monoton per (name, org_id, variant). Prompt hardcoded di kelas
agen tetap jadi fallback bila tak ada baris aktif → default byte-identik.
"""
from __future__ import annotations

import asyncpg

PROMPT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_prompts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,
    variant     TEXT NOT NULL DEFAULT 'default',
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    weight      INTEGER NOT NULL DEFAULT 100,
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Versi unik per (name, org, variant). org_id NULL disamakan via COALESCE agar
-- baris global tetap tunduk keunikan versi.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_prompts_version
    ON agent_prompts (name, COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid), variant, version);
CREATE INDEX IF NOT EXISTS idx_agent_prompts_active
    ON agent_prompts (name, active) WHERE active;
"""


async def ensure_prompt_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(PROMPT_SCHEMA_SQL)
