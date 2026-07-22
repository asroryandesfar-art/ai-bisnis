"""P2-C — Runtime Observability: agregasi agent_jobs + task_evaluations + router.

Pola sama test_jobs_router: pool Postgres nyata, org efemeral, isi baris job/eval
langsung, panggil monitor & endpoint LANGSUNG dalam satu event loop.
"""
import asyncio
import uuid

import asyncpg

import main
from task_runtime import ensure_job_schema, RuntimeMonitor
from evaluation import ensure_eval_schema


def _run_db(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_job_schema(pool)
            await ensure_eval_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "RtObs", f"rto-{org[:8]}")
            try:
                await body(pool, org)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


async def _job(pool, org, status, *, lease_owner=None, lease_delta_s=None, updated_ago=None):
    """Sisipkan satu agent_jobs dengan status & lease/updated_at terkontrol."""
    jid = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO agent_jobs (id, org_id, agent_name, goal, status, lease_owner,
               lease_until, updated_at)
           VALUES ($1,$2,'finance_agent','g',$3,$4,
                   CASE WHEN $5::float IS NULL THEN NULL ELSE NOW() + make_interval(secs => $5::float) END,
                   NOW() - make_interval(secs => $6::float))""",
        jid, org, status, lease_owner,
        lease_delta_s, float(updated_ago or 0),
    )
    return jid


def test_health_snapshot_queue_inflight_stalled_dlq():
    async def body(pool, org):
        await _job(pool, org, "queued")
        await _job(pool, org, "queued")
        await _job(pool, org, "running", lease_owner="w1", lease_delta_s=60)      # in-flight
        await _job(pool, org, "running", lease_owner="w2", lease_delta_s=-30)     # stalled (lease lewat)
        await _job(pool, org, "dead_letter")
        await _job(pool, org, "completed", updated_ago=10)                        # completed 1h & window
        await _job(pool, org, "failed", updated_ago=10)                           # failed 1h & window

        snap = await RuntimeMonitor().health_snapshot(pool, org, window_hours=24)
        assert snap["queue"]["queued"] == 2 and snap["queue"]["running"] == 2
        assert snap["backlog"] == 2
        assert snap["in_flight"] == 1
        assert snap["stalled"] == 1
        assert snap["dead_letter"] == 1
        assert snap["throughput"]["completed_1h"] == 1
        assert snap["throughput"]["failed_1h"] == 1
        assert snap["throughput"]["success_rate"] == 50.0
        # worker aktif hanya yang lease valid + running
        owners = {w["lease_owner"]: w["active_jobs"] for w in snap["workers"]}
        assert owners == {"w1": 1}
        # semua status muncul (0-filled)
        assert set(snap["queue"]) >= {"paused", "cancelled", "completed"}
    _run_db(body)


def test_health_snapshot_empty_org():
    async def body(pool, org):
        snap = await RuntimeMonitor().health_snapshot(pool, org)
        assert snap["backlog"] == 0 and snap["in_flight"] == 0 and snap["stalled"] == 0
        assert snap["throughput"]["success_rate"] == 0.0
        assert snap["workers"] == []
        assert snap["evaluation"] == {"avg_overall": 0.0, "count": 0, "judged_pct": 0.0}
    _run_db(body)


async def _eval(pool, org, agent, overall, judged):
    await pool.execute(
        """INSERT INTO task_evaluations (org_id, agent_name, goal, scores, overall, judged)
           VALUES ($1,$2,'g','{}'::jsonb,$3,$4)""",
        org, agent, overall, judged,
    )


def test_evaluation_summary_and_trends():
    async def body(pool, org):
        await _eval(pool, org, "finance_agent", 0.9, True)
        await _eval(pool, org, "finance_agent", 0.7, False)
        await _eval(pool, org, "hr_agent", 0.5, True)

        snap = await RuntimeMonitor().health_snapshot(pool, org, window_hours=24)
        assert snap["evaluation"]["count"] == 3
        assert abs(snap["evaluation"]["avg_overall"] - (0.9 + 0.7 + 0.5) / 3) < 1e-6
        assert abs(snap["evaluation"]["judged_pct"] - (2 / 3 * 100)) < 0.1

        trends = await RuntimeMonitor().evaluation_trends(pool, org, window_hours=24)
        by = {t["agent_name"]: t for t in trends}
        assert by["finance_agent"]["n"] == 2
        assert abs(by["finance_agent"]["avg_overall"] - 0.8) < 1e-6
        assert by["finance_agent"]["min_overall"] == 0.7 and by["finance_agent"]["max_overall"] == 0.9
        assert by["finance_agent"]["judged_pct"] == 50.0
        assert by["hr_agent"]["n"] == 1
    _run_db(body)


# ── Router: panggil endpoint langsung ─────────────────────────────────────────
def _router():
    from bn_platform.runtime_observability_router import build_runtime_observability_router

    async def get_pool():
        raise RuntimeError("unused")

    def require_permission(key):
        async def _checker(user=None, pool=None):
            return {"org_id": "unused", "id": "u1"}
        return _checker

    return build_runtime_observability_router(get_pool=get_pool, require_permission=require_permission)


def _ep(router, suffix, method):
    for r in router.routes:
        if r.path.endswith(suffix) and method in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"route not found: {method} {suffix}")


def test_router_routes_exist():
    have = {r.path for r in _router().routes}
    assert any(p.endswith("/runtime/health") for p in have)
    assert any(p.endswith("/runtime/evaluations") for p in have)
    assert any(p.endswith("/runtime/stream") for p in have)


def test_router_health_and_evaluations():
    router = _router()
    health = _ep(router, "/runtime/health", "GET")
    evals = _ep(router, "/runtime/evaluations", "GET")

    async def body(pool, org):
        user = {"org_id": org, "id": "u1"}
        await _job(pool, org, "queued")
        await _eval(pool, org, "finance_agent", 0.9, True)
        h = await health(user=user, pool=pool, window_hours=24)
        assert h["backlog"] == 1 and h["evaluation"]["count"] == 1
        t = await evals(user=user, pool=pool, window_hours=24)
        assert any(x["agent_name"] == "finance_agent" for x in t)
    _run_db(body)
