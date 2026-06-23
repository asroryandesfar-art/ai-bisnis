"""
execution_log.py — Unified Execution Log (AI Agent Platform Phase 4).

Modul data murni (tanpa LLM, tanpa class agent) yang membaca VIEW
`agent_execution_log` (lihat bn_platform/schema_platform.sql §10k) --
gabungan UNION ALL dari 5 sistem task/eksekusi yang sudah ada:
agent_executions (per-agent dalam pipeline chat, dipopulasi
agent_observability.py), workforce_tasks (AI Workforce), computer_agent_tasks
(browser automation), workflow_executions (Workflow Builder),
agent_task_executions (Task Engine, lihat task_engine.py). Tidak ada
write-path baru di modul ini -- murni query atas data yang sudah ada,
fondasi untuk Agent Center dashboard (Fase 5).
"""
from __future__ import annotations

import asyncpg

SOURCE_TYPES = ("chat_agent", "workforce_task", "computer_agent", "workflow", "agent_task")


async def list_execution_log(
    pool: asyncpg.Pool, *, org_id: str, source_type: str | None = None,
    status: str | None = None, limit: int = 50,
) -> list[dict]:
    conditions = ["org_id=$1"]
    params: list = [org_id]
    if source_type:
        params.append(source_type)
        conditions.append(f"source_type=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    params.append(max(1, min(limit, 200)))
    rows = await pool.fetch(
        f"""SELECT * FROM agent_execution_log WHERE {' AND '.join(conditions)}
            ORDER BY started_at DESC LIMIT ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


async def execution_log_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    rows = await pool.fetch(
        """SELECT source_type, status, COUNT(*) AS cnt
           FROM agent_execution_log WHERE org_id=$1
           GROUP BY source_type, status""",
        org_id,
    )
    by_source_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_source_type[r["source_type"]] = by_source_type.get(r["source_type"], 0) + int(r["cnt"])
        by_status[r["status"]] = by_status.get(r["status"], 0) + int(r["cnt"])
    return {"by_source_type": by_source_type, "by_status": by_status}
