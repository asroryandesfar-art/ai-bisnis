"""bn_platform/casper_engineer_router.py — Casper Engineer router.

Endpoint tenant untuk menjalankan Casper Engineer (agen software-engineer
otonom: planning → repo analysis → self-verification → self-critique). Modul
TERPISAH dari Casper Blockchain (casper/workflow.py) — tidak saling mengubah.

RBAC-gated (workforce.read/write — menjalankan task agent otonom), rate-limited,
hasil dipersist per-tenant ke `casper_engineer_runs`. Mengikuti pola persis
bn_platform/research.py + agent_center.py (factory DI, tanpa import dari main).
"""
import json
from typing import Annotated, Awaitable, Callable, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from casper_engineer import CasperEngineerAgent
from .security import _check_rate_limit

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class EngineerRunRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=4000)
    repo_context: Optional[str] = Field(None, max_length=12000)


def build_casper_engineer_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                  require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/casper/engineer", tags=["casper-engineer"])
    cfg = get_agent_config()
    agent = CasperEngineerAgent(
        api_key=cfg.get("api_key"), model=cfg.get("model"), base_url=cfg.get("base_url"),
        deepseek_api_key=cfg.get("deepseek_api_key", ""),
        openrouter_api_key=cfg.get("openrouter_api_key", ""),
        gemini_api_key=cfg.get("gemini_api_key", ""),
        app_url=cfg.get("app_url", "https://botnesia.id"),
    )

    @router.post("/run")
    async def run_engineer(
        body: EngineerRunRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        _check_rate_limit(f"casper_engineer:{user['org_id']}", 10)
        context = {
            "goal": body.goal,
            "repo_context": body.repo_context or "",
            "org_id": str(user["org_id"]),
            "_observability_pool": pool,   # supaya run tercatat di observability
        }
        result = await agent.safe_run(context)
        out = result.output or {}

        row = await pool.fetchrow(
            """INSERT INTO casper_engineer_runs
               (org_id, user_id, goal, repo_context, planning, repository_analysis,
                self_verification, self_critique, status, confidence)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10)
               RETURNING id, created_at""",
            user["org_id"], user["id"], body.goal, body.repo_context,
            json.dumps(out.get("planning", {})),
            json.dumps(out.get("repository_analysis", {})),
            json.dumps(out.get("self_verification", {})),
            json.dumps(out.get("self_critique", {})),
            out.get("status", "needs_review"),
            out.get("confidence"),
        )
        return {
            "id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
            "goal": body.goal,
            "status": out.get("status", "needs_review"),
            "confidence": out.get("confidence"),
            "needs_repo_context": out.get("needs_repo_context", False),
            "planning": out.get("planning", {}),
            "repository_analysis": out.get("repository_analysis", {}),
            "self_verification": out.get("self_verification", {}),
            "self_critique": out.get("self_critique", {}),
        }

    @router.get("/runs")
    async def list_runs(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        limit: int = 20,
    ):
        rows = await pool.fetch(
            """SELECT id, goal, status, confidence, created_at
               FROM casper_engineer_runs WHERE org_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            user["org_id"], min(max(limit, 1), 100),
        )
        return [
            {
                "id": str(r["id"]), "goal": r["goal"], "status": r["status"],
                "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    @router.get("/run/{run_id}")
    async def get_run(
        run_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        row = await pool.fetchrow(
            """SELECT id, goal, repo_context, planning, repository_analysis,
                      self_verification, self_critique, status, confidence, created_at
               FROM casper_engineer_runs WHERE id = $1 AND org_id = $2""",
            _as_uuid(run_id), user["org_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        # Pool utama tidak punya jsonb codec -> kolom JSONB kembali sebagai string.
        return {
            "id": str(row["id"]), "goal": row["goal"], "repo_context": row["repo_context"],
            "planning": _load_json(row["planning"]),
            "repository_analysis": _load_json(row["repository_analysis"]),
            "self_verification": _load_json(row["self_verification"]),
            "self_critique": _load_json(row["self_critique"]),
            "status": row["status"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "created_at": row["created_at"].isoformat(),
        }

    return router


def _load_json(value):
    """JSONB dari pool utama (tanpa codec) kembali sebagai string -> parse aman."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


def _as_uuid(value: str):
    import uuid
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="ID tidak valid") from exc
