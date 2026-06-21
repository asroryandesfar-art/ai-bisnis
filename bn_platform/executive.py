"""bn_platform/executive.py — Executive Center router (AI Workforce Phase 6).

AI CEO Assistant: sintesis Finance/Marketing/HR/Operations/Security/Sales
jadi satu company health score + executive brief (growth recommendations,
cost optimization, revenue opportunities, strategic insights). Reuse
ops_reports (source='executive') -- tidak ada tabel baru. RBAC-gated
(executive.read/write, owner/admin-only), audit-logged, org-scoped.
Mengikuti pola persis bn_platform/operations.py."""
import json
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import executive_agent as exe
from .security import _check_rate_limit, write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class ReportGenerateRequest(BaseModel):
    report_type: str


def _report_out(row: dict) -> dict:
    out = dict(row)
    if isinstance(out.get("data"), str):
        try:
            out["data"] = json.loads(out["data"])
        except Exception:
            out["data"] = {}
    return out


def build_executive_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                            require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/executive", tags=["executive"])
    cfg = get_agent_config()
    agent = exe.ExecutiveAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                base_url=cfg.get("base_url"), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("executive.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await exe.dashboard_summary(pool, user["org_id"])

    @router.get("/trends")
    async def trends(
        user: Annotated[dict, Depends(require_permission("executive.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        days: int = 30,
    ):
        return await exe.gather_trend_series(pool, user["org_id"], days=days)

    @router.get("/reports")
    async def list_reports(
        user: Annotated[dict, Depends(require_permission("executive.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        report_type: str | None = None,
        limit: int = 20,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 100))
        if report_type:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 AND source='executive' AND report_type=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, report_type, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 AND source='executive' ORDER BY created_at DESC LIMIT $2",
                org_id, limit,
            )
        return {"reports": [dict(r) for r in rows]}

    @router.post("/reports/generate", status_code=201)
    async def generate_report_route(
        body: ReportGenerateRequest,
        user: Annotated[dict, Depends(require_permission("executive.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"executive-report:{org_id}", 5)
        try:
            report = await exe.generate_executive_report(
                pool, org_id, body.report_type, generated_by=user["id"], agent=agent,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="ops_report", resource_id=report["id"],
            metadata={"report_type": body.report_type, "source": "executive"},
        )
        return _report_out(report)

    @router.post("/analyze")
    async def analyze_business_route(
        user: Annotated[dict, Depends(require_permission("executive.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"executive-analyze:{org_id}", 5)
        result = await exe.run_business_analysis(pool, org_id, agent=agent)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="business_analysis", resource_id=None,
            metadata={"business_health_label": result["business_health_label"]},
        )
        return result

    @router.post("/demo")
    async def investor_demo_route(
        user: Annotated[dict, Depends(require_permission("executive.read"))],
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"executive-demo:{org_id}", 5)
        return await exe.run_investor_demo(agent=agent)

    @router.get("/reports/{report_id}")
    async def get_report(
        report_id: str,
        user: Annotated[dict, Depends(require_permission("executive.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM ops_reports WHERE id=$1 AND org_id=$2 AND source='executive'", report_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Laporan tidak ditemukan")
        return _report_out(dict(row))

    return router
