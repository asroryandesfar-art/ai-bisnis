"""bn_platform/self_learning.py — Self-Learning Center router (AI Workforce
Phase 8). Insight terdistilasi dari conversations/sales/complaints/
outcomes. Scan hanya membuat insight berstatus 'candidate' (tidak
memengaruhi chat); hanya yang di-approve manusia lewat endpoint ini yang
disuntik ke system prompt chat (lihat self_learning_engine.py dan
main.py chat()). RBAC-gated, audit-logged, org-scoped. Mengikuti pola
persis bn_platform/operations.py."""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import self_learning_engine as sl
from .security import _check_rate_limit, write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class InsightStatusRequest(BaseModel):
    status: str


def build_self_learning_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/learning", tags=["learning"])
    cfg = get_agent_config()
    agent = sl.SelfLearningAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                  base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("learning.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await sl.dashboard_summary(pool, user["org_id"])

    @router.get("/insights")
    async def list_insights_route(
        user: Annotated[dict, Depends(require_permission("learning.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        category: str | None = None, status: str | None = None, limit: int = 50,
    ):
        insights = await sl.list_insights(pool, org_id=user["org_id"], category=category, status=status, limit=limit)
        return {"insights": insights}

    @router.post("/scan")
    async def scan_route(
        user: Annotated[dict, Depends(require_permission("learning.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 90,
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"learning-scan:{org_id}", 5)
        created = await sl.run_learning_scan(pool, org_id, agent=agent, days=days)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="organizational_memory",
            metadata={"scan": True, "insights": len(created)},
        )
        return {"insights": created}

    @router.patch("/insights/{insight_id}")
    async def update_insight_route(
        insight_id: str, body: InsightStatusRequest,
        user: Annotated[dict, Depends(require_permission("learning.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            insight = await sl.update_insight_status(pool, org_id=org_id, insight_id=insight_id,
                                                       status=body.status, reviewed_by=user["id"])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not insight:
            raise HTTPException(404, "Insight tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="organizational_memory", resource_id=insight_id,
            metadata={"status": body.status},
        )
        return insight

    return router
