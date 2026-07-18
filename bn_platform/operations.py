"""bn_platform/operations.py — Operations Center router (AI Workforce Phase 4).

Tenant health, workflow monitoring, SLA monitoring, weekly/monthly report,
dan critical alert. Read-only agregasi dari tabel yang sudah ada (lihat
docstring operations_agent.py) -- hanya menulis ke ops_alerts/ops_reports.
RBAC-gated (operations.read/operations.write), audit-logged, org-scoped.
Mengikuti pola persis bn_platform/finance.py."""
import json
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import operations_agent as ops
from .security import _check_rate_limit, write_audit_log
from .agent_toggles import require_agent_enabled

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


def _report_out(row: dict) -> dict:
    out = dict(row)
    if isinstance(out.get("data"), str):
        try:
            out["data"] = json.loads(out["data"])
        except Exception:
            out["data"] = {}
    return out


class AlertStatusRequest(BaseModel):
    status: str


class RunTaskRequest(BaseModel):
    goal: str
    bot_id: str | None = None


class ReportGenerateRequest(BaseModel):
    report_type: str


def build_operations_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                             require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/operations", tags=["operations"])
    cfg = get_agent_config()
    agent = ops.OperationsAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                 base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("operations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await ops.dashboard_summary(pool, user["org_id"])

    @router.get("/alerts")
    async def list_alerts(
        user: Annotated[dict, Depends(require_permission("operations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        conditions = ["org_id=$1"]
        params: list = [org_id]
        if status:
            params.append(status)
            conditions.append(f"status=${len(params)}")
        if severity:
            params.append(severity)
            conditions.append(f"severity=${len(params)}")
        params.append(limit)
        rows = await pool.fetch(
            f"SELECT * FROM ops_alerts WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
        return {"alerts": [dict(r) for r in rows]}

    @router.patch("/alerts/{alert_id}")
    async def update_alert_route(
        alert_id: str,
        body: AlertStatusRequest,
        user: Annotated[dict, Depends(require_permission("operations.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await ops.update_alert_status(pool, org_id=org_id, alert_id=alert_id,
                                                  status=body.status, actor_id=user["id"])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Alert tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="ops_alert", resource_id=alert_id,
            metadata={"status": body.status},
        )
        return row

    @router.post("/scan")
    async def scan_route(
        user: Annotated[dict, Depends(require_permission("operations.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(f"operations:{user['org_id']}", 5)
        created = await ops.run_health_scan(pool, user["org_id"])
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="ops_alert", metadata={"scan": True, "alerts_created": len(created)},
        )
        return {"alerts_created": created}

    @router.get("/reports")
    async def list_reports(
        user: Annotated[dict, Depends(require_permission("operations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        report_type: str | None = None,
        limit: int = 20,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 100))
        if report_type:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 AND report_type=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, report_type, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT id, org_id, report_type, period_start, period_end, summary, created_at FROM ops_reports "
                "WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2",
                org_id, limit,
            )
        return {"reports": [dict(r) for r in rows]}

    @router.post("/reports/generate", status_code=201)
    async def generate_report_route(
        body: ReportGenerateRequest,
        user: Annotated[dict, Depends(require_permission("operations.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"operations-report:{org_id}", 5)
        try:
            report = await ops.generate_report(pool, org_id, body.report_type, generated_by=user["id"], agent=agent)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="ops_report", resource_id=report["id"],
            metadata={"report_type": body.report_type},
        )
        return _report_out(report)

    @router.get("/reports/{report_id}")
    async def get_report(
        report_id: str,
        user: Annotated[dict, Depends(require_permission("operations.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM ops_reports WHERE id=$1 AND org_id=$2", report_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Laporan tidak ditemukan")
        return _report_out(dict(row))

    # ── Task Engine: goal bebas multi-step lewat Operations Agent's tools ──
    @router.post("/run-task")
    async def run_task(
        body: RunTaskRequest,
        user: Annotated[dict, Depends(require_permission("operations.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(f"operations-run-task:{user['org_id']}", 5)
        await require_agent_enabled(pool, str(user["org_id"]), "operations")
        result = await agent.run_task(body.goal, pool=pool, org_id=user["org_id"], bot_id=body.bot_id)
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="agent_task_execution",
            metadata={"goal": body.goal, "status": result.get("status")},
        )
        return result

    return router
