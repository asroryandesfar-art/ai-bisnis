"""Tests untuk AI Improvement Engine: analisis (failed answers, low confidence,
negative feedback, repeated questions, handoff frequency, agent weaknesses),
recommendation engine (knowledge gap / prompt / workflow / agent improvement),
penyimpanan idempotent via dedup_key, dan router /api/improvement/*.

AI hanya mendeteksi & merekomendasikan — admin yang memutuskan via PATCH status.
Mengikuti pola FakePool + _route (test_security_platform.py).
"""
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from bn_platform.improvement_engine import (
    RecommendationUpdateRequest,
    _jsonb,
    _severity_for_count,
    analyze_agent_weaknesses,
    analyze_failed_answers,
    analyze_handoff_frequency,
    analyze_low_confidence,
    analyze_negative_feedback,
    analyze_repeated_questions,
    build_improvement_router,
    generate_recommendations,
    run_improvement_scan,
    save_recommendations,
)


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakePool:
    """Pool sederhana: cocokkan query via substring."""

    def __init__(self, fetch_results=None, fetchrow_results=None):
        self.fetch_results = fetch_results or []
        self.fetchrow_results = fetchrow_results or []
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        q = " ".join(sql.split())
        for pattern, value in self.fetch_results:
            if pattern in q:
                return value(args) if callable(value) else value
        return []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        q = " ".join(sql.split())
        for pattern, value in self.fetchrow_results:
            if pattern in q:
                return value(args) if callable(value) else value
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


# ─── Helpers ────────────────────────────────────────────

def test_severity_for_count():
    assert _severity_for_count(1) == "low"
    assert _severity_for_count(2) == "medium"
    assert _severity_for_count(5) == "high"
    assert _severity_for_count(10) == "critical"


def test_jsonb_parses_string_and_passes_through():
    assert _jsonb('{"a": 1}') == {"a": 1}
    assert _jsonb(None) == {}
    assert _jsonb({"b": 2}) == {"b": 2}
    assert _jsonb("not json", default={"x": 1}) == {"x": 1}


# ─── Analysis queries ───────────────────────────────────

def test_analyze_failed_answers_queries_conversation_analysis():
    rows = [{"bot_id": "bot-1", "intent": "refund", "outcome": "unresolved", "count": 3}]
    pool = FakePool(fetch_results=[("GROUP BY bot_id, intent, outcome", rows)])
    result = asyncio.run(analyze_failed_answers(pool, org_id="org-1", days=30))
    assert result == rows
    _, _, params = pool.calls[-1]
    assert params == ("org-1", 30)


def test_analyze_low_confidence_uses_threshold():
    rows = [{"bot_id": "bot-1", "intent": "pricing", "count": 4, "avg_confidence": 42.0}]
    pool = FakePool(fetch_results=[("(raw_metrics->>'confidence_score')::numeric < $3", rows)])
    result = asyncio.run(analyze_low_confidence(pool, org_id="org-1", days=30))
    assert result == rows
    _, _, params = pool.calls[-1]
    assert params == ("org-1", 30, 60)


def test_analyze_negative_feedback_queries_feedback_records():
    rows = [{"bot_id": "bot-1", "question": "Bagaimana refund?", "count": 3, "last_seen": "now"}]
    pool = FakePool(fetch_results=[("FROM feedback_records", rows)])
    result = asyncio.run(analyze_negative_feedback(pool, org_id="org-1", days=30))
    assert result == rows


def test_analyze_repeated_questions_queries_learning_queue():
    rows = [{"bot_id": "bot-1", "question": "q", "answer": "a", "failure_reason": None,
             "action_type": "prompt", "occurrence_count": 3, "status": "pending"}]
    pool = FakePool(fetch_results=[("FROM feedback_learning_queue", rows)])
    result = asyncio.run(analyze_repeated_questions(pool, org_id="org-1", days=30))
    assert result == rows


def test_analyze_handoff_frequency_queries_human_queue():
    rows = [{"bot_id": "bot-1", "reason": "complex_query", "count": 5}]
    pool = FakePool(fetch_results=[("FROM human_queue", rows)])
    result = asyncio.run(analyze_handoff_frequency(pool, org_id="org-1", days=30))
    assert result == rows


