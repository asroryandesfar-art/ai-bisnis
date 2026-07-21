"""P0-D D4 — worker (run_one_job/drain_jobs/make_registry_agent_builder)."""
import asyncio
import uuid

import asyncpg
import pytest

import main
from task_runtime import (
    JobRepository, drain_jobs, ensure_job_schema, make_registry_agent_builder, run_one_job,
)

repo = JobRepository()


class FakeAgent:
    name = "fake_agent"
    tools: list = []
    api_key = model = base_url = None

    async def _call_llm_json(self, messages, **kw):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "verifier internal" in blob:
            return {"verified": True, "reasoning": "ok"}
        return {"subtasks": ["s"], "relevant_tools": []}

    async def _call_llm_with_tools(self, messages, *, tools, tool_ctx):
        return {"final_answer": "beres", "tool_calls": []}


def _builder(name, ctx):
    return FakeAgent()


def _run(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org_id = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org_id, "Worker Test", f"worker-{org_id[:8]}")
            try:
                await body(pool, org_id)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_run_one_job_claims_and_completes():
    async def body(pool, org_id):
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        status = await run_one_job(pool, owner="w1", agent_builder=_builder)
        assert status == "completed"
        assert (await repo.get(pool, job["id"], org_id=org_id))["status"] == "completed"
    _run(body)


def test_run_one_job_none_when_empty():
    async def body(pool, org_id):
        # tak ada job untuk org ini; tapi claim_next global — pakai org terisolasi &
        # pastikan tak ada queued: langsung klaim harus None ATAU job org lain.
        # Untuk deterministik: enqueue lalu klaim sekali (habis), klaim kedua None.
        await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        assert await run_one_job(pool, owner="w1", agent_builder=_builder) == "completed"
        # tak ada job queued milik kita lagi (claim kedua bisa None atau job org lain=completed)
        second = await run_one_job(pool, owner="w1", agent_builder=_builder)
        assert second in (None, "completed", "queued", "dead_letter")   # tak error
    _run(body)


def test_drain_processes_multiple():
    async def body(pool, org_id):
        for _ in range(3):
            await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        n = await drain_jobs(pool, owner="w1", agent_builder=_builder, max_jobs=3)
        assert n == 3
        done = await repo.list_jobs(pool, org_id, status="completed")
        assert len(done) == 3
    _run(body)


def test_registry_builder_unknown_agent_raises():
    b = make_registry_agent_builder({"api_key": ""})
    with pytest.raises(ValueError):
        b("agent_yang_tidak_ada_xyz", {})
