"""bn_platform/agent_center.py — Agent Center Dashboard router (AI Agent
Platform Phase 5). Read-only -- daftar agent (agent_registry.list_agents())
dan overview platform (agent_registry.AdminAgent.platform_overview(), murni
agregasi fakta lintas-sistem, tanpa LLM). Mengikuti pola persis
bn_platform/execution_log.py. Gated execution_log.read (reuse, sensitivity
sama: visibilitas lintas-sistem)."""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends

import agent_registry

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


def build_agent_center_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                               require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/agent-center", tags=["agent-center"])
    cfg = get_agent_config()
    admin_agent = agent_registry.AdminAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                                             base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.get("/agents")
    async def list_agents_route(
        user: Annotated[dict, Depends(require_permission("execution_log.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return {"agents": agent_registry.list_agents()}

    @router.get("/overview")
    async def overview_route(
        user: Annotated[dict, Depends(require_permission("execution_log.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await admin_agent.platform_overview(pool, user["org_id"])

    return router
