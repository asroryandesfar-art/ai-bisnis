"""bn_platform/channel_messaging.py — Channel Messaging router (Tool
Framework Phase 7). List/get pesan keluar yang dibuat agent lewat
run_task() (audit trail), approve/reject sebelum benar-benar dikirim ke
pelanggan. Eksekusi sesungguhnya (kirim via ChannelManager) tetap di
channel_messaging.py (top-level module) -- router ini hanya RBAC gate +
audit log, mengikuti pola persis bn_platform/computer_agent.py."""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import channel_messaging as cm
from .security import write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class RejectTaskRequest(BaseModel):
    reason: str | None = None


def build_channel_messaging_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                     require_permission, app_url: str = "") -> APIRouter:
    router = APIRouter(prefix="/channel-messaging", tags=["channel-messaging"])

    @router.get("/tasks")
    async def list_tasks_route(
        user: Annotated[dict, Depends(require_permission("channel_messaging.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
    ):
        tasks = await cm.list_tasks(pool, org_id=user["org_id"], status=status, limit=limit)
        return {"tasks": tasks}

    @router.get("/tasks/{task_id}")
    async def get_task_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("channel_messaging.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await cm.get_task(pool, org_id=user["org_id"], task_id=task_id)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan")
        return task

    @router.post("/tasks/{task_id}/approve")
    async def approve_task_route(
        task_id: str,
        user: Annotated[dict, Depends(require_permission("channel_messaging.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await cm.approve_task(pool, org_id=user["org_id"], task_id=task_id, approver_id=user["id"], app_url=app_url)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan atau tidak butuh approval")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="channel_message_task", resource_id=task_id,
            metadata={"approved": True, "channel": task.get("channel")},
        )
        return task

    @router.post("/tasks/{task_id}/reject")
    async def reject_task_route(
        task_id: str, body: RejectTaskRequest,
        user: Annotated[dict, Depends(require_permission("channel_messaging.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        task = await cm.reject_task(pool, org_id=user["org_id"], task_id=task_id,
                                     approver_id=user["id"], reason=body.reason)
        if not task:
            raise HTTPException(404, "Task tidak ditemukan atau tidak butuh approval")
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="channel_message_task", resource_id=task_id,
            metadata={"approved": False, "reason": body.reason},
        )
        return task

    return router
