"""bn_platform/computer_agent.py — Computer Agent router (AI Agent Platform
Phase 3). List/get task browser automation (audit trail, termasuk yang
auto-execute), approve/reject aksi tulis (klik/isi form/submit) yang butuh
human approval. Eksekusi sesungguhnya tetap di computer_agent.py (agent
module) -- router ini hanya RBAC gate + audit log, mengikuti pola persis
bn_platform/workforce.py."""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import computer_agent as ca
from .security import write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class RejectTaskRequest(BaseModel):
    reason: str | None = None


def build_computer_agent_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                 require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/computer-agent", tags=["computer-agent"])

    @router.get("/tasks")
    async def list_tasks_route(
        user: Annotated[dict, Depends(require_permission("computer_agent.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
    ):
        tasks = await ca.list_tasks(pool, org_id=user["org_id"], status=status, limit=limit)
        return {"tasks": tasks}

    @router.get("/tasks/{task_id}")
    async def get_task_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("computer_agent.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await ca.get_task(pool, org_id=user["org_id"], task_id=task_id)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan")
        return task

    @router.post("/tasks/{task_id}/approve")
    async def approve_task_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("computer_agent.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await ca.approve_task(pool, org_id=user["org_id"], task_id=task_id, approver_id=user["id"])
        if not task:
            raise HTTPException(404, "Task tidak ditemukan atau tidak butuh approval")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="computer_agent_task", resource_id=task_id,
            metadata={"approved": True},
        )
        return task

    @router.post("/tasks/{task_id}/reject")
    async def reject_task_route(
        task_id: str, body: RejectTaskRequest,
        user: Annotated[dict, Depends(require_permission("computer_agent.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await ca.reject_task(pool, org_id=user["org_id"], task_id=task_id,
                                     approver_id=user["id"], reason=body.reason)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan atau tidak butuh approval")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="computer_agent_task", resource_id=task_id,
            metadata={"approved": False, "reason": body.reason},
        )
        return task

    return router
