"""Tests untuk Operations Agent (AI Workforce Phase 4): operations_agent.py
(health detection helpers, alerting, reports) dan bn_platform/operations.py
(router RBAC gating + endpoint behavior).

Mengikuti pola FakePool + _route dari test_finance_agent.py -- tidak ada
panggilan Groq atau database sungguhan."""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi import HTTPException

import operations_agent as ops
from bn_platform.operations import (
    build_operations_router, AlertStatusRequest, ReportGenerateRequest, RunTaskRequest,
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


# ─── Health metrics ─────────────────────────────────────────────

def test_detect_workflow_health_computes_success_rate():
    pool = FakePool(
        fetchrow_results=[{"total": 10, "success_cnt": 9, "failed_cnt": 1, "avg_duration_ms": 500}],
        fetch_results=[[{"id": uuid.uuid4(), "workflow_id": uuid.uuid4(), "error": "timeout",
                          "started_at": datetime(2026, 6, 1, tzinfo=timezone.utc)}]],
    )
    result = asyncio.run(ops.detect_workflow_health(pool, "org-1"))
    assert result["success_rate_pct"] == 90.0
    assert result["failed_count"] == 1
    assert len(result["recent_failures"]) == 1
    assert isinstance(result["recent_failures"][0]["id"], str)


def test_detect_workflow_health_no_executions():
    pool = FakePool(fetchrow_results=[{"total": 0, "success_cnt": 0, "failed_cnt": 0, "avg_duration_ms": None}])
    result = asyncio.run(ops.detect_workflow_health(pool, "org-1"))
    assert result["success_rate_pct"] is None


def test_detect_sla_health_computes_breach_rate():
    pool = FakePool(fetchrow_results=[{"total": 20, "breached_cnt": 5, "avg_resolution_minutes": 45.5}])
    result = asyncio.run(ops.detect_sla_health(pool, "org-1"))
    assert result["breach_rate_pct"] == 25.0
    assert result["avg_resolution_minutes"] == 45.5


def test_detect_tenant_activity_marks_inactive():
    pool = FakePool(fetchrow_results=[{
        "convs_7d": 0, "convs_30d": 0, "last_activity_at": datetime.now(timezone.utc) - timedelta(days=20),
    }])
    result = asyncio.run(ops.detect_tenant_activity(pool, "org-1"))
    assert result["is_inactive"] is True


def test_detect_tenant_activity_marks_active():
    pool = FakePool(fetchrow_results=[{
        "convs_7d": 50, "convs_30d": 200, "last_activity_at": datetime.now(timezone.utc) - timedelta(hours=2),
    }])
    result = asyncio.run(ops.detect_tenant_activity(pool, "org-1"))
    assert result["is_inactive"] is False


def test_compute_health_score_healthy():
    workflow_health = {"success_rate_pct": 98}
    sla_health = {"breach_rate_pct": 2}
    tenant_activity = {"is_inactive": False}
    result = ops.compute_health_score(workflow_health, sla_health, tenant_activity)
    assert result["label"] == "healthy"
    assert result["score"] == 100


def test_compute_health_score_critical_when_inactive():
    workflow_health = {"success_rate_pct": None}
    sla_health = {"breach_rate_pct": None}
    tenant_activity = {"is_inactive": True}
    result = ops.compute_health_score(workflow_health, sla_health, tenant_activity)
    assert result["score"] == 70
    assert "Tidak ada aktivitas" in result["reasons"][0]


# ─── Alerts ─────────────────────────────────────────────────────

def test_create_alert_rejects_invalid_severity():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ops.create_alert(pool, org_id="org-1", severity="bogus", category="x", message="y"))


def test_create_alert_inserts():
    pool = FakePool(fetchrow_results=[{"id": "alert-1", "severity": "high", "category": "sla_breach"}])
    alert = asyncio.run(ops.create_alert(pool, org_id="org-1", severity="high", category="sla_breach", message="test"))
    assert alert["severity"] == "high"
    assert any("INSERT INTO ops_alerts" in c[1] for c in pool.calls)


def test_update_alert_status_rejects_invalid():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ops.update_alert_status(pool, org_id="org-1", alert_id="a1", status="bogus", actor_id="u1"))


def test_update_alert_status_acknowledge_and_resolve():
    pool = FakePool(fetchrow_results=[
        {"id": "a1", "status": "acknowledged"},
        {"id": "a1", "status": "resolved"},
    ])
    ack = asyncio.run(ops.update_alert_status(pool, org_id="org-1", alert_id="a1", status="acknowledged", actor_id="u1"))
    assert ack["status"] == "acknowledged"
    resolved = asyncio.run(ops.update_alert_status(pool, org_id="org-1", alert_id="a1", status="resolved", actor_id="u1"))
    assert resolved["status"] == "resolved"