def test_analyze_agent_weaknesses_queries_rollup():
    rows = [{"bot_id": "bot-1", "bot_name": "Sales Bot", "conversations": 10,
             "avg_quality_score": 4.2, "avg_confidence": 55.0,
             "failed_verifications": 3, "bad_outcomes": 4}]
    pool = FakePool(fetch_results=[("FROM conversation_analysis ca", rows)])
    result = asyncio.run(analyze_agent_weaknesses(pool, org_id="org-1", days=30))
    assert result == rows


# ─── Recommendation engine ──────────────────────────────

def _full_pool(**overrides):
    """FakePool dgn hasil kosong untuk semua query analisis, bisa di-override per test."""
    defaults = {
        "GROUP BY bot_id, intent, outcome": [],
        "(raw_metrics->>'confidence_score')::numeric < $3": [],
        "FROM feedback_records": [],
        "FROM feedback_learning_queue": [],
        "FROM human_queue": [],
        "FROM conversation_analysis ca": [],
    }
    defaults.update(overrides)
    return FakePool(fetch_results=list(defaults.items()))


def test_generate_recommendations_low_confidence_becomes_knowledge_gap():
    pool = _full_pool(**{"(raw_metrics->>'confidence_score')::numeric < $3": [
        {"bot_id": "bot-1", "intent": "refund", "count": 4, "avg_confidence": 45.0},
    ]})
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    assert len(recs) == 1
    rec = recs[0]
    assert rec["category"] == "knowledge_gap"
    assert rec["severity"] == "medium"
    assert rec["dedup_key"] == "knowledge_gap:low_confidence:bot-1:refund"
    assert rec["occurrence_count"] == 4


def test_generate_recommendations_negative_feedback_becomes_knowledge_gap():
    pool = _full_pool(**{"FROM feedback_records": [
        {"bot_id": "bot-1", "question": "Bagaimana refund?", "count": 6, "last_seen": "now"},
    ]})
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    assert len(recs) == 1
    rec = recs[0]
    assert rec["category"] == "knowledge_gap"
    assert rec["severity"] == "high"
    assert "Bagaimana refund?" in rec["description"]


def test_generate_recommendations_repeated_questions_map_action_type_to_category():
    pool = _full_pool(**{"FROM feedback_learning_queue": [
        {"bot_id": "bot-1", "question": "q1", "answer": "a1", "failure_reason": "Jawaban kurang detail",
         "action_type": "prompt", "occurrence_count": 3, "status": "pending"},
        {"bot_id": "bot-1", "question": "q2", "answer": "a2", "failure_reason": None,
         "action_type": "workflow", "occurrence_count": 2, "status": "in_progress"},
    ]})
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    categories = {r["dedup_key"]: r["category"] for r in recs}
    assert categories["prompt_improvement:learning_queue:bot-1:q1"] == "prompt_improvement"
    assert categories["workflow_improvement:learning_queue:bot-1:q2"] == "workflow_improvement"


def test_generate_recommendations_agent_weaknesses_verification_and_quality():
    pool = _full_pool(**{"FROM conversation_analysis ca": [
        {"bot_id": "bot-1", "bot_name": "Sales Bot", "conversations": 10,
         "avg_quality_score": 2.5, "avg_confidence": 50.0,
         "failed_verifications": 3, "bad_outcomes": 4},
    ]})
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    by_category = {r["category"]: r for r in recs}
    assert "prompt_improvement" in by_category
    assert by_category["prompt_improvement"]["dedup_key"] == "prompt_improvement:verification:bot-1"
    assert "agent_improvement" in by_category
    assert by_category["agent_improvement"]["severity"] == "high"  # avg_quality < 3


