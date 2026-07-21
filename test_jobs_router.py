"""P0-D D5 — bn_platform/jobs_router (Durable Task Runtime API).

Pola sama test_casper_engineer_router: panggil endpoint LANGSUNG (bukan TestClient)
dengan pool Postgres nyata dalam satu event loop → hindari isu pool loop-bound.
"""
import asyncio
import uuid

import asyncpg
import pytest
from fastapi import HTTPException

import main
from task_runtime import ensure_job_schema
from bn_platform.jobs_router import build_jobs_router, EnqueueJobRequest


def _router():
    async def get_pool():
        raise RuntimeError("unused in direct-call test")

    def require_permission(key):
        async def _checker(user=None, pool=None):
            return {"org_id": "org-x", "id": "user-1"}
        return _checker

    return build_jobs_router(get_pool=get_pool, require_permission=require_permission)


def _ep(router, suffix, method):
    for r in router.routes:
        if r.path.endswith(suffix) and method in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"route not found: {method} {suffix}")


def test_routes_exist():
    router = _router()
    have = {r.path for r in router.routes}
    assert any(p.endswith("/jobs") for p in have)
    assert any(p.endswith("/jobs/{job_id}") for p in have)
    assert any(p.endswith("/jobs/{job_id}/cancel") for p in have)
    assert any(p.endswith("/jobs/{job_id}/pause") for p in have)
    assert any(p.endswith("/jobs/{job_id}/resume") for p in have)


def test_enqueue_get_list_cancel():
    router = _router()
    enqueue = _ep(router, "/jobs", "POST")
    get_job = _ep(router, "/jobs/{job_id}", "GET")
    list_jobs = _ep(router, "/jobs", "GET")
    cancel_job = _ep(router, "/jobs/{job_id}/cancel", "POST")

    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "JobsAPI", f"japi-{org[:8]}")
            user = {"org_id": org, "id": "u1"}
            try:
                res = await enqueue(body=EnqueueJobRequest(agent="fake_agent", goal="kerjakan"),
                                    user=user, pool=pool)
                jid = res["job_id"]
                assert res["status"] == "queued"
                got = await get_job(job_id=jid, user=user, pool=pool)
                assert got["id"] == jid and "steps" in got and got["steps"] == []
                lst = await list_jobs(user=user, pool=pool, status=None, limit=50)
                assert any(j["id"] == jid for j in lst)
                # idempotency: enqueue key sama → job sama
                r2 = await enqueue(body=EnqueueJobRequest(agent="a", goal="g", idempotency_key="idem1"),
                                   user=user, pool=pool)
                r3 = await enqueue(body=EnqueueJobRequest(agent="a", goal="g", idempotency_key="idem1"),
                                   user=user, pool=pool)
                assert r2["job_id"] == r3["job_id"]
                c = await cancel_job(job_id=jid, user=user, pool=pool)
                assert c["status"] == "cancelling"
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()

    asyncio.run(body())


def test_get_missing_returns_404():
    router = _router()
    get_job = _ep(router, "/jobs/{job_id}", "GET")

    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            with pytest.raises(HTTPException) as ei:
                await get_job(job_id=str(uuid.uuid4()),
                              user={"org_id": str(uuid.uuid4()), "id": "u"}, pool=pool)
            assert ei.value.status_code == 404
        finally:
            await pool.close()

    asyncio.run(body())


def test_cancel_missing_returns_409():
    router = _router()
    cancel_job = _ep(router, "/jobs/{job_id}/cancel", "POST")

    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            with pytest.raises(HTTPException) as ei:
                await cancel_job(job_id=str(uuid.uuid4()),
                                 user={"org_id": str(uuid.uuid4()), "id": "u"}, pool=pool)
            assert ei.value.status_code == 409
        finally:
            await pool.close()

    asyncio.run(body())


def test_retry_dlq_requeues():
    from task_runtime import JobRepository
    repo = JobRepository()
    router = _router()
    retry = _ep(router, "/jobs/{job_id}/retry", "POST")

    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "Retry", f"retry-{org[:8]}")
            user = {"org_id": org, "id": "u1"}
            try:
                job = await repo.enqueue(pool, org_id=org, agent_name="a", goal="g")
                await pool.execute("UPDATE agent_jobs SET status='dead_letter', attempts=3 WHERE id=$1", job["id"])
                res = await retry(job_id=job["id"], user=user, pool=pool)
                assert res["status"] == "queued"
                fresh = await repo.get(pool, job["id"], org_id=org)
                assert fresh["attempts"] == 0 and fresh["dlq_reason"] is None
                # bukan dead_letter lagi → 409
                with pytest.raises(HTTPException) as ei:
                    await retry(job_id=job["id"], user=user, pool=pool)
                assert ei.value.status_code == 409
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()

    asyncio.run(body())


def test_stream_emits_progress_and_done_for_terminal_job():
    from task_runtime import JobRepository
    repo = JobRepository()
    router = _router()
    enqueue = _ep(router, "/jobs", "POST")
    stream = _ep(router, "/jobs/{job_id}/stream", "GET")

    async def body():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "Stream", f"stream-{org[:8]}")
            user = {"org_id": org, "id": "u1"}
            try:
                r = await enqueue(body=EnqueueJobRequest(agent="a", goal="g"), user=user, pool=pool)
                await pool.execute("UPDATE agent_jobs SET status='completed', progress_pct=100 WHERE id=$1",
                                   r["job_id"])
                resp = await stream(job_id=r["job_id"], user=user, pool=pool, poll_s=0.05, max_polls=5)
                chunks = []
                async for c in resp.body_iterator:
                    chunks.append(c if isinstance(c, str) else c.decode())
                out = "".join(chunks)
                assert "event: progress" in out and "event: done" in out and "completed" in out
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()

    asyncio.run(body())
