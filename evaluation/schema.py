"""evaluation.schema — DDL Evaluation Framework (P1-D).

Tabel `task_evaluations`: skor otomatis pasca-task (deterministik + LLM-judge
opsional). Additive & idempotent. Terhubung ke agent_task_executions (execution_id)
& agent_jobs (job_id) — keduanya nullable supaya bisa mengevaluasi sumber apa pun.
"""
from __future__ import annotations

import asyncpg

EVAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task_evaluations (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    execution_id  UUID,
    job_id        UUID,
    agent_name    TEXT,
    goal          TEXT,
    scores        JSONB NOT NULL DEFAULT '{}'::jsonb,
    overall       REAL,
    judged        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_evaluations_org ON task_evaluations(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_evaluations_exec ON task_evaluations(execution_id);
"""


async def ensure_eval_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(EVAL_SCHEMA_SQL)
