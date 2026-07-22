"""bn_platform/runtime_observability_router.py — API observability durable runtime (P2-C).

Dashboard operator realtime untuk durable runtime (P0-D) + skor Evaluation (P1-D):
antrian/backlog, in-flight, worker aktif (lease), job macet (lease kedaluwarsa),
DLQ, throughput, dan tren skor per-agen. Read-only, RBAC-gated (workforce.read),
org-scoped. Pola factory-DI (tanpa import main). JANGAN `from __future__` (Depends).

Melengkapi (bukan menggantikan) `/observability` (AI traces/token/cost) — ini
fokus ke RUNTIME (queue/worker/eval), subsistem yang belum punya view operator.
"""
import asyncio
import json
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from task_runtime import RuntimeMonitor

GetPool = Callable[..., Awaitable[asyncpg.Pool]]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def build_runtime_observability_router(*, get_pool: GetPool, require_permission) -> APIRouter:
    router = APIRouter(prefix="/runtime", tags=["runtime-observability"])
    monitor = RuntimeMonitor()

    @router.get("/health")
    async def health(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        window_hours: int = Query(24, ge=1, le=720),
    ):
        return await monitor.health_snapshot(pool, str(user["org_id"]), window_hours=window_hours)

    @router.get("/evaluations")
    async def evaluations(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        window_hours: int = Query(24, ge=1, le=720),
    ):
        return await monitor.evaluation_trends(pool, str(user["org_id"]), window_hours=window_hours)

    @router.get("/stream")
    async def stream(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        window_hours: int = Query(24, ge=1, le=720),
        interval_s: float = Query(3.0, ge=1.0, le=30.0),
        max_ticks: int = Query(200, ge=1, le=1200),
    ):
        """Snapshot health berkala via SSE (realtime). Klien boleh reconnect."""
        org_id = str(user["org_id"])

        async def gen():
            for _ in range(max_ticks):
                try:
                    snap = await monitor.health_snapshot(pool, org_id, window_hours=window_hours)
                    yield _sse("health", snap)
                except Exception:
                    yield _sse("error", {"error": "snapshot gagal"})
                    return
                await asyncio.sleep(interval_s)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return router
