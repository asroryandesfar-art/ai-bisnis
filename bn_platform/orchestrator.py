"""bn_platform/orchestrator.py — Endpoint orkestrasi multi-agent (internal).

Permukaan TERAUTENTIKASI + RBAC untuk engine multi_agent_orchestrator. Domain
agent (HR/Finance/Analytics/dst) hanya aktif di sini setelah filter permission
efektif user. Widget publik /chat/{bot_id} TIDAK memakai modul ini.
"""
from typing import Annotated, Any, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

import agent_registry
from bn_platform.rbac import get_user_permissions
from multi_agent_orchestrator import MultiAgentOrchestrator

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]

# Key yang aman diteruskan ke constructor agent (BaseAgent). Sisanya (searxng_url,
# search_api_key) masuk lewat context, bukan __init__.
_AGENT_KW = ("api_key", "model", "base_url", "deepseek_api_key",
             "openrouter_api_key", "gemini_api_key", "app_url")


class OrchestrateReq(BaseModel):
    message: str
    agents: list[str] | None = None      # opsional: paksa agent tertentu (name/kategori)
    workspace: str | None = None
    timeout: float | None = None


def build_orchestrator_router(
    *,
    get_pool: GetPool,
    get_current_user: GetCurrentUser,
    get_agent_config: Callable[[], dict],
) -> APIRouter:
    router = APIRouter()

    def _agent_kwargs() -> dict:
        cfg = get_agent_config() or {}
        return {k: cfg[k] for k in _AGENT_KW if k in cfg}

    @router.get("/agent/registry")
    async def list_orchestratable_agents(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        """Agent yang boleh dipanggil user ini (setelah filter RBAC)."""
        perms = await get_user_permissions(pool, user["id"], user["org_id"])
        specs = agent_registry.orchestration_agents(allowed_permissions=perms)
        return {"agents": [
            {"name": s.name, "category": s.category, "permission": s.permission,
             "capabilities": s.capabilities}
            for s in specs
        ]}

    @router.post("/agent/orchestrate")
    async def orchestrate(
        body: OrchestrateReq,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        """Jalankan orkestrasi multi-agent penuh (RBAC-scoped)."""
        perms = await get_user_permissions(pool, user["id"], user["org_id"])
        cfg = get_agent_config() or {}
        orch = MultiAgentOrchestrator(agent_kwargs=_agent_kwargs())
        context: dict[str, Any] = {
            "org_id": user["org_id"],
            "actor_user_id": user["id"],
            "pool": pool,
            "role": user.get("role"),
            "workspace": body.workspace,
            "messages": [],
            "_searxng_url": cfg.get("searxng_url", ""),
            "_search_api_key": cfg.get("search_api_key", ""),
        }
        result = await orch.orchestrate(
            message=body.message,
            context=context,
            allowed_permissions=perms,
            requested_agents=body.agents,
            timeout=body.timeout,
        )
        return result.to_dict()

    return router
