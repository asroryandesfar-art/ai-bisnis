"""bn_platform/jobs_router.py — HTTP API Durable Task Runtime (P0-D D5).

Endpoint tenant untuk mengantre & mengontrol durable job (agent_jobs). RBAC-gated
(workforce.read/write), rate-limited. Mengikuti pola factory-DI casper_engineer_
router (tanpa import dari main). JANGAN `from __future__ import annotations`
(merusak resolusi Depends closure di FastAPI).

Endpoint TAMBAHAN & opsional — jalur eksekusi lama (run_task inline) tak berubah.
"""
from typing import Annotated, Awaitable, Callable, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from task_runtime import JobRepository
from .security import _check_rate_limit

GetPool = Callable[..., Awaitable[asyncpg.Pool]]


class EnqueueJobRequest(BaseModel):
    agent: str = Field(..., min_length=1, max_length=80)
    goal: str = Field(..., min_length=1, max_length=8000)
    bot_id: Optional[str] = Field(None, max_length=64)
    ctx: dict = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10)
    max_attempts: int = Field(3, ge=1, le=10)
    step_timeout_s: int = Field(120, ge=5, le=3600)
    max_duration_s: int = Field(3600, ge=30, le=86400)
    idempotency_key: Optional[str] = Field(None, max_length=200)


def build_jobs_router(*, get_pool: GetPool, require_permission,
                      on_enqueue: Optional[Callable[[], None]] = None) -> APIRouter:
    """`on_enqueue` (opsional) dipanggil setelah enqueue untuk memicu worker
    (mis. Celery run_pending.delay); bila None, beat/worker yang memproses."""
    router = APIRouter(prefix="/jobs", tags=["durable-jobs"])
    repo = JobRepository()

    @router.post("")
    async def enqueue_job(
        body: EnqueueJobRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        await _check_rate_limit(f"jobs-enqueue:{user['org_id']}", 30)
        job = await repo.enqueue(
            pool, org_id=str(user["org_id"]), agent_name=body.agent, goal=body.goal,
            ctx=body.ctx, bot_id=body.bot_id, priority=body.priority,
            max_attempts=body.max_attempts, step_timeout_s=body.step_timeout_s,
            max_duration_s=body.max_duration_s, idempotency_key=body.idempotency_key)
        if on_enqueue is not None:
            try:
                on_enqueue()
            except Exception:
                pass
        return {"job_id": job["id"], "status": job["status"], "created_at": job.get("created_at")}

    @router.get("")
    async def list_jobs(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        status: Optional[str] = None, limit: int = 50,
    ):
        return await repo.list_jobs(pool, str(user["org_id"]), status=status, limit=limit)

    @router.get("/{job_id}")
    async def get_job(
        job_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        job = await repo.get(pool, job_id, org_id=str(user["org_id"]))
        if job is None:
            raise HTTPException(status_code=404, detail="Job tidak ditemukan")
        job["steps"] = await repo.list_steps(pool, job_id)
        return job

    async def _control(action, job_id, user, pool):
        await _check_rate_limit(f"jobs-control:{user['org_id']}", 60)
        job = await repo.request_control(pool, job_id, org_id=str(user["org_id"]), action=action)
        if job is None:
            raise HTTPException(status_code=409,
                                detail=f"Job tak bisa di-{action} pada status saat ini (atau tak ditemukan).")
        return {"job_id": job["id"], "status": job["status"]}

    @router.post("/{job_id}/cancel")
    async def cancel_job(job_id: str,
                         user: Annotated[dict, Depends(require_permission("workforce.write"))],
                         pool: asyncpg.Pool = Depends(get_pool)):
        return await _control("cancel", job_id, user, pool)

    @router.post("/{job_id}/pause")
    async def pause_job(job_id: str,
                        user: Annotated[dict, Depends(require_permission("workforce.write"))],
                        pool: asyncpg.Pool = Depends(get_pool)):
        return await _control("pause", job_id, user, pool)

    @router.post("/{job_id}/resume")
    async def resume_job(job_id: str,
                         user: Annotated[dict, Depends(require_permission("workforce.write"))],
                         pool: asyncpg.Pool = Depends(get_pool)):
        return await _control("resume", job_id, user, pool)

    return router