def test_generate_recommendations_handoff_and_failed_answers_respect_min_occurrences():
    pool = _full_pool(**{
        "FROM human_queue": [
            {"bot_id": "bot-1", "reason": "complex_query", "count": 1},   # di bawah ambang, dikecualikan
            {"bot_id": "bot-1", "reason": "billing_issue", "count": 3},   # disertakan
        ],
        "GROUP BY bot_id, intent, outcome": [
            {"bot_id": "bot-1", "intent": "refund", "outcome": "abandoned", "count": 1},  # dikecualikan
            {"bot_id": "bot-1", "intent": "refund", "outcome": "escalated", "count": 5},  # disertakan
        ],
    })
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    dedup_keys = {r["dedup_key"] for r in recs}
    assert "workflow_improvement:handoff:bot-1:billing_issue" in dedup_keys
    assert "workflow_improvement:handoff:bot-1:complex_query" not in dedup_keys
    assert "agent_improvement:outcome:bot-1:refund:escalated" in dedup_keys
    assert "agent_improvement:outcome:bot-1:refund:abandoned" not in dedup_keys


def test_generate_recommendations_empty_data_returns_nothing():
    pool = _full_pool()
    recs = asyncio.run(generate_recommendations(pool, org_id="org-1", days=30))
    assert recs == []


# ─── Persistence ─────────────────────────────────────────

def test_save_recommendations_upserts_with_dedup_key_and_skips_status():
    pool = FakePool()
    recs = [{
        "category": "knowledge_gap", "bot_id": "bot-1", "severity": "medium",
        "title": "Title", "description": "Desc", "evidence": {"count": 3},
        "dedup_key": "knowledge_gap:low_confidence:bot-1:refund", "occurrence_count": 3,
    }]
    saved = asyncio.run(save_recommendations(pool, org_id="org-1", recommendations=recs))
    assert saved == 1
    kind, sql, params = pool.calls[0]
    assert kind == "execute"
    flat_sql = " ".join(sql.split())
    assert "ON CONFLICT (org_id, dedup_key) DO UPDATE" in flat_sql
    assert "status" not in flat_sql.split("DO UPDATE SET")[1]
    assert params[0] == "org-1"
    assert params[7] == "knowledge_gap:low_confidence:bot-1:refund"


def test_run_improvement_scan_saves_and_audits():
    pool = _full_pool(**{"FROM feedback_records": [
        {"bot_id": "bot-1", "question": "q", "count": 5, "last_seen": "now"},
    ]})
    result = asyncio.run(run_improvement_scan(pool, org_id="org-1", days=14))
    assert result["recommendations_generated"] == 1
    assert result["days"] == 14
    audit_calls = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO audit_logs" in c[1]]
    assert len(audit_calls) == 1
    assert audit_calls[0][2][4] == "improvement_scan"  # resource_type


# ─── Router ──────────────────────────────────────────────

def _build_router(pool, *, permissions=None):
    permissions = permissions or set()

    async def get_pool():
        return pool

    async def get_current_user():
        return _user()

    def require_permission(key):
        async def _checker(user, pool):
            if key not in permissions:
                raise HTTPException(403, f"Tidak punya izin: {key}")
            return user
        return _checker

    return build_improvement_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission,
    )


def _user(org_id="org-1"):
    return {"org_id": org_id, "id": "user-1", "email": "owner@x.com"}


def test_dashboard_aggregates_top_issues_and_filters_recommendations():
    rec_rows = [
        {"id": "rec-1", "bot_id": "bot-1", "category": "knowledge_gap", "severity": "high",
         "title": "Gap", "description": "Desc", "evidence": '{"count": 3}',
         "occurrence_count": 3, "status": "new", "resolution_note": None,
         "created_at": "now", "updated_at": "now"},
        {"id": "rec-2", "bot_id": "bot-1", "category": "prompt_improvement", "severity": "medium",
         "title": "Prompt", "description": "Desc2", "evidence": "{}",
         "occurrence_count": 2, "status": "applied", "resolution_note": "Done",
         "created_at": "now", "updated_at": "now"},
    ]
    pool = _full_pool(**{
        "FROM human_queue": [{"bot_id": "bot-1", "reason": "complex_query", "count": 7}],
        "FROM ai_improvement_recommendations": rec_rows,
    })
    pool.fetchrow_results = [("FROM audit_logs", {"created_at": "2026-06-01"})]

    router = _build_router(pool, permissions={"analytics.read"})
    handler = _route(router, "/dashboard", "GET")
    result = asyncio.run(handler(user=_user(), pool=pool, days=30))

    assert result["summary"]["handoffs"] == 7
    assert result["top_issues"][0]["type"] == "handoff"
    assert result["knowledge_gaps"][0]["id"] == "rec-1"
    assert result["knowledge_gaps"][0]["evidence"] == {"count": 3}
    assert {r["id"] for r in result["suggested_improvements"]} == {"rec-1"}  # rec-2 sudah "applied"
    assert result["last_scan_at"] == "2026-06-01"


