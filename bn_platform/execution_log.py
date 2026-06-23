"""bn_platform/execution_log.py — Unified Execution Log router (AI Agent
Platform Phase 4). Read-only -- query atas VIEW agent_execution_log, tidak
menulis ke tabel apapun. RBAC-gated (execution_log.read), mengikuti pola
persis bn_platform/operations.py."""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends

import execution_log as el

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


def build_execution_log_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/execution-log", tags=["execution-log"])

    @router.get("")
    async def list_route(
        user: Annotated[dict, Depends(require_permission("execution_log.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        source_type: str | None = None, status: str | None = None, limit: int = 50,
    ):
        entries = await el.list_execution_log(
            pool, org_id=user["org_id"], source_type=source_type, status=status, limit=limit,
        )
        return {"entries": entries}

    @router.get("/summary")
    async def summary_route(
        user: Annotated[dict, Depends(require_permission("execution_log.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await el.execution_log_summary(pool, user["org_id"])

    return router
