"""Platform-wide Founder Operating System built on existing BotNesia data."""

import asyncio
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends

from .config import cfg
from .revenue_intel import _require_platform_admin, compute_churn, compute_mrr

GetCurrentUser = Callable[..., Awaitable[dict]]
GetPool = Callable[..., Awaitable[asyncpg.Pool]]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, float(value)))


def percentage_change(current: float, previous: float) -> float:
    current = float(current or 0)
    previous = float(previous or 0)
    if previous <= 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 2)


def calculate_health_score(*, growth: float, revenue: float, churn: float, usage: float, retention: float) -> dict:
    components = {
        "growth": round(_clamp(50 + growth * 2), 1),
        "revenue": round(_clamp(50 + revenue * 2), 1),
        "churn": round(_clamp(100 - churn * 5), 1),
        "usage": round(_clamp(50 + usage * 2), 1),
        "retention": round(_clamp(retention), 1),
    }
    score = round(sum(components.values()) / len(components))
    if score >= 80:
        label = "healthy"
    elif score >= 60:
        label = "stable"
    elif score >= 40:
        label = "watch"
    else:
        label = "critical"
    return {"score": score, "label": label, "components": components}


def build_founder_insights(metrics: dict, *, high_cost_tenants: list[dict], failing_agents: list[dict]) -> list[dict]:
    insights = []
    revenue_growth = float(metrics.get("revenue_growth_rate") or 0)
    churn = float(metrics.get("churn_rate") or 0)
    usage_growth = float(metrics.get("usage_growth_rate") or 0)
    profit = float(metrics.get("profit_idr") or 0)

    if revenue_growth >= 5:
        insights.append({"type": "positive", "title": f"Revenue naik {revenue_growth:.1f}%", "detail": "Pendapatan bulan ini tumbuh dibanding bulan sebelumnya."})
    elif revenue_growth <= -5:
        insights.append({"type": "warning", "title": f"Revenue turun {abs(revenue_growth):.1f}%", "detail": "Periksa upgrade plan, pembayaran gagal, dan pipeline tenant baru."})
    else:
        insights.append({"type": "neutral", "title": "Revenue relatif stabil", "detail": "Perubahan revenue masih dalam rentang 5% dari bulan sebelumnya."})

    if churn >= 5:
        insights.append({"type": "warning", "title": f"Churn meningkat ke {churn:.1f}%", "detail": "Prioritaskan tenant berisiko dan audit alasan pembatalan langganan."})
    elif churn == 0:
        insights.append({"type": "positive", "title": "Tidak ada churn terdeteksi", "detail": "Belum ada subscription yang dibatalkan dalam 30 hari terakhir."})

    if usage_growth >= 10:
        insights.append({"type": "positive", "title": f"Penggunaan AI tumbuh {usage_growth:.1f}%", "detail": "Volume conversation meningkat dibanding periode sebelumnya."})
    elif usage_growth <= -10:
        insights.append({"type": "warning", "title": f"Penggunaan AI turun {abs(usage_growth):.1f}%", "detail": "Identifikasi tenant yang berhenti aktif dan channel yang kehilangan trafik."})

    if profit < 0:
        insights.append({"type": "critical", "title": "Operating profit negatif", "detail": "AI cost dan marketing spend melebihi revenue bulan berjalan."})

    total_ai_cost = float(metrics.get("ai_cost_usd") or 0)
    for tenant in high_cost_tenants[:2]:
        share = (float(tenant.get("ai_cost_usd") or 0) / total_ai_cost * 100) if total_ai_cost > 0 else 0
        if share >= 25:
            insights.append({"type": "warning", "title": f"{tenant.get('name') or 'Tenant'} memakai {share:.1f}% AI cost", "detail": "Review model routing, token usage, dan margin tenant ini."})

    for agent in failing_agents[:2]:
        if float(agent.get("failure_rate") or 0) >= 10:
            insights.append({"type": "warning", "title": f"Agent {agent.get('agent_name') or 'unknown'} sering gagal", "detail": f"Failure rate {float(agent.get('failure_rate') or 0):.1f}% dalam 30 hari terakhir."})

    return insights[:8]


