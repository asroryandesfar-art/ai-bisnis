"""P0-D D2/D3 — DurableJobRunner (checkpoint/resume/cancel/retry) vs Postgres nyata.

Agent di-fake (tanpa LLM) via agent_builder; pool/checkpoint nyata. Menguji jalur
completed, resume (skip step 'done'), cancel cooperative, dan retry/DLQ saat error.
"""
import asyncio
import uuid

import asyncpg

import feature_flags as ff
import main
from long_term_memory import SemanticMemory, ensure_memory_schema
from task_runtime import DurableJobRunner, JobRepository, ensure_job_schema

repo = JobRepository()


def teardown_function():
    ff.clear_all_overrides()


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


class CogAgent:
    """Fake agent dgn reason() (Cognitive Loop di-stub) — uji integrasi runner."""
    name = "cog_agent"
    tools: list = []
    api_key = model = base_url = None

    def __init__(self, accepted=True):
        self.reason_calls = 0
        self.accepted = accepted

    async def reason(self, goal, **kw):
        self.reason_calls += 1
        return {"goal": goal, "answer": "jawaban kognitif", "accepted": self.accepted,
                "final_score": 0.9 if self.accepted else 0.4, "iterations": 2,
                "stop_reason": "accepted" if self.accepted else "max_iters", "history": [{"i": 0}]}


def test_cognitive_mode_durable_job_completes():
    ff.set_override("cognitive_loop", True)

    async def body(pool, org_id):
        cog = CogAgent()
        job = await repo.enqueue(pool, org_id=org_id, agent_name="cog_agent", goal="g",
                                 ctx={"mode": "cognitive", "use_tools": False})
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)
        runner = DurableJobRunner(repo, agent_builder=lambda n, c: cog)
        status = await runner.run(pool, claimed)
        assert status == "completed" and cog.reason_calls == 1
        final = await repo.get(pool, job["id"], org_id=org_id)
        assert final["status"] == "completed" and final["result_execution_id"] is not None
        steps = await repo.list_steps(pool, job["id"])
        assert [s["kind"] for s in steps] == ["cognitive"]
        assert steps[0]["output"]["final_score"] == 0.9
        n = await pool.fetchval("SELECT count(*) FROM agent_task_executions WHERE id=$1",
                                uuid.UUID(final["result_execution_id"]))
        assert n == 1
    _run(body)


def test_cognitive_flag_off_falls_through_to_linear():
    # mode=cognitive TAPI flag OFF → jalur linear lama (default aman)
    async def body(pool, org_id):
        fake = FakeAgent(subtasks=["x"])            # punya _call_llm_json/_with_tools (linear)
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g",
                                 ctx={"mode": "cognitive"})
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)
        runner = DurableJobRunner(repo, agent_builder=lambda n, c: fake)
        status = await runner.run(pool, claimed)
        assert status == "completed"
        kinds = [s["kind"] for s in await repo.list_steps(pool, job["id"])]
        assert kinds == ["plan", "subtask", "verify", "report"]   # LINEAR, bukan cognitive
    _run(body)


def test_cognitive_resume_reuses_saved_step():
    ff.set_override("cognitive_loop", True)

    async def body(pool, org_id):
        cog = CogAgent()
        job = await repo.enqueue(pool, org_id=org_id, agent_name="cog_agent", goal="g",
                                 ctx={"mode": "cognitive"})
        await repo.claim_next(pool, owner="w1", lease_s=60)
        # simulasikan crash SETELAH loop selesai, SEBELUM finalize: step cognitive 'done'
        await repo.save_step(pool, job_id=job["id"], seq=0, kind="cognitive", status="done",
                             checkpoint={"_phase": "done"},
                             output={"result": {"answer": "tersimpan", "accepted": True,
                                                 "final_score": 0.8, "iterations": 1,
                                                 "stop_reason": "accepted"}})
        claimed = await repo.get(pool, job["id"], org_id=org_id)
        runner = DurableJobRunner(repo, agent_builder=lambda n, c: cog)
        status = await runner.run(pool, claimed)
        assert status == "completed" and cog.reason_calls == 0     # RESUME: loop tak diulang
        final = await repo.get(pool, job["id"], org_id=org_id)
        row = await pool.fetchrow("SELECT report FROM agent_task_executions WHERE id=$1",
                                  uuid.UUID(final["result_execution_id"]))
        assert row["report"] == "tersimpan"
    _run(body)


