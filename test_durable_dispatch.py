"""P0-D D6 — enqueue_if_durable (jembatan run_task inline → durable, flag-gated)."""
import asyncio
import uuid

import asyncpg

import feature_flags as ff
import main
from bn_platform.durable_dispatch import enqueue_if_durable
from task_runtime import JobRepository, ensure_job_schema

repo = JobRepository()


def teardown_function():
    ff.clear_all_overrides()


def _run(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "Dispatch", f"disp-{org[:8]}")
            try:
                await body(pool, org)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_flag_off_returns_none_inline_path():
    async def body(pool, org):
        # default: flag durable_runtime OFF → None (caller pakai jalur inline lama)
        assert await enqueue_if_durable(pool, org_id=org, agent_name="finance_agent", goal="g") is None
    _run(body)


def test_flag_on_enqueues_durable_job(monkeypatch):
    import celery_app

    class _Stub:
        def delay(self, *a, **k):
            return None
    monkeypatch.setattr(celery_app, "run_pending_jobs_task", _Stub())
    ff.set_override("durable_runtime", True)

    async def body(pool, org):
        job = await enqueue_if_durable(pool, org_id=org, agent_name="finance_agent", goal="laporan")
        assert job is not None and job["status"] == "queued"
        assert (await repo.get(pool, job["id"], org_id=org))["agent_name"] == "finance_agent"
    _run(body)


def test_canary_by_org(monkeypatch):
    import celery_app

    class _Stub:
        def delay(self, *a, **k):
            return None
    monkeypatch.setattr(celery_app, "run_pending_jobs_task", _Stub())

    async def body(pool, org):
        # canary hanya org tertentu (bukan org test) → None
        ff.set_override("durable_runtime", "canary:org-lain")
        assert await enqueue_if_durable(pool, org_id=org, agent_name="a", goal="g") is None
        # canary termasuk org test → enqueue
        ff.set_override("durable_runtime", f"canary:{org}")
        assert await enqueue_if_durable(pool, org_id=org, agent_name="a", goal="g") is not None
    _run(body)
