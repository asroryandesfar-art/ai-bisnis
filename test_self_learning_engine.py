"""Tests untuk Self Learning Company (AI Workforce Phase 8):
self_learning_engine.py (deteksi pola sales/komplain/approach, upsert
idempotent, injeksi context read-only) dan bn_platform/self_learning.py
router. Mengikuti pola FakePool queue-based dari test_operations_agent.py."""
import asyncio

import pytest
from fastapi import HTTPException

import self_learning_engine as sl
from bn_platform.self_learning import build_self_learning_router, InsightStatusRequest


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


# ─── Detection (deterministic) ──────────────────────────────────

def test_analyze_sales_patterns_computes_conversion_rate():
    pool = FakePool(fetch_results=[[{"intent": "pricing", "purchased_cnt": 6, "total_cnt": 20}]])
    result = asyncio.run(sl.analyze_sales_patterns(pool, "org-1"))
    assert result[0]["conversion_rate_pct"] == 30.0


def test_analyze_sales_patterns_empty():
    pool = FakePool(fetch_results=[[]])
    result = asyncio.run(sl.analyze_sales_patterns(pool, "org-1"))
    assert result == []


def test_analyze_complaint_resolutions_collects_sample_notes():
    pool = FakePool(fetch_results=[[
        {"reason": "shipping_delay", "resolved_cnt": 5, "notes": ["Diganti barang baru", "Refund", None]},
    ]])
    result = asyncio.run(sl.analyze_complaint_resolutions(pool, "org-1"))
    assert result[0]["resolved_count"] == 5
    assert result[0]["sample_notes"] == ["Diganti barang baru", "Refund"]


def test_analyze_successful_approaches_returns_avg_quality():
    pool = FakePool(fetch_results=[[{"intent": "faq", "cnt": 10, "avg_quality": 9.2}]])
    result = asyncio.run(sl.analyze_successful_approaches(pool, "org-1"))
    assert result[0]["avg_quality_score"] == 9.2


# ─── Upsert / scan ───────────────────────────────────────────────

def test_run_learning_scan_skips_low_conversion_sales_pattern(monkeypatch):
    async def fake_sales(pool, org_id, days=90):
        return [{"intent": "x", "purchased_count": 1, "total_count": 20, "conversion_rate_pct": 5.0}]
    async def fake_complaints(pool, org_id, days=90):
        return []
    async def fake_approaches(pool, org_id, days=90):
        return []

    monkeypatch.setattr(sl, "analyze_sales_patterns", fake_sales)
    monkeypatch.setattr(sl, "analyze_complaint_resolutions", fake_complaints)
    monkeypatch.setattr(sl, "analyze_successful_approaches", fake_approaches)

    pool = FakePool()
    created = asyncio.run(sl.run_learning_scan(pool, "org-1"))
    assert created == []


def test_run_learning_scan_creates_insight_for_good_sales_pattern(monkeypatch):
    async def fake_sales(pool, org_id, days=90):
        return [{"intent": "pricing", "purchased_count": 6, "total_count": 20, "conversion_rate_pct": 30.0}]
    async def fake_complaints(pool, org_id, days=90):
        return []
    async def fake_approaches(pool, org_id, days=90):
        return []

    monkeypatch.setattr(sl, "analyze_sales_patterns", fake_sales)
    monkeypatch.setattr(sl, "analyze_complaint_resolutions", fake_complaints)
    monkeypatch.setattr(sl, "analyze_successful_approaches", fake_approaches)

    pool = FakePool(fetchrow_results=[{"id": "ins-1", "category": "sales_pattern", "insight": "x"}])
    created = asyncio.run(sl.run_learning_scan(pool, "org-1"))
    assert len(created) == 1
    assert any("ON CONFLICT (org_id, dedup_key)" in c[1] for c in pool.calls)


def test_run_learning_scan_uses_agent_distillation(monkeypatch):
    async def fake_sales(pool, org_id, days=90):
        return [{"intent": "pricing", "purchased_count": 6, "total_count": 20, "conversion_rate_pct": 30.0}]
    async def fake_complaints(pool, org_id, days=90):
        return []
    async def fake_approaches(pool, org_id, days=90):
        return []

    monkeypatch.setattr(sl, "analyze_sales_patterns", fake_sales)
    monkeypatch.setattr(sl, "analyze_complaint_resolutions", fake_complaints)
    monkeypatch.setattr(sl, "analyze_successful_approaches", fake_approaches)

    class FakeAgent:
        async def distill_insight(self, category, evidence):
            return "Insight tersaring dari AI."

    pool = FakePool(fetchrow_results=[{"id": "ins-1", "insight": "Insight tersaring dari AI."}])
    created = asyncio.run(sl.run_learning_scan(pool, "org-1", agent=FakeAgent()))
    assert created[0]["insight"] == "Insight tersaring dari AI."


# ─── Review ──────────────────────────────────────────────────────

def test_update_insight_status_rejects_invalid():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(sl.update_insight_status(pool, org_id="org-1", insight_id="i1", status="bogus"))


def test_update_insight_status_approve():
    pool = FakePool(fetchrow_results=[{"id": "i1", "status": "approved"}])
    result = asyncio.run(sl.update_insight_status(pool, org_id="org-1", insight_id="i1", status="approved", reviewed_by="u1"))
    assert result["status"] == "approved"


# ─── Chat context injection (read-only, no LLM) ─────────────────

def test_build_organizational_learning_context_empty_when_no_approved():
    pool = FakePool(fetch_results=[[]])
    result = asyncio.run(sl.build_organizational_learning_context(pool, "org-1", "bot-1"))
    assert result == ""


def test_build_organizational_learning_context_formats_insights():
    pool = FakePool(fetch_results=[[
        {"category": "sales_pattern", "insight": "Pricing intent convert tinggi."},
    ]])
    result = asyncio.run(sl.build_organizational_learning_context(pool, "org-1", "bot-1"))
    assert "Pricing intent convert tinggi." in result
    assert "Pembelajaran Organisasi" in result


# ─── SelfLearningAgent ───────────────────────────────────────────

def test_distill_insight_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(sl.SelfLearningAgent, "_call_llm_json", fake_call_llm_json)
    agent = sl.SelfLearningAgent(api_key="test-key")
    result = asyncio.run(agent.distill_insight("sales_pattern", {}))
    assert result is None


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_learning_permission():
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

    build_self_learning_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("learning.read") == 2
    assert requested_keys.count("learning.write") == 1
    assert requested_keys.count("learning.approve") == 1


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_self_learning_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_update_insight_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/insights/{insight_id}", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            insight_id="i1", body=InsightStatusRequest(status="approved"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_update_insight_route_rejects_invalid_status():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/insights/{insight_id}", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            insight_id="i1", body=InsightStatusRequest(status="bogus"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422
