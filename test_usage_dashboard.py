"""
Tests for the Cost Control / Usage Dashboard additions to
bn_platform/cost_intelligence.py::summary() — image generation usage,
storage usage, and per-agent latency/success rate. Composition over
existing tables (image_generations, documents, agent_executions), tested
against real Postgres (same rationale as test_knowledge_health.py: these
are aggregate queries across real tables, simplest/most trustworthy to
verify against the real DB rather than a hand-built FakePool).
"""
import asyncio
import uuid

import asyncpg
import pytest

import main
from bn_platform.cost_intelligence import build_cost_intelligence_router


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


async def _setup_org(pool) -> str:
    org_id = str(uuid.uuid4())
    slug = f"e2e-usage-dash-{uuid.uuid4().hex[:8]}"
    await pool.execute(
        """INSERT INTO organizations (id, name, slug, plan, billing_status)
           VALUES ($1,$2,$3,'starter','trialing')""",
        org_id, "Usage Dashboard Test Org", slug,
    )
    return org_id


async def _setup_bot(pool, org_id: str) -> str:
    bot_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO bots (id, org_id, name, status, primary_color, greeting, language, system_prompt)
           VALUES ($1,$2,'Usage Dashboard Test Bot','active','#0066FF','Halo','id','Kamu adalah asisten.')""",
        bot_id, org_id,
    )
    return bot_id


async def _setup_conversation(pool, *, org_id: str, bot_id: str) -> str:
    conv_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO conversations (id, bot_id, org_id, channel) VALUES ($1,$2,$3,'widget')""",
        conv_id, bot_id, org_id,
    )
    return conv_id


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _get_pool_noop():
    raise AssertionError("get_pool should not be called when pool is injected directly")


async def _get_current_user_noop():
    raise AssertionError("get_current_user should not be called when user is injected directly")


def test_summary_includes_image_storage_and_agent_performance():
    async def body(pool):
        org_id = await _setup_org(pool)
        bot_id = await _setup_bot(pool, org_id)

        await pool.execute(
            """INSERT INTO image_generations
                   (org_id, kind, provider, model, prompt, image_url, status, estimated_cost)
               VALUES ($1,'generate','replicate','flux-2-pro','a logo','http://x/1.png','completed',0.05)""",
            org_id,
        )
        await pool.execute(
            """INSERT INTO image_generations
                   (org_id, kind, provider, model, prompt, image_url, status, estimated_cost)
               VALUES ($1,'generate','replicate','flux-2-pro','a poster','http://x/2.png','completed',0.05)""",
            org_id,
        )
        doc_id = str(uuid.uuid4())
        await pool.execute(
            """INSERT INTO documents (id, org_id, filename, file_size, mime_type, status)
               VALUES ($1,$2,'a.txt',12345,'text/plain','ready')""",
            doc_id, org_id,
        )
        async def _insert_agent_execution(duration_ms: int, status: str) -> None:
            trace_id = str(uuid.uuid4())
            conv_id = await _setup_conversation(pool, org_id=org_id, bot_id=bot_id)
            await pool.execute(
                """INSERT INTO ai_traces (id, tenant_id, conversation_id, user_question, final_answer, status)
                   VALUES ($1,$2,$3,'test question','test answer','completed')""",
                trace_id, org_id, conv_id,
            )
            await pool.execute(
                """INSERT INTO agent_executions
                       (id, trace_id, tenant_id, conversation_id, agent_name, sequence_no,
                        execution_start, execution_end, duration_ms, status)
                   VALUES ($1,$2,$3,$4,'cs_agent',1,NOW(),NOW(),$5,$6)""",
                str(uuid.uuid4()), trace_id, org_id, conv_id, duration_ms, status,
            )

        await _insert_agent_execution(120, "success")
        await _insert_agent_execution(80, "error")

        router = build_cost_intelligence_router(get_pool=_get_pool_noop, get_current_user=_get_current_user_noop)
        endpoint = _route(router, "/summary", "GET")
        result = await endpoint(user={"org_id": org_id}, pool=pool)

        assert result["image_generation_usage"]["monthly_count"] == 2
        assert result["image_generation_usage"]["monthly_cost"] == pytest.approx(0.10)

        assert result["storage_usage"]["document_bytes"] == 12345
        assert result["storage_usage"]["document_count"] == 1

        agent_perf = {row["agent_name"]: row for row in result["agent_performance"]}
        assert agent_perf["cs_agent"]["calls"] == 2
        assert agent_perf["cs_agent"]["avg_latency_ms"] == pytest.approx(100, abs=1)
        assert agent_perf["cs_agent"]["success_rate_pct"] == pytest.approx(50.0)

    _run(body)


def test_summary_handles_org_with_no_usage_gracefully():
    async def body(pool):
        org_id = await _setup_org(pool)
        router = build_cost_intelligence_router(get_pool=_get_pool_noop, get_current_user=_get_current_user_noop)
        endpoint = _route(router, "/summary", "GET")
        result = await endpoint(user={"org_id": org_id}, pool=pool)

        assert result["image_generation_usage"] == {"monthly_count": 0, "monthly_cost": 0.0}
        assert result["storage_usage"] == {"document_bytes": 0, "document_count": 0}
        assert result["agent_performance"] == []

    _run(body)