def test_list_recommendations_validates_category_and_status():
    pool = FakePool(fetch_results=[("FROM ai_improvement_recommendations", [])])
    router = _build_router(pool, permissions={"analytics.read"})
    handler = _route(router, "/recommendations", "GET")

    result = asyncio.run(handler(user=_user(), pool=pool, category=None, status=None))
    assert result == {"recommendations": []}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(user=_user(), pool=pool, category="invalid", status=None))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(user=_user(), pool=pool, category=None, status="invalid"))
    assert exc.value.status_code == 422


def test_update_recommendation_success_not_found_and_invalid_status():
    pool = FakePool(fetchrow_results=[
        ("UPDATE ai_improvement_recommendations", {"id": "rec-1", "category": "knowledge_gap",
         "status": "reviewed", "resolution_note": "noted", "updated_at": "now"}),
    ])
    router = _build_router(pool, permissions={"settings.manage"})
    handler = _route(router, "/recommendations/{rec_id}", "PATCH")

    body = RecommendationUpdateRequest(status="reviewed", resolution_note="noted")
    result = asyncio.run(handler(rec_id="rec-1", body=body, user=_user(), pool=pool))
    assert result["recommendation"]["status"] == "reviewed"
    assert any(c[0] == "execute" and "INSERT INTO audit_logs" in c[1] for c in pool.calls)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(rec_id="rec-1", body=RecommendationUpdateRequest(status="invalid"), user=_user(), pool=pool))
    assert exc.value.status_code == 422

    pool_none = FakePool(fetchrow_results=[("UPDATE ai_improvement_recommendations", None)])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(rec_id="missing", body=RecommendationUpdateRequest(status="dismissed"), user=_user(), pool=pool_none))
    assert exc.value.status_code == 404


def test_trigger_scan_runs_scan_and_returns_summary():
    pool = _full_pool()
    router = _build_router(pool, permissions={"settings.manage"})
    handler = _route(router, "/scan", "POST")
    result = asyncio.run(handler(user=_user(org_id="org-scan-run"), pool=pool, days=30))
    assert result["recommendations_generated"] == 0
    assert result["days"] == 30


def test_trigger_scan_rate_limited_after_too_many_requests():
    pool = _full_pool()
    router = _build_router(pool, permissions={"settings.manage"})
    handler = _route(router, "/scan", "POST")
    user = _user(org_id="org-scan-ratelimit")
    for _ in range(5):
        asyncio.run(handler(user=user, pool=pool, days=30))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(user=user, pool=pool, days=30))
    assert exc.value.status_code == 429


# ─── Wiring: routes, schema, and frontend ─────────────────

def test_improvement_engine_routes_schema_and_ui_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/improvement/dashboard" in paths
    assert "/api/improvement/recommendations" in paths
    assert "/api/improvement/recommendations/{rec_id}" in paths
    assert "/api/improvement/scan" in paths

    schema = (Path(__file__).resolve().parent / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ai_improvement_recommendations" in schema
    for field in ("category", "severity", "status", "dedup_key", "occurrence_count"):
        assert field in schema

    frontend = (Path(__file__).resolve().parent / "frontend/app.js").read_text()
    components = (Path(__file__).resolve().parent / "frontend/components.js").read_text()
    api_client = (Path(__file__).resolve().parent / "frontend/api-client.js").read_text()
    assert "renderImprovement" in frontend
    assert "AI Improvement Center" in components
    assert "improvementDashboard" in api_client
    assert "improvementScan" in api_client
