"""
Section 10 (Observability): bn_platform.system_health.system_health_report()
composes existing health/metrics functions (security scan, knowledge health,
cost health, marketplace health, recent top issues, HTTP/AI metrics snapshot)
into one read-only dashboard payload for a fresh org with no usage yet --
confirms the composition doesn't blow up on an empty tenant and that each
section's shape matches its own dedicated function.
"""
import asyncio
import uuid

import asyncpg

import main
from bn_platform.system_health import system_health_report


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _setup_org(pool) -> str:
    org_id = str(uuid.uuid4())
    slug = f"e2e-system-health-{uuid.uuid4().hex[:8]}"
    await pool.execute(
        """INSERT INTO organizations (id, name, slug, plan, billing_status)
           VALUES ($1,$2,$3,'starter','trialing')""",
        org_id, "System Health Test Org", slug,
    )
    return org_id


def test_system_health_report_composes_all_sections_for_fresh_org():
    async def body(pool):
        org_id = await _setup_org(pool)
        report = await system_health_report(pool, org_id=org_id)

        assert report["org_id"] == org_id
        assert report["generated_at"]

        assert "http_requests_total" in report["http_metrics"]
        assert "db_pool_size" in report["http_metrics"]

        assert "score" in report["security"]
        assert isinstance(report["security"]["findings"], list)

        assert report["top_issues_7d"] == []

        assert report["knowledge_health"]["org_id"] == org_id
        assert report["knowledge_health"]["total_urls"] == 0

        assert report["marketplace_health"]["total_agents"] > 0

        assert report["cost_health"]["monthly_cost"] == 0.0
        assert "budget" in report["cost_health"]

    _run(body)
