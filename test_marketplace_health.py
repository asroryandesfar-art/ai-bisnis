"""
Section 9 (Marketplace Quality Check): tests for
bn_platform.marketplace.agent_health_report(), which audits every seeded
marketplace template (system_prompt, category, knowledge_sources,
starter_questions, is_active) and was used to find + fix the 13 legacy
templates (pre-100+ catalog) that had stale category names and missing
starter_questions (see scripts/fix_marketplace_template_quality.py).

Runs against the real, live-seeded marketplace_templates table (170
templates) rather than a fixture set, since the report's whole purpose is
to audit that real data.
"""
import asyncio

import asyncpg
import pytest

import main
from bn_platform.marketplace import agent_health_report


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def test_agent_health_report_shape():
    async def body(pool):
        report = await agent_health_report(pool)
        assert report["total_agents"] > 0
        assert report["healthy_agents"] + report["agents_with_issues_count"] == report["total_agents"]
        assert 0.0 <= report["health_score_pct"] <= 100.0
        assert isinstance(report["issue_summary"], dict)
        assert isinstance(report["agents_with_issues"], list)
        for agent in report["agents_with_issues"]:
            assert agent["key"] and agent["issues"]

    _run(body)


def test_agent_health_report_legacy_templates_now_pass_category_and_starter_questions():
    """Regression for the fix applied via
    scripts/fix_marketplace_template_quality.py: these legacy template keys
    used to fail with invalid_category and/or no_starter_questions."""
    async def body(pool):
        report = await agent_health_report(pool)
        flagged_keys = {a["key"]: a["issues"] for a in report["agents_with_issues"]}
        for key in (
            "toko-online", "klinik", "pesantren", "properti", "umkm",
            "customer-service", "property", "faq", "e-commerce", "sales",
        ):
            issues = flagged_keys.get(key, [])
            assert "invalid_category" not in issues, f"{key} still has invalid_category: {issues}"
        for key in (
            "clinic", "customer-service", "e-commerce", "faq", "klinik",
            "pesantren", "properti", "property", "sales", "school",
            "toko-online", "travel", "umkm",
        ):
            issues = flagged_keys.get(key, [])
            assert "no_starter_questions" not in issues, f"{key} still has no_starter_questions: {issues}"

    _run(body)


def test_agent_health_report_health_score_above_90_pct():
    """13 legacy templates still lack knowledge_sources by design (see
    scripts/fix_marketplace_template_quality.py docstring: fabricating fake
    source URLs for them would be dishonest) — that's the one remaining,
    accepted gap, documented in the production readiness report rather than
    papered over here."""
    async def body(pool):
        report = await agent_health_report(pool)
        assert report["health_score_pct"] >= 90.0, report
        assert report["issue_summary"].get("invalid_category", 0) == 0
        assert report["issue_summary"].get("no_starter_questions", 0) == 0

    _run(body)
