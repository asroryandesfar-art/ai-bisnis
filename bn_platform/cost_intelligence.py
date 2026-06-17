"""Tenant-scoped FinOps API for AI cost and budget intelligence."""
from __future__ import annotations

import asyncio

from calendar import monthrange
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cost_intelligence import budget_status


class BudgetUpdate(BaseModel):
    monthly_budget_usd: float = Field(ge=0, le=1_000_000_000)


async def monthly_cost_health(pool, *, org_id: str) -> dict:
    """Biaya bulanan + status budget satu tenant — dipakai oleh endpoint
    /cost-intelligence/summary dan oleh komposisi /system-health, supaya
    dua tempat itu tidak menduplikasi query yang sama."""
    totals = await pool.fetchrow(
        """SELECT
               COALESCE(SUM(estimated_cost) FILTER (
                   WHERE created_at >= DATE_TRUNC('month', NOW())), 0)::float AS monthly_cost,
               COALESCE(SUM(estimated_cost) FILTER (
                   WHERE created_at >= DATE_TRUNC('day', NOW())), 0)::float AS daily_cost,
               COALESCE(SUM(token_count) FILTER (
                   WHERE created_at >= DATE_TRUNC('month', NOW())), 0)::bigint AS monthly_tokens,
               COUNT(*) FILTER (
                   WHERE created_at >= DATE_TRUNC('month', NOW()))::int AS monthly_calls
           FROM cost_records WHERE tenant_id=$1""",
        org_id,
    )
    budget_row = await pool.fetchrow(
        "SELECT monthly_budget_usd::float AS monthly_budget_usd FROM tenant_cost_budgets WHERE tenant_id=$1",
        org_id,
    )
    monthly_cost = float((totals or {}).get("monthly_cost") or 0)
    monthly_budget = float((budget_row or {}).get("monthly_budget_usd") or 0)
    now = datetime.now(timezone.utc)
    days_in_month = monthrange(now.year, now.month)[1]
    projected_cost = monthly_cost / max(1, now.day) * days_in_month
    return {
        "monthly_cost": monthly_cost,
        "daily_cost": float((totals or {}).get("daily_cost") or 0),
        "projected_monthly_cost": projected_cost,
        "monthly_tokens": int((totals or {}).get("monthly_tokens") or 0),
        "monthly_calls": int((totals or {}).get("monthly_calls") or 0),
        "budget": {
            "monthly_budget_usd": monthly_budget,
            **budget_status(monthly_cost, monthly_budget),
        },
    }