def test_run_health_scan_creates_alert_when_workflow_unhealthy(monkeypatch):
    async def fake_detect_workflow_health(pool, org_id, days=7):
        return {"success_rate_pct": 50.0, "total_executions": 10, "failed_count": 5,
                "avg_duration_ms": 100, "recent_failures": []}

    async def fake_detect_sla_health(pool, org_id, days=7):
        return {"total_handoffs": 0, "breached_count": 0, "breach_rate_pct": None, "avg_resolution_minutes": None}

    async def fake_detect_tenant_activity(pool, org_id):
        return {"conversations_7d": 10, "conversations_30d": 40, "last_activity_at": None, "is_inactive": False}

    async def fake_top_recs(pool, org_id, limit=20):
        return []

    monkeypatch.setattr(ops, "detect_workflow_health", fake_detect_workflow_health)
    monkeypatch.setattr(ops, "detect_sla_health", fake_detect_sla_health)
    monkeypatch.setattr(ops, "detect_tenant_activity", fake_detect_tenant_activity)
    monkeypatch.setattr(ops, "top_improvement_recommendations", fake_top_recs)

    pool = FakePool(fetchval_results=[None], fetchrow_results=[{"id": "alert-1", "category": "workflow_failure"}])
    created = asyncio.run(ops.run_health_scan(pool, "org-1"))
    assert len(created) == 1
    assert created[0]["category"] == "workflow_failure"


def test_run_health_scan_skips_when_recent_alert_exists(monkeypatch):
    async def fake_detect_workflow_health(pool, org_id, days=7):
        return {"success_rate_pct": 50.0, "total_executions": 10, "failed_count": 5,
                "avg_duration_ms": 100, "recent_failures": []}

    async def fake_detect_sla_health(pool, org_id, days=7):
        return {"total_handoffs": 0, "breached_count": 0, "breach_rate_pct": None, "avg_resolution_minutes": None}

    async def fake_detect_tenant_activity(pool, org_id):
        return {"conversations_7d": 10, "conversations_30d": 40, "last_activity_at": None, "is_inactive": False}

    async def fake_top_recs(pool, org_id, limit=20):
        return []

    monkeypatch.setattr(ops, "detect_workflow_health", fake_detect_workflow_health)
    monkeypatch.setattr(ops, "detect_sla_health", fake_detect_sla_health)
    monkeypatch.setattr(ops, "detect_tenant_activity", fake_detect_tenant_activity)
    monkeypatch.setattr(ops, "top_improvement_recommendations", fake_top_recs)

    pool = FakePool(fetchval_results=[1])  # has_recent_open_alert returns truthy
    created = asyncio.run(ops.run_health_scan(pool, "org-1"))
    assert created == []


# ─── Reports ────────────────────────────────────────────────────

def test_generate_report_rejects_invalid_type():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(ops.generate_report(pool, "org-1", "bogus"))


def test_dashboard_summary_aggregates(monkeypatch):
    async def fake_detect_workflow_health(pool, org_id, days=7):
        return {"success_rate_pct": 95.0, "total_executions": 20, "failed_count": 1,
                "avg_duration_ms": 200, "recent_failures": []}

    async def fake_detect_sla_health(pool, org_id, days=7):
        return {"total_handoffs": 5, "breached_count": 0, "breach_rate_pct": 0.0, "avg_resolution_minutes": 10.0}

    async def fake_detect_tenant_activity(pool, org_id):
        return {"conversations_7d": 30, "conversations_30d": 100, "last_activity_at": "2026-06-19T00:00:00", "is_inactive": False}

    monkeypatch.setattr(ops, "detect_workflow_health", fake_detect_workflow_health)
    monkeypatch.setattr(ops, "detect_sla_health", fake_detect_sla_health)
    monkeypatch.setattr(ops, "detect_tenant_activity", fake_detect_tenant_activity)

    pool = FakePool(fetch_results=[[{"severity": "high", "cnt": 2}]])
    summary = asyncio.run(ops.dashboard_summary(pool, "org-1"))
    assert summary["health"]["label"] == "healthy"
    assert summary["open_alerts_by_severity"]["high"] == 2


# ─── OperationsAgent (LLM narrative) ────────────────────────────

def test_generate_summary_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(ops.OperationsAgent, "_call_llm_json", fake_call_llm_json)
    agent = ops.OperationsAgent(api_key="test-key")
    result = asyncio.run(agent.generate_summary({"health": {"score": 80}}))
    assert result is None


def test_generate_summary_returns_text(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        return {"summary": "Operasional tenant stabil minggu ini."}

    monkeypatch.setattr(ops.OperationsAgent, "_call_llm_json", fake_call_llm_json)
    agent = ops.OperationsAgent(api_key="test-key")
    result = asyncio.run(agent.generate_summary({"health": {"score": 80}}))
    assert result == "Operasional tenant stabil minggu ini."


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_operations_permission():
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

    build_operations_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("operations.read") == 4
    assert requested_keys.count("operations.write") == 4
    assert set(requested_keys) == {"operations.read", "operations.write"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_operations_router(
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
        body=RunTaskRequest(goal="Cek kesehatan workflow minggu ini"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "completed"
    assert captured["goal"] == "Cek kesehatan workflow minggu ini"
    assert captured["org_id"] == "org-1"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_update_alert_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "a1", "status": "acknowledged"}])
    router = _build_router(pool)
    handler = _route(router, "/alerts/{alert_id}", "PATCH")
    result = asyncio.run(handler(
        alert_id="a1", body=AlertStatusRequest(status="acknowledged"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "acknowledged"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_update_alert_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/alerts/{alert_id}", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            alert_id="a1", body=AlertStatusRequest(status="resolved"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_generate_report_route_rejects_invalid_type():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/reports/generate", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            body=ReportGenerateRequest(report_type="bogus"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422
