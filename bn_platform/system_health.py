"""Section 10 (Observability): one read-only `/system-health` endpoint that
composes existing health/metrics functions into a single dashboard payload —
no new analysis pipeline, just aggregation of what sections 5/6/8/9 and the
existing observability/security/improvement_engine modules already produce.
"""
from datetime import datetime, timezone
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends

from .cost_intelligence import monthly_cost_health
from .improvement_engine import (
    analyze_failed_answers,
    analyze_handoff_frequency,
    analyze_low_confidence,
)
from .knowledge_builder import knowledge_health_report
from .marketplace import agent_health_report
from .observability import metrics_snapshot
from .security import run_security_scan

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


async def system_health_report(pool: asyncpg.Pool, *, org_id: str) -> dict:
    security = await run_security_scan(pool, org_id=org_id)
    knowledge = await knowledge_health_report(pool, org_id=org_id)
    cost = await monthly_cost_health(pool, org_id=org_id)
    marketplace = await agent_health_report(pool)

    failed_answers = await analyze_failed_answers(pool, org_id=org_id, days=7)
    low_confidence = await analyze_low_confidence(pool, org_id=org_id, days=7)
    handoffs = await analyze_handoff_frequency(pool, org_id=org_id, days=7)

    top_issues: list[dict] = []
    for row in failed_answers:
        top_issues.append({
            "type": "failed_answer", "bot_id": row["bot_id"], "count": row["count"],
            "title": f"Intent '{row['intent']}' berakhir '{row['outcome']}'",
        })
    for row in low_confidence:
        top_issues.append({
            "type": "low_confidence", "bot_id": row["bot_id"], "count": row["count"],
            "title": f"Confidence rendah pada intent '{row['intent']}' (avg {row['avg_confidence']})",
        })
    for row in handoffs:
        top_issues.append({
            "type": "handoff", "bot_id": row["bot_id"], "count": row["count"],
            "title": f"Handoff berulang: {row['reason']}",
        })
    top_issues.sort(key=lambda i: i["count"], reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "org_id": org_id,
        "http_metrics": metrics_snapshot(),
        "security": {
            "score": security["score"],
            "findings_count": security["findings_count"],
            "findings": security["findings"][:10],
        },
        "top_issues_7d": top_issues[:10],
        "knowledge_health": knowledge,
        "marketplace_health": marketplace,
        "cost_health": cost,
    }


def build_system_health_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                require_permission) -> APIRouter:
    router = APIRouter(tags=["system-health"])

    @router.get("/system-health")
    async def get_system_health(
        user: Annotated[dict, Depends(require_permission("analytics.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await system_health_report(pool, org_id=user["org_id"])

    return router
