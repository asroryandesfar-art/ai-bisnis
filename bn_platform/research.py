"""bn_platform/research.py — Research Agent router (Agent OS Phase 1).

Endpoint tipis untuk menjalankan ResearchAgent (riset web/lead discovery)
dari dashboard tenant. Read-only -- tidak menulis ke tabel apapun, hasil
riset dikembalikan langsung ke caller (tidak dipersist). RBAC-gated
(research.read), rate-limited. Mengikuti pola persis bn_platform/operations.py.
"""
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from research_agent import ResearchAgent
from .security import _check_rate_limit

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class ResearchRunRequest(BaseModel):
    goal: str


def build_research_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                           require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/research", tags=["research"])
    cfg = get_agent_config()
    agent = ResearchAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                          base_url=cfg.get("base_url"), app_url=cfg.get("app_url", "https://botnesia.id"))

    @router.post("/run")
    async def run_route(
        body: ResearchRunRequest,
        user: Annotated[dict, Depends(require_permission("research.read"))],
    ):
        _check_rate_limit(f"research:{user['org_id']}", 5)
        return await agent.run_research(
            body.goal,
            searxng_url=cfg.get("searxng_url", ""),
            tavily_api_key=cfg.get("search_api_key", ""),
        )

    return router
