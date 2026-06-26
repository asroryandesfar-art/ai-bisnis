"""
execution_log.py — Unified Execution Log (AI Agent Platform Phase 4+).

Modul data murni (tanpa LLM, tanpa class agent) yang membaca VIEW
`agent_execution_log` (lihat bn_platform/schema_platform.sql §10k) --
gabungan UNION ALL dari semua sistem task/eksekusi:
agent_executions (per-agent dalam pipeline chat, dipopulasi
agent_observability.py), workforce_tasks (AI Workforce), computer_agent_tasks
(browser automation), workflow_executions (Workflow Builder),
agent_task_executions (Task Engine), channel_message_tasks (Tool Framework),
agent_action_executions (Action Executor, AI Agent Platform).

Juga menyediakan `get_audit_log()` untuk membaca agent_audit_log
(aksi-aksi detail dari FileSystemService, TerminalService, ComputerUseService).
Tidak ada write-path baru di modul ini — murni query.
"""
from __future__ import annotations

import asyncpg

SOURCE_TYPES = (
    "chat_agent", "workforce_task", "computer_agent",
    "workflow", "agent_task", "channel_message", "action_execution",
)


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


async def get_audit_log(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    action_type: str | None = None,
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Baca audit log aksi detail agent (FileSystemService, TerminalService, ComputerUseService).

    Wrapper tipis di atas audit_logger.list_logs() supaya caller tidak perlu
    import audit_logger langsung.
    """
    from audit_logger import list_logs
    return await list_logs(
        pool, org_id=org_id, action_type=action_type,
        agent_name=agent_name, status=status, limit=limit,
    )


async def get_action_executions(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Baca riwayat Action Executor pipeline executions untuk satu org."""
    conditions = ["org_id=$1"]
    params: list = [org_id]
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    params.append(max(1, min(limit, 100)))
    try:
        rows = await pool.fetch(
            f"""SELECT id, goal, status, summary, duration_ms,
                       jsonb_array_length(plan) AS step_count, created_at
                FROM agent_action_executions
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC LIMIT ${len(params)}""",
            *params,
        )
        return [dict(r) for r in rows]
    except Exception:
        return []


async def get_permission_grants(
    pool: asyncpg.Pool,
    *,
    org_id: str,
) -> list[dict]:
    """Baca semua permission grant aktif untuk org ini."""
    from permission_manager import PermissionManager
    pm = PermissionManager(pool, org_id)
    return await pm.list_grants()