async def founder_overview(pool: asyncpg.Pool) -> dict:
    mrr_data, churn_data = await asyncio.gather(compute_mrr(pool), compute_churn(pool, period_days=30))

    business, tenants, usage, costs, retention = await asyncio.gather(
        pool.fetchrow(
            """SELECT
                 COALESCE(SUM(amount_idr),0)::bigint AS total_revenue_idr,
                 COALESCE(SUM(amount_idr) FILTER (WHERE paid_at >= DATE_TRUNC('month', NOW())),0)::bigint AS monthly_revenue_idr,
                 COALESCE(SUM(amount_idr) FILTER (
                   WHERE paid_at >= DATE_TRUNC('month', NOW()) - INTERVAL '1 month'
                     AND paid_at < DATE_TRUNC('month', NOW())),0)::bigint AS previous_month_revenue_idr
               FROM invoices WHERE status='paid'"""
        ),
        pool.fetchrow(
            """SELECT COUNT(*)::int AS total_tenants,
                      COUNT(*) FILTER (WHERE billing_status IN ('active','trialing'))::int AS active_tenants,
                      COUNT(*) FILTER (WHERE created_at >= NOW()-INTERVAL '30 days')::int AS new_tenants,
                      COUNT(*) FILTER (WHERE created_at >= NOW()-INTERVAL '60 days'
                                        AND created_at < NOW()-INTERVAL '30 days')::int AS previous_new_tenants
               FROM organizations"""
        ),
        pool.fetchrow(
            """SELECT COUNT(*)::bigint AS total_conversations,
                      COUNT(*) FILTER (WHERE started_at >= NOW()-INTERVAL '30 days')::bigint AS conversations_30d,
                      COUNT(*) FILTER (WHERE started_at >= NOW()-INTERVAL '60 days'
                                        AND started_at < NOW()-INTERVAL '30 days')::bigint AS previous_conversations_30d
               FROM conversations"""
        ),
        pool.fetchrow(
            """SELECT COALESCE(SUM(estimated_cost),0)::float AS total_ai_cost_usd,
                      COALESCE(SUM(estimated_cost) FILTER (WHERE created_at >= DATE_TRUNC('month', NOW())),0)::float AS monthly_ai_cost_usd,
                      COALESCE(SUM(token_count),0)::bigint AS total_tokens,
                      COALESCE(SUM(token_count) FILTER (WHERE created_at >= NOW()-INTERVAL '30 days'),0)::bigint AS tokens_30d
               FROM cost_records"""
        ),
        pool.fetchrow(
            """WITH cohort AS (
                 SELECT id FROM organizations WHERE created_at < NOW()-INTERVAL '30 days'
               )
               SELECT COUNT(*)::int AS eligible_tenants,
                      COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM conversations c
                        WHERE c.org_id=cohort.id AND c.started_at >= NOW()-INTERVAL '30 days'
                      ))::int AS retained_tenants
               FROM cohort"""
        ),
    )

    top_agents, top_channels, high_cost_tenants, failing_agents, trend = await asyncio.gather(
        pool.fetch(
            """SELECT agent_name, COUNT(*)::int AS executions,
                      COALESCE(SUM(total_tokens),0)::bigint AS tokens,
                      COUNT(*) FILTER (WHERE status='failed')::int AS failures,
                      ROUND(100.0 * COUNT(*) FILTER (WHERE status='failed') / NULLIF(COUNT(*),0), 1)::float AS failure_rate
               FROM agent_executions WHERE execution_start >= NOW()-INTERVAL '30 days'
               GROUP BY agent_name ORDER BY executions DESC LIMIT 8"""
        ),
        pool.fetch(
            """SELECT COALESCE(channel,'unknown') AS channel, COUNT(*)::bigint AS conversations
               FROM conversations WHERE started_at >= NOW()-INTERVAL '30 days'
               GROUP BY channel ORDER BY conversations DESC LIMIT 8"""
        ),
        pool.fetch(
            """SELECT o.id AS tenant_id, o.name,
                      COALESCE(SUM(c.estimated_cost),0)::float AS ai_cost_usd,
                      COALESCE(SUM(c.token_count),0)::bigint AS tokens
               FROM organizations o JOIN cost_records c ON c.tenant_id=o.id
               WHERE c.created_at >= DATE_TRUNC('month', NOW())
               GROUP BY o.id,o.name ORDER BY ai_cost_usd DESC LIMIT 8"""
        ),
        pool.fetch(
            """SELECT agent_name, COUNT(*)::int AS executions,
                      COUNT(*) FILTER (WHERE status='failed')::int AS failures,
                      ROUND(100.0 * COUNT(*) FILTER (WHERE status='failed') / NULLIF(COUNT(*),0), 1)::float AS failure_rate
               FROM agent_executions WHERE execution_start >= NOW()-INTERVAL '30 days'
               GROUP BY agent_name HAVING COUNT(*) FILTER (WHERE status='failed') > 0
               ORDER BY failure_rate DESC, failures DESC LIMIT 8"""
        ),
        pool.fetch(
            """SELECT day::date AS date,
                      COALESCE((SELECT SUM(i.amount_idr) FROM invoices i WHERE i.status='paid' AND i.paid_at::date=day::date),0)::bigint AS revenue,
                      COALESCE((SELECT SUM(c.estimated_cost) FROM cost_records c WHERE c.created_at::date=day::date),0)::float AS cost,
                      COALESCE((SELECT COUNT(*) FROM conversations v WHERE v.started_at::date=day::date),0)::bigint AS conversations
               FROM generate_series(CURRENT_DATE-29, CURRENT_DATE, INTERVAL '1 day') day ORDER BY day"""
        ),
    )

    business = dict(business or {})
    tenants = dict(tenants or {})
    usage = dict(usage or {})
    costs = dict(costs or {})
    retention = dict(retention or {})
    monthly_revenue = float(business.get("monthly_revenue_idr") or 0)
    previous_revenue = float(business.get("previous_month_revenue_idr") or 0)
    revenue_growth = percentage_change(monthly_revenue, previous_revenue)
    usage_growth = percentage_change(usage.get("conversations_30d") or 0, usage.get("previous_conversations_30d") or 0)
    tenant_growth = percentage_change(tenants.get("new_tenants") or 0, tenants.get("previous_new_tenants") or 0)
    eligible = int(retention.get("eligible_tenants") or 0)
    retained = int(retention.get("retained_tenants") or 0)
    retention_rate = round(retained / eligible * 100, 2) if eligible else 100.0
    churn_rate = round(float(churn_data.get("churn_rate") or 0) * 100, 2)
    usd_to_idr = max(1, int(cfg.founder_usd_to_idr))
    ai_cost_usd = float(costs.get("monthly_ai_cost_usd") or 0)
    ai_cost_idr = round(ai_cost_usd * usd_to_idr)
    total_cost_idr = ai_cost_idr + int(cfg.monthly_marketing_spend_idr or 0)
    profit_idr = round(monthly_revenue - total_cost_idr)
    active_tenants = int(tenants.get("active_tenants") or 0)

    metrics = {
        "mrr_idr": int(mrr_data.get("mrr_idr") or 0),
        "arr_idr": int(mrr_data.get("arr_idr") or 0),
        "revenue_idr": int(business.get("total_revenue_idr") or 0),
        "monthly_revenue_idr": round(monthly_revenue),
        "profit_idr": profit_idr,
        "cost_idr": total_cost_idr,
        "ai_cost_usd": ai_cost_usd,
        "ai_cost_idr": ai_cost_idr,
        "active_tenants": active_tenants,
        "total_tenants": int(tenants.get("total_tenants") or 0),
        "new_tenants": int(tenants.get("new_tenants") or 0),
        "churn_rate": churn_rate,
        "growth_rate": revenue_growth,
        "revenue_growth_rate": revenue_growth,
        "tenant_growth_rate": tenant_growth,
        "usage_growth_rate": usage_growth,
        "retention_rate": retention_rate,
        "total_conversations": int(usage.get("total_conversations") or 0),
        "conversations_30d": int(usage.get("conversations_30d") or 0),
        "total_token_usage": int(costs.get("total_tokens") or 0),
        "tokens_30d": int(costs.get("tokens_30d") or 0),
        "cost_per_tenant_usd": round(ai_cost_usd / active_tenants, 4) if active_tenants else 0.0,
        "usd_to_idr": usd_to_idr,
    }
    health = calculate_health_score(
        growth=tenant_growth, revenue=revenue_growth, churn=churn_rate,
        usage=usage_growth, retention=retention_rate,
    )
    high_cost_rows = [dict(row) for row in high_cost_tenants]
    failing_rows = [dict(row) for row in failing_agents]
    return {
        "metrics": metrics,
        "health_score": health,
        "insights": build_founder_insights(metrics, high_cost_tenants=high_cost_rows, failing_agents=failing_rows),
        "top_agents": [dict(row) for row in top_agents],
        "top_channels": [dict(row) for row in top_channels],
        "high_cost_tenants": high_cost_rows,
        "failing_agents": failing_rows,
        "trend": [dict(row) for row in trend],
        "period": "current_month_and_last_30_days",
    }


def build_founder_router(*, get_pool: GetPool, get_current_user: GetCurrentUser) -> APIRouter:
    router = APIRouter(prefix="/founder", tags=["founder-operating-system"])

    @router.get("/access")
    async def access(user: Annotated[dict, Depends(get_current_user)]):
        _require_platform_admin(user)
        return {"founder": True}

    @router.get("/overview")
    async def overview(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _require_platform_admin(user)
        return await founder_overview(pool)

    return router
