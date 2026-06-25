"""Tests untuk Marketing Agent (AI Workforce Phase 2): marketing_agent.py
(persistence helpers + MarketingAgent NLP content generation) dan
bn_platform/marketing.py (router RBAC gating + endpoint behavior).

Mengikuti pola FakePool + _route dari test_finance_agent.py -- tidak ada
panggilan Groq atau database sungguhan."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import marketing_agent as ma
from bn_platform.marketing import (
    build_marketing_router, ContentCreateRequest, CampaignCreateRequest, RunTaskRequest,
)


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakePool:
    def __init__(self, fetchval_results=None, fetchrow_results=None, fetch_results=None):
        self.calls = []
        self._fetchval_results = list(fetchval_results or [])
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetch_results = list(fetch_results or [])

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._fetchval_results.pop(0) if self._fetchval_results else None

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


# ─── Persistence helpers ────────────────────────────────────────

def test_create_campaign_inserts_and_returns_row():
    pool = FakePool(fetchrow_results=[{"id": "camp-1", "name": "Promo Akhir Bulan", "status": "draft"}])
    campaign = asyncio.run(ma.create_campaign(
        pool, org_id="org-1", bot_id=None, name="Promo Akhir Bulan", goal="naikkan penjualan",
        target_audience=None, start_date=None, end_date=None, created_by="user-1",
    ))
    assert campaign["name"] == "Promo Akhir Bulan"
    assert any("INSERT INTO marketing_campaigns" in c[1] for c in pool.calls)


def test_update_campaign_status_rejects_invalid_status():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ma.update_campaign_status(pool, org_id="org-1", campaign_id="camp-1", status="bogus"))


def test_create_content_rejects_invalid_platform():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ma.create_content(
            pool, org_id="org-1", bot_id=None, campaign_id=None, platform="bogus",
            title=None, body="halo", hashtags=None, created_by="user-1",
        ))


def test_create_content_inserts_and_parses_hashtags():
    pool = FakePool(fetchrow_results=[{"id": "content-1", "platform": "instagram", "body": "Promo!", "hashtags": '["promo", "diskon"]'}])
    content = asyncio.run(ma.create_content(
        pool, org_id="org-1", bot_id=None, campaign_id=None, platform="instagram",
        title=None, body="Promo!", hashtags=["promo", "diskon"], created_by="user-1",
    ))
    assert content["hashtags"] == ["promo", "diskon"]


def test_schedule_content():
    pool = FakePool(fetchrow_results=[{"id": "content-1", "status": "scheduled", "hashtags": "[]"}])
    when = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = asyncio.run(ma.schedule_content(pool, org_id="org-1", content_id="content-1", scheduled_at=when))
    assert result["status"] == "scheduled"
    assert any("UPDATE marketing_content" in c[1] for c in pool.calls)


def test_approve_content():
    pool = FakePool(fetchrow_results=[{"id": "content-1", "status": "ready_to_publish", "hashtags": "[]"}])
    result = asyncio.run(ma.approve_content(pool, org_id="org-1", content_id="content-1", approver_id="user-1"))
    assert result["status"] == "ready_to_publish"


def test_record_engagement_rejects_invalid_metric():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ma.record_engagement(
            pool, org_id="org-1", content_id="content-1", metric_type="bogus",
            value=10, recorded_at=None, created_by="user-1",
        ))


def test_record_engagement_inserts():
    pool = FakePool(fetchrow_results=[{"id": "eng-1", "metric_type": "likes", "value": 50}])
    result = asyncio.run(ma.record_engagement(
        pool, org_id="org-1", content_id="content-1", metric_type="likes",
        value=50, recorded_at=None, created_by="user-1",
    ))
    assert result["value"] == 50
    assert any("INSERT INTO marketing_engagement" in c[1] for c in pool.calls)


def test_campaign_analytics_aggregates():
    pool = FakePool(fetch_results=[
        [{"platform": "instagram", "status": "published", "cnt": 3}],
        [{"metric_type": "likes", "total": 120}],
    ])
    result = asyncio.run(ma.campaign_analytics(pool, "org-1", "camp-1"))
    assert result["engagement_totals"]["likes"] == 120
    assert result["content_by_platform_status"][0]["cnt"] == 3


def test_dashboard_summary_aggregates():
    pool = FakePool(
        fetchrow_results=[{"draft_cnt": 2, "scheduled_cnt": 1, "ready_cnt": 0, "published_cnt": 5}],
        fetchval_results=[1, 1],
        fetch_results=[[{"metric_type": "likes", "total": 80}]],
    )
    summary = asyncio.run(ma.dashboard_summary(pool, "org-1"))
    assert summary["content_published"] == 5
    assert summary["active_campaigns"] == 1
    assert summary["content_due_now"] == 1
    assert summary["engagement_30d"]["likes"] == 80


# ─── MarketingAgent (NLP) ───────────────────────────────────────

def test_marketing_agent_requires_org_id_and_pool():
    agent = ma.MarketingAgent(api_key="test-key")
    result = asyncio.run(agent.run({"user_message": "buat caption promo", "platform": "instagram"}))
    assert result.success is False
    assert "org_id" in result.error


def test_marketing_agent_rejects_invalid_platform():
    agent = ma.MarketingAgent(api_key="test-key")
    pool = FakePool()
    result = asyncio.run(agent.run({
        "user_message": "buat caption", "platform": "bogus", "org_id": "org-1", "pool": pool,
    }))
    assert result.success is False
    assert "platform" in result.error


def test_marketing_agent_generates_and_persists_content(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.6, max_tokens=512, default=None):
        return {"title": None, "body": "Promo diskon 20%! Buruan checkout sebelum kehabisan.",
                "hashtags": ["promo", "diskon"]}

    monkeypatch.setattr(ma.MarketingAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool(fetchrow_results=[{
        "id": "content-1", "platform": "instagram", "body": "Promo diskon 20%! Buruan checkout sebelum kehabisan.",
        "hashtags": '["promo", "diskon"]',
    }])
    agent = ma.MarketingAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "user_message": "Promo diskon 20% akhir bulan", "platform": "instagram",
        "org_id": "org-1", "pool": pool, "actor_user_id": "user-1",
    }))
    assert result.success is True
    assert result.output["content"]["hashtags"] == ["promo", "diskon"]


def test_marketing_agent_fails_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.6, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(ma.MarketingAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool()
    agent = ma.MarketingAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "user_message": "Promo diskon 20%", "platform": "instagram",
        "org_id": "org-1", "pool": pool, "actor_user_id": "user-1",
    }))
    assert result.success is False


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_marketing_permission():
    requested_keys = []

    def recording_require_permission(key):
        requested_keys.append(key)
        async def _checker(user=None, pool=None):
            return user
        return _checker

    async def get_pool():
        return FakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    build_marketing_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("marketing.read") == 9
    assert requested_keys.count("marketing.write") == 10
    assert requested_keys.count("marketing.approve") == 1
    assert set(requested_keys) == {"marketing.read", "marketing.write", "marketing.approve"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_marketing_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_run_task_route_delegates_to_task_engine_and_writes_audit_log(monkeypatch):
    captured = {}

    async def fake_run_agent_task(agent, goal, *, pool, org_id, bot_id=None, ctx=None):
        captured["goal"] = goal
        captured["org_id"] = org_id
        return {"status": "completed", "report": "ok"}

    import task_engine
    monkeypatch.setattr(task_engine, "run_agent_task", fake_run_agent_task)

    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/run-task", "POST")
    result = asyncio.run(handler(
        body=RunTaskRequest(goal="Buat 1 konten Instagram untuk promo"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "completed"
    assert captured["goal"] == "Buat 1 konten Instagram untuk promo"
    assert captured["org_id"] == "org-1"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_create_campaign_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "camp-1", "name": "Promo Akhir Bulan", "status": "draft"}])
    router = _build_router(pool)
    handler = _route(router, "/campaigns", "POST")
    result = asyncio.run(handler(
        body=CampaignCreateRequest(name="Promo Akhir Bulan"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["name"] == "Promo Akhir Bulan"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_create_content_route_rejects_invalid_platform():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/content", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            body=ContentCreateRequest(platform="bogus", body="halo"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_create_content_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "content-1", "platform": "instagram", "body": "halo", "hashtags": "[]"}])
    router = _build_router(pool)
    handler = _route(router, "/content", "POST")
    result = asyncio.run(handler(
        body=ContentCreateRequest(platform="instagram", body="halo"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["platform"] == "instagram"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)
