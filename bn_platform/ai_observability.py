"""Tenant-scoped API for AI execution metrics and trace inspection."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query


def build_ai_observability_router(*, get_pool: Callable, get_current_user: Callable) -> APIRouter:
    router = APIRouter(prefix="/observability", tags=["ai-observability"])

    @router.get("/summary")
    async def summary(
        days: int = Query(7, ge=1, le=90),
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        org_id = user["org_id"]
        totals = await pool.fetchrow(
            """WITH windowed AS (
                   SELECT *
                   FROM agent_executions
                   WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ),
               latest AS (
                   SELECT DISTINCT ON (agent_name) agent_name, status
                   FROM windowed
                   ORDER BY agent_name, execution_start DESC
               )
               SELECT
                   COUNT(*) FILTER (WHERE status='running' AND execution_start >= NOW() - INTERVAL '5 minutes') AS active_agents,
                   (SELECT COUNT(*) FROM latest WHERE status='error') AS failed_agents,
                   COALESCE(AVG(duration_ms) FILTER (WHERE status <> 'running'), 0)::float AS average_latency_ms,
                   COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens,
                   COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)::bigint AS completion_tokens,
                   COALESCE(100.0 * COUNT(*) FILTER (WHERE status IN ('success','skipped')) /
                       NULLIF(COUNT(*) FILTER (WHERE status <> 'running'), 0), 0)::float AS success_rate,
                   COALESCE(100.0 * COUNT(*) FILTER (WHERE status='error') /
                       NULLIF(COUNT(*) FILTER (WHERE status <> 'running'), 0), 0)::float AS error_rate
               FROM windowed""",
            org_id, days,
        )
        agents = await pool.fetch(
            """WITH windowed AS (
                   SELECT *
                   FROM agent_executions
                   WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ),
               latest AS (
                   SELECT DISTINCT ON (agent_name)
                          agent_name, status AS last_status, error_message AS last_error
                   FROM windowed
                   ORDER BY agent_name, execution_start DESC
               )
               SELECT w.agent_name,
                      COUNT(*)::int AS executions,
                      COUNT(*) FILTER (WHERE w.status='error')::int AS failures,
                      COALESCE(SUM(w.retry_count),0)::int AS retries,
                      COALESCE(AVG(w.duration_ms),0)::float AS average_latency_ms,
                      COALESCE(SUM(w.total_tokens),0)::bigint AS total_tokens,
                      MAX(w.execution_start) AS last_seen_at,
                      l.last_status,
                      l.last_error
               FROM windowed w
               JOIN latest l ON l.agent_name=w.agent_name
               GROUP BY w.agent_name, l.last_status, l.last_error
               ORDER BY executions DESC, agent_name""",
            org_id, days,
        )
        traces = await pool.fetch(
            """SELECT id, conversation_id, user_question, status, duration_ms,
                      prompt_tokens, completion_tokens, total_tokens, started_at,
                      (SELECT COUNT(*) FROM agent_executions ae WHERE ae.trace_id=t.id) AS agent_count
               FROM ai_traces t
               WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ORDER BY started_at DESC LIMIT 50""",
            org_id, days,
        )
        return {
            "window_days": days,
            "metrics": dict(totals or {}),
            "agents": [dict(row) for row in agents],
            "traces": [dict(row) for row in traces],
        }

    @router.get("/traces/{trace_id}")
    async def trace_detail(
        trace_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        trace = await pool.fetchrow(
            """SELECT id, tenant_id, conversation_id, user_question, final_answer,
                      status, started_at, ended_at, duration_ms,
                      prompt_tokens, completion_tokens, total_tokens
               FROM ai_traces WHERE id=$1 AND tenant_id=$2""",
            trace_id, user["org_id"],
        )
        if not trace:
            raise HTTPException(404, "Trace tidak ditemukan")
        executions = await pool.fetch(
            """SELECT id, parent_execution_id, agent_name, sequence_no,
                      execution_start, execution_end, duration_ms, status,
                      error_message, confidence_score::float AS confidence_score,
                      prompt_tokens, completion_tokens, total_tokens, metadata
               FROM agent_executions
               WHERE trace_id=$1 AND tenant_id=$2
               ORDER BY sequence_no, execution_start""",
            trace_id, user["org_id"],
        )
        return {"trace": dict(trace), "executions": [dict(row) for row in executions]}

    return router