def build_cost_intelligence_router(*, get_pool: Callable, get_current_user: Callable) -> APIRouter:
    router = APIRouter(prefix="/cost-intelligence", tags=["cost-intelligence"])

    @router.get("/summary")
    async def summary(user=Depends(get_current_user), pool=Depends(get_pool)):
        org_id = user["org_id"]
        cost_health = await monthly_cost_health(pool, org_id=org_id)

        async def grouped(column: str, limit: int = 20):
            allowed = {"agent_name", "model_name", "channel", "conversation_id"}
            if column not in allowed:
                raise ValueError("Invalid cost grouping")
            return await pool.fetch(
                f"""SELECT {column} AS label,
                           COALESCE(SUM(estimated_cost),0)::float AS cost,
                           COALESCE(SUM(token_count),0)::bigint AS tokens,
                           COUNT(*)::int AS calls
                    FROM cost_records
                    WHERE tenant_id=$1 AND created_at >= DATE_TRUNC('month', NOW())
                    GROUP BY {column}
                    ORDER BY cost DESC LIMIT {int(limit)}""",
                org_id,
            )

        by_agent, by_model, by_channel, by_conversation = await asyncio.gather(
            grouped("agent_name"), grouped("model_name"),
            grouped("channel"), grouped("conversation_id", 15),
        )
        daily = await pool.fetch(
            """SELECT created_at::date AS date,
                      COALESCE(SUM(estimated_cost),0)::float AS cost,
                      COALESCE(SUM(token_count),0)::bigint AS tokens
               FROM cost_records
               WHERE tenant_id=$1 AND created_at >= NOW() - INTERVAL '30 days'
               GROUP BY created_at::date ORDER BY date""",
            org_id,
        )
        tenant = await pool.fetchrow(
            """SELECT o.id AS tenant_id, o.name,
                      COALESCE(SUM(c.estimated_cost),0)::float AS cost,
                      COALESCE(SUM(c.token_count),0)::bigint AS tokens
               FROM organizations o
               LEFT JOIN cost_records c ON c.tenant_id=o.id
                 AND c.created_at >= DATE_TRUNC('month', NOW())
               WHERE o.id=$1 GROUP BY o.id, o.name""",
            org_id,
        )
        routing = await pool.fetch(
            """SELECT task_complexity, routed_model, COUNT(*)::int AS requests
               FROM ai_traces
               WHERE tenant_id=$1 AND created_at >= DATE_TRUNC('month', NOW())
               GROUP BY task_complexity, routed_model ORDER BY requests DESC""",
            org_id,
        )

        # Cost Control: per-tenant image generation + storage usage, per-agent
        # latency/success rate — komposisi dari tabel yang sudah ada
        # (image_generations, documents, agent_executions), bukan pipeline baru.
        image_usage = await pool.fetchrow(
            """SELECT COUNT(*)::int AS monthly_count,
                      COALESCE(SUM(estimated_cost),0)::float AS monthly_cost
               FROM image_generations
               WHERE org_id=$1 AND kind='generate' AND status='completed'
                 AND created_at >= DATE_TRUNC('month', NOW())""",
            org_id,
        )
        storage_usage = await pool.fetchrow(
            """SELECT COALESCE(SUM(file_size),0)::bigint AS document_bytes,
                      COUNT(*)::int AS document_count
               FROM documents WHERE org_id=$1""",
            org_id,
        )
        agent_performance = await pool.fetch(
            """SELECT agent_name,
                      COUNT(*)::int AS calls,
                      ROUND(AVG(duration_ms)::numeric, 0) AS avg_latency_ms,
                      ROUND(
                          (COUNT(*) FILTER (WHERE status='success')::numeric
                           / GREATEST(COUNT(*), 1)) * 100, 1
                      ) AS success_rate_pct
               FROM agent_executions
               WHERE tenant_id=$1 AND created_at >= DATE_TRUNC('month', NOW())
               GROUP BY agent_name ORDER BY calls DESC""",
            org_id,
        )
        return {
            "currency": "USD",
            **cost_health,
            "cost_by_tenant": [dict(tenant)] if tenant else [],
            "cost_by_agent": [dict(row) for row in by_agent],
            "cost_by_model": [dict(row) for row in by_model],
            "cost_by_channel": [dict(row) for row in by_channel],
            "cost_by_conversation": [dict(row) for row in by_conversation],
            "daily_costs": [dict(row) for row in daily],
            "model_routing": [dict(row) for row in routing],
            "image_generation_usage": dict(image_usage) if image_usage else {"monthly_count": 0, "monthly_cost": 0.0},
            "storage_usage": dict(storage_usage) if storage_usage else {"document_bytes": 0, "document_count": 0},
            "agent_performance": [dict(row) for row in agent_performance],
        }

    @router.put("/budget")
    async def update_budget(
        body: BudgetUpdate,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        if user.get("role") not in {"owner", "admin"}:
            raise HTTPException(403, "Hanya owner atau admin yang dapat mengubah budget")
        await pool.execute(
            """INSERT INTO tenant_cost_budgets
               (tenant_id, monthly_budget_usd, updated_by, updated_at)
               VALUES ($1,$2,$3,NOW())
               ON CONFLICT (tenant_id) DO UPDATE SET
                 monthly_budget_usd=EXCLUDED.monthly_budget_usd,
                 updated_by=EXCLUDED.updated_by, updated_at=NOW()""",
            user["org_id"], body.monthly_budget_usd, user["id"],
        )
        return {"monthly_budget_usd": body.monthly_budget_usd}

    return router
