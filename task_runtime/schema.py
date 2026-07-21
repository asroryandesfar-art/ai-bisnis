"""task_runtime.schema — DDL durable task runtime (P0-D D1).

Tabel state-hidup job (agent_jobs) + checkpoint per-langkah (agent_job_steps).
BUKAN pengganti agent_task_executions (tetap jadi laporan final saat job selesai).
Additive & idempotent (CREATE TABLE/INDEX IF NOT EXISTS) → aman dijalankan berkali
di startup (ensure_optional_schema) maupun di setup test.
"""
from __future__ import annotations

import asyncpg

JOB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    bot_id              UUID REFERENCES bots(id) ON DELETE SET NULL,
    agent_name          TEXT NOT NULL,
    goal                TEXT NOT NULL,
    ctx                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','paused','pausing','cancelling',
                          'cancelled','failed','dead_letter','completed')),
    priority            INT NOT NULL DEFAULT 5,
    progress_pct        INT NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    attempts            INT NOT NULL DEFAULT 0,
    max_attempts        INT NOT NULL DEFAULT 3,
    step_timeout_s      INT NOT NULL DEFAULT 120,
    max_duration_s      INT NOT NULL DEFAULT 3600,
    lease_owner         TEXT,
    lease_until         TIMESTAMPTZ,
    dlq_reason          TEXT,
    last_error          TEXT,
    idempotency_key     TEXT,
    result_execution_id UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_org ON agent_jobs(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_claim ON agent_jobs(status, priority, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_jobs_idem
    ON agent_jobs(org_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_job_steps (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id               UUID NOT NULL REFERENCES agent_jobs(id) ON DELETE CASCADE,
    seq                  INT NOT NULL,
    kind                 TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','done','failed')),
    checkpoint           JSONB,
    output               JSONB,
    tool_calls           JSONB,
    step_idempotency_key TEXT,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at             TIMESTAMPTZ,
    UNIQUE (job_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_agent_job_steps_job ON agent_job_steps(job_id, seq);
"""


async def ensure_job_schema(pool: asyncpg.Pool) -> None:
    """Buat tabel job runtime bila belum ada (idempotent)."""
    await pool.execute(JOB_SCHEMA_SQL)
