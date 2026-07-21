"""P0-D D1 — JobRepository terhadap Postgres nyata (agent_jobs/agent_job_steps).

Pola sama test_memory_store_persistence: pool langsung dari main.cfg.database_url,
org test ephemeral (dibersihkan CASCADE). Menguji enqueue/idempotency/claim
(SKIP LOCKED)/lease/recovery/checkpoint/resume/control.
"""
import asyncio
import uuid

import asyncpg

import main
from task_runtime import JobRepository, ensure_job_schema

repo = JobRepository()


def _run(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            org_id = str(uuid.uuid4())
            await pool.execute(
                "INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                org_id, "JobRT Test", f"jobrt-{org_id[:8]}")
            try:
                await body(pool, org_id)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_enqueue_and_get():
    async def body(pool, org_id):
        job = await repo.enqueue(pool, org_id=org_id, agent_name="finance_agent",
                                 goal="buat laporan", ctx={"foo": "bar"}, priority=3)
        assert job["status"] == "queued" and job["attempts"] == 0
        assert job["ctx"] == {"foo": "bar"} and job["priority"] == 3
        got = await repo.get(pool, job["id"], org_id=org_id)
        assert got["id"] == job["id"]
        assert await repo.get(pool, job["id"], org_id=str(uuid.uuid4())) is None   # org scoping
    _run(body)


def test_enqueue_idempotent():
    async def body(pool, org_id):
        a = await repo.enqueue(pool, org_id=org_id, agent_name="x", goal="g",
                               idempotency_key="k1")
        b = await repo.enqueue(pool, org_id=org_id, agent_name="x", goal="g",
                               idempotency_key="k1")
        assert a["id"] == b["id"]                       # tak buat duplikat
    _run(body)


def test_claim_skip_locked_and_attempts():
    async def body(pool, org_id):
        j1 = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g1", priority=1)
        j2 = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g2", priority=2)
        c1 = await repo.claim_next(pool, owner="w1", lease_s=30)
        c2 = await repo.claim_next(pool, owner="w2", lease_s=30)
        claimed_ids = {c1["id"], c2["id"]}
        assert claimed_ids == {j1["id"], j2["id"]}      # dua job berbeda
        assert c1["status"] == "running" and c1["attempts"] == 1
        assert c1["id"] == j1["id"]                     # prioritas 1 lebih dulu
        assert await repo.claim_next(pool, owner="w3", lease_s=30) is None   # habis
    _run(body)


def test_lease_renew_owner_guard():
    async def body(pool, org_id):
        await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g")
        c = await repo.claim_next(pool, owner="w1", lease_s=30)
        assert await repo.renew_lease(pool, c["id"], owner="w1", lease_s=60) is True
        assert await repo.renew_lease(pool, c["id"], owner="other", lease_s=60) is False
    _run(body)


def test_recovery_reclaims_expired_lease():
    async def body(pool, org_id):
        await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g")
        c = await repo.claim_next(pool, owner="dead", lease_s=30)
        # simulasikan worker mati: lease kadaluarsa
        await pool.execute("UPDATE agent_jobs SET lease_until=NOW()-INTERVAL '5 seconds' WHERE id=$1", c["id"])
        expired = await repo.find_expired(pool)
        assert any(j["id"] == c["id"] for j in expired)
        # worker lain merebut (resume): attempts naik jadi 2, owner baru
        again = await repo.claim_next(pool, owner="w2", lease_s=30)
        assert again["id"] == c["id"] and again["attempts"] == 2 and again["lease_owner"] == "w2"
    _run(body)


def test_checkpoint_and_resume_point():
    async def body(pool, org_id):
        job = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g")
        await repo.save_step(pool, job_id=job["id"], seq=0, kind="plan",
                             checkpoint={"subtasks": ["x"]}, output={"ok": True})
        await repo.save_step(pool, job_id=job["id"], seq=1, kind="subtask",
                             checkpoint={"done": 1}, tool_calls=[{"tool": "t"}])
        steps = await repo.list_steps(pool, job["id"])
        assert [s["seq"] for s in steps] == [0, 1]
        last = await repo.latest_done_step(pool, job["id"])
        assert last["seq"] == 1 and last["checkpoint"] == {"done": 1}
        # UPSERT: simpan ulang seq=1 tak menggandakan
        await repo.save_step(pool, job_id=job["id"], seq=1, kind="subtask", checkpoint={"done": 2})
        steps2 = await repo.list_steps(pool, job["id"])
        assert len(steps2) == 2 and steps2[1]["checkpoint"] == {"done": 2}
    _run(body)


def test_set_status_and_control():
    async def body(pool, org_id):
        job = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g")
        rid = str(uuid.uuid4())
        done = await repo.set_status(pool, job["id"], "completed", progress_pct=100,
                                     result_execution_id=rid)
        assert done["status"] == "completed" and done["progress_pct"] == 100
        assert done["result_execution_id"] == rid
        # control: cancel
        j2 = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g2")
        c = await repo.request_control(pool, j2["id"], org_id=org_id, action="cancel")
        assert c["status"] == "cancelling"
        # resume hanya dari paused
        assert await repo.request_control(pool, j2["id"], org_id=org_id, action="resume") is None
    _run(body)


def test_list_jobs_filter():
    async def body(pool, org_id):
        await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g1")
        j2 = await repo.enqueue(pool, org_id=org_id, agent_name="a", goal="g2")
        await repo.set_status(pool, j2["id"], "completed")
        allj = await repo.list_jobs(pool, org_id)
        assert len(allj) == 2
        done = await repo.list_jobs(pool, org_id, status="completed")
        assert len(done) == 1 and done[0]["id"] == j2["id"]
    _run(body)
