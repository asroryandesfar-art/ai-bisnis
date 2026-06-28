"""bn_platform/workforce.py — Workforce Orchestration router (AI Workforce
Phase 7). Koordinasi task lintas-agent (Finance/Marketing/HR/Operations/
Security/Executive): assign, status, approval, deteksi konflik, eskalasi.
Tidak pernah memanggil supervisor.py atau memicu aksi otomatis di domain
agent manapun -- murni tracking/koordinasi, eksekusi tetap manual lewat
endpoint domain masing-masing. Mengikuti pola persis bn_platform/operations.py."""
from datetime import datetime
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import workforce_orchestrator as wf
from .security import _check_rate_limit, write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class TaskCreateRequest(BaseModel):
    domain: str
    title: str
    description: str | None = None
    priority: str = "medium"
    source_type: str | None = None
    source_id: str | None = None
    requires_approval: bool = False
    assigned_to: str | None = None
    due_at: datetime | None = None
    parent_task_id: str | None = None


class TaskStatusRequest(BaseModel):
    status: str


class TaskAssignRequest(BaseModel):
    assigned_to: str


class TaskProgressRequest(BaseModel):
    progress_pct: int


def build_workforce_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                            require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/workforce", tags=["workforce"])
    cfg = get_agent_config()
    agent = wf.WorkforceOrchestratorAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                          base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await wf.dashboard_summary(pool, user["org_id"])

    @router.get("/tasks")
    async def list_tasks_route(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        domain: str | None = None, status: str | None = None,
        priority: str | None = None, limit: int = 50,
    ):
        tasks = await wf.list_tasks(pool, org_id=user["org_id"], domain=domain,
                                     status=status, priority=priority, limit=limit)
        return {"tasks": tasks}

    @router.post("/tasks", status_code=201)
    async def create_task_route(
        body: TaskCreateRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        try:
            task = await wf.create_task(
                pool, org_id=user["org_id"], domain=body.domain, title=body.title,
                description=body.description, priority=body.priority,
                source_type=body.source_type, source_id=body.source_id,
                requires_approval=body.requires_approval, assigned_to=body.assigned_to,
                due_at=body.due_at, created_by=user["id"], parent_task_id=body.parent_task_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="workforce_task", resource_id=task["id"],
            metadata={"domain": body.domain, "priority": body.priority},
        )
        return task

    @router.patch("/tasks/{task_id}/status")
    async def update_task_status_route(
        task_id: str, body: TaskStatusRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        try:
            task = await wf.update_task_status(pool, org_id=user["org_id"], task_id=task_id,
                                                status=body.status, actor_id=user["id"])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not task:
            raise HTTPException(404, "Task tidak ditemukan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workforce_task", resource_id=task_id,
            metadata={"status": body.status},
        )
        return task

    @router.patch("/tasks/{task_id}/progress")
    async def update_task_progress_route(
        task_id: str, body: TaskProgressRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        try:
            task = await wf.update_progress(pool, org_id=user["org_id"], task_id=task_id,
                                             progress_pct=body.progress_pct)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not task:
            raise HTTPException(404, "Task tidak ditemukan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workforce_task", resource_id=task_id,
            metadata={"progress_pct": body.progress_pct},
        )
        return task

    @router.get("/tasks/{task_id}/subtasks")
    async def list_subtasks_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        subtasks = await wf.list_subtasks(pool, org_id=user["org_id"], parent_task_id=task_id)
        return {"subtasks": subtasks}

    @router.patch("/tasks/{task_id}/assign")
    async def assign_task_route(
        task_id: str, body: TaskAssignRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await wf.assign_task(pool, org_id=user["org_id"], task_id=task_id, assigned_to=body.assigned_to)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workforce_task", resource_id=task_id,
            metadata={"assigned_to": body.assigned_to},
        )
        return task

    @router.post("/tasks/{task_id}/approve")
    async def approve_task_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await wf.approve_task(pool, org_id=user["org_id"], task_id=task_id, approver_id=user["id"])
        if not task:
            raise HTTPException(404, "Task tidak ditemukan atau tidak butuh approval")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workforce_task", resource_id=task_id,
            metadata={"approved": True},
        )
        return task

    @router.post("/scan-conflicts")
    async def scan_conflicts_route(
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        _check_rate_limit(f"workforce-scan:{org_id}", 5)
        conflicts = await wf.detect_conflicts(pool, org_id)
        escalated = await wf.escalate_overdue_tasks(pool, org_id)

        suggestions = []
        if conflicts:
            tasks = await wf.list_tasks(pool, org_id=org_id, limit=200)
            for conflict in conflicts:
                conflicting_tasks = [t for t in tasks if str(t["id"]) in conflict["task_ids"]]
                suggestion = await agent.suggest_conflict_resolution(conflicting_tasks)
                suggestions.append({**conflict, "ai_suggestion": suggestion})

        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workforce_task",
            metadata={"scan": True, "conflicts_found": len(conflicts), "escalated_count": len(escalated)},
        )
        return {"conflicts": suggestions, "escalated": escalated}

    return router