def test_cognitive_recalls_and_stores_long_term_memory():
    ff.set_override("cognitive_loop", True)
    ff.set_override("long_term_memory", True)

    async def fake_embed(text):
        v = [0.0] * 384
        v[0] = 1.0 if "apel" in (text or "").lower() else 0.0
        v[2] = 0.0 if "apel" in (text or "").lower() else 1.0
        return v

    memory = SemanticMemory(embed_fn=fake_embed)
    captured = {}

    class CogA:
        name = "cog_agent"
        tools: list = []
        api_key = model = base_url = None

        async def reason(self, goal, *, context=None, **kw):
            captured["ctx"] = context or {}
            return {"answer": "rekomendasi: apel merah", "accepted": True,
                    "final_score": 0.9, "iterations": 1, "stop_reason": "accepted"}

    async def body(pool, org_id):
        await ensure_memory_schema(pool)
        # memori semantik relevan yang harus di-recall (subject = nama agent)
        await memory.store(pool, org_id=org_id, scope="semantic", subject="cog_agent",
                           content="pelanggan sangat menyukai apel merah")
        job = await repo.enqueue(pool, org_id=org_id, agent_name="cog_agent",
                                 goal="beri rekomendasi apel", ctx={"mode": "cognitive", "use_tools": False})
        claimed = await repo.claim_next(pool, owner="w1", lease_s=60)
        runner = DurableJobRunner(repo, agent_builder=lambda n, c: CogA(), memory=memory)
        status = await runner.run(pool, claimed)
        assert status == "completed"
        # RECALL: memori relevan ter-inject ke context reasoning
        assert "apel merah" in captured["ctx"].get("knowledge_base_context", "")
        # STORE: pengalaman disimpan sbg episodic memory
        eps = await memory.retrieve(pool, org_id=org_id, query="apel", scope="episodic", subject="cog_agent")
        assert any("rekomendasi: apel merah" in e["content"] for e in eps)
    _run(body)


def test_chaos_crash_recovery_then_resume():
    """Worker A klaim + selesai 'plan' lalu CRASH (lease kadaluarsa). Recovery:
    find_expired → worker B claim_next (attempts++) → runner RESUME dari checkpoint
    (plan tak diulang) → completed. Membuktikan tahan-crash end-to-end."""
    async def body(pool, org_id):
        fake = FakeAgent(subtasks=["x"])
        job = await repo.enqueue(pool, org_id=org_id, agent_name="fake_agent", goal="g")
        # worker A klaim (attempts=1)
        await repo.claim_next(pool, owner="A", lease_s=30)
        # A menyelesaikan step plan lalu "crash": seed checkpoint + lease kadaluarsa
        await repo.save_step(pool, job_id=job["id"], seq=0, kind="plan", status="done",
                             checkpoint={"_phase": "subtask", "plan": {"subtasks": ["x"], "relevant_tools": []},
                                         "subtasks": ["x"], "relevant_tools": [],
                                         "subtask_results": [], "all_tool_calls": [], "sub_i": 0})
        await pool.execute("UPDATE agent_jobs SET lease_until=NOW()-INTERVAL '5 seconds' WHERE id=$1", job["id"])
        # recovery: job muncul sebagai expired; worker B merebut
        assert any(j["id"] == job["id"] for j in await repo.find_expired(pool))
        reclaimed = await repo.claim_next(pool, owner="B", lease_s=30)
        assert reclaimed["id"] == job["id"] and reclaimed["attempts"] == 2 and reclaimed["lease_owner"] == "B"
        # resume → selesai tanpa mengulang plan
        runner = DurableJobRunner(repo, agent_builder=lambda name, ctx: fake)
        status = await runner.run(pool, reclaimed)
        assert status == "completed" and fake.calls["plan"] == 0 and fake.calls["subtask"] == 1
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
