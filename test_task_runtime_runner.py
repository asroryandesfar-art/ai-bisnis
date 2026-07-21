"""P0-D D2/D3 — DurableJobRunner (checkpoint/resume/cancel/retry) vs Postgres nyata.

Agent di-fake (tanpa LLM) via agent_builder; pool/checkpoint nyata. Menguji jalur
completed, resume (skip step 'done'), cancel cooperative, dan retry/DLQ saat error.
"""
import asyncio
import uuid

import asyncpg

import main
from task_runtime import DurableJobRunner, JobRepository, ensure_job_schema

repo = JobRepository()


class FakeAgent:
    name = "fake_agent"
    tools: list = []
    api_key = model = base_url = None

    def __init__(self, subtasks=None, verified=True, raise_on_plan=False):
        self.subtasks = subtasks or ["subtask satu"]
        self.verified = verified
        self.raise_on_plan = raise_on_plan
        self.calls = {"plan": 0, "verify": 0, "subtask": 0}

    async def _call_llm_json(self, messages, **kw):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "verifier internal" in blob:
            self.calls["verify"] += 1
            return {"verified": self.verified, "reasoning": "ok"}
        self.calls["plan"] += 1
        if self.raise_on_plan:
            raise RuntimeError("plan boom")
        return {"subtasks": self.subtasks, "relevant_tools": []}

    async def _call_llm_with_tools(self, messages, *, tools, tool_ctx):
        self.calls["subtask"] += 1
        return {"final_answer": "beres", "tool_calls": []}


def _run(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org_id = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org_id, "Runner Test", f"runner-{org_id[:8]}")
            try:
                await body(pool, org_id)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_full_run_completes_and_persists():
    async def body(pool, org_id):
        fake = FakeAgent(subtasks=["a", "b"])
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="kerjakan")
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)
        runner = DurableJobRunner(repo, agent_builder=lambda name, ctx: fake)
        status = await runner.run(pool, claimed)
        assert status == "completed"
        final = await repo.get(pool, job["id"], org_id=org_id)
        assert final["status"] == "completed" and final["progress_pct"] == 100
        assert final["result_execution_id"] is not None
        assert fake.calls == {"plan": 1, "verify": 1, "subtask": 2}
        # step ter-checkpoint: plan, subtask×2, verify, report
        steps = await repo.list_steps(pool, job["id"])
        assert [s["kind"] for s in steps] == ["plan", "subtask", "subtask", "verify", "report"]
        # laporan final tertulis ke agent_task_executions (backward-compat)
        n = await pool.fetchval("SELECT count(*) FROM agent_task_executions WHERE id=$1",
                                uuid.UUID(final["result_execution_id"]))
        assert n == 1
    _run(body)


def test_resume_skips_completed_plan_step():
    async def body(pool, org_id):
        fake = FakeAgent(subtasks=["x"])
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        await repo.claim_next(pool, owner="w1", lease_s=60)
        # simulasikan crash SETELAH plan: seed step plan 'done' + state
        await repo.save_step(pool, job_id=job["id"], seq=0, kind="plan", status="done",
                             checkpoint={"_phase": "subtask", "plan": {"subtasks": ["x"], "relevant_tools": []},
                                         "subtasks": ["x"], "relevant_tools": [],
                                         "subtask_results": [], "all_tool_calls": [], "sub_i": 0})
        claimed = await repo.get(pool, job["id"], org_id=org_id)
        runner = DurableJobRunner(repo, agent_builder=lambda name, ctx: fake)
        status = await runner.run(pool, claimed)
        assert status == "completed"
        assert fake.calls["plan"] == 0            # RESUME: plan tak dijalankan ulang
        assert fake.calls["subtask"] == 1
    _run(body)


def test_cancel_at_boundary():
    async def body(pool, org_id):
        fake = FakeAgent()
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)
        await repo.request_control(pool, job["id"], org_id=org_id, action="cancel")
        claimed = await repo.get(pool, job["id"], org_id=org_id)      # status=cancelling
        runner = DurableJobRunner(repo, agent_builder=lambda name, ctx: fake)
        status = await runner.run(pool, claimed)
        assert status == "cancelled" and fake.calls["plan"] == 0
        assert (await repo.get(pool, job["id"], org_id=org_id))["status"] == "cancelled"
    _run(body)


def test_error_retries_then_dlq():
    async def body(pool, org_id):
        fake = FakeAgent(raise_on_plan=True)
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g", max_attempts=3)
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)   # attempts=1
        runner = DurableJobRunner(repo, agent_builder=lambda name, ctx: fake)
        status = await runner.run(pool, claimed)
        assert status == "queued"                 # attempts(1) < max(3) → retry
        got = await repo.get(pool, job["id"], org_id=org_id)
        assert got["status"] == "queued" and "plan boom" in (got["last_error"] or "")
        # habiskan attempts → DLQ
        await pool.execute("UPDATE agent_jobs SET attempts=3 WHERE id=$1", job["id"])
        claimed2 = await repo.get(pool, job["id"], org_id=org_id)
        status2 = await runner.run(pool, claimed2)
        assert status2 == "dead_letter"
    _run(body)
