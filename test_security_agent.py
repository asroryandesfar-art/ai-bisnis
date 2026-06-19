"""Tests untuk Security Agent (AI Workforce Phase 5): security_agent.py
(deteksi API abuse, tenant isolation, risk level, alert sync, report) dan
endpoint baru di bn_platform/security.py (scan-and-alert, risk-alerts,
reports) -- lapisan tipis di atas run_security_scan() yang sudah ada.

Mengikuti pola FakePool queue-based dari test_operations_agent.py."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

import security_agent as sec
from bn_platform.security import build_security_router


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


# ─── Risk level / detection ──────────────────────────────────────

def test_compute_risk_level_boundaries():
    assert sec.compute_risk_level(95) == "low"
    assert sec.compute_risk_level(90) == "low"
    assert sec.compute_risk_level(80) == "medium"
    assert sec.compute_risk_level(50) == "high"
    assert sec.compute_risk_level(10) == "critical"


def test_detect_api_abuse_returns_bursts():
    pool = FakePool(fetch_results=[[
        {"actor": "attacker@x.com", "action": "login_failed", "cnt": 12},
    ]])
    result = asyncio.run(sec.detect_api_abuse(pool, "org-1"))
    assert result == [{"actor": "attacker@x.com", "action": "login_failed", "count": 12}]


def test_detect_api_abuse_empty_when_none():
    pool = FakePool(fetch_results=[[]])
    result = asyncio.run(sec.detect_api_abuse(pool, "org-1"))
    assert result == []


def test_check_tenant_isolation_detects_cross_org_handoff():
    pool = FakePool(fetch_results=[
        [{"id": uuid.uuid4()}],  # human_queue violation
        [],  # workflow_executions clean
        [],  # sessions clean
    ])
    violations = asyncio.run(sec.check_tenant_isolation(pool, "org-1"))
    assert len(violations) == 1
    assert violations[0]["table"] == "human_queue"
    assert isinstance(violations[0]["id"], str)


def test_check_tenant_isolation_clean():
    pool = FakePool(fetch_results=[[], [], []])
    violations = asyncio.run(sec.check_tenant_isolation(pool, "org-1"))
    assert violations == []


# ─── Alert sync (reuse ops_alerts) ──────────────────────────────

def test_sync_alerts_from_scan_creates_alert_for_finding(monkeypatch):
    async def fake_has_recent(pool, org_id, category, hours=24):
        return False

    monkeypatch.setattr(sec, "has_recent_open_alert", fake_has_recent)
    pool = FakePool(fetchrow_results=[{"id": "alert-1", "category": "security_rbac", "source": "security"}])
    scan_result = {"findings": [{"severity": "high", "category": "rbac", "title": "User non-aktif punya role admin", "resource_id": "user-9"}]}
    created = asyncio.run(sec.sync_alerts_from_scan(pool, "org-1", scan_result, [], []))
    assert len(created) == 1
    assert any("INSERT INTO ops_alerts" in c[1] and "'security'" in c[1] for c in pool.calls)


def test_sync_alerts_from_scan_skips_when_alert_recent(monkeypatch):
    async def fake_has_recent(pool, org_id, category, hours=24):
        return True

    monkeypatch.setattr(sec, "has_recent_open_alert", fake_has_recent)
    pool = FakePool()
    scan_result = {"findings": [{"severity": "high", "category": "rbac", "title": "x", "resource_id": None}]}
    created = asyncio.run(sec.sync_alerts_from_scan(pool, "org-1", scan_result, [{"actor": "a", "action": "login_failed", "count": 9}], [{"table": "x", "id": "1", "issue": "y"}]))
    assert created == []


def test_sync_alerts_from_scan_creates_abuse_and_isolation_alerts(monkeypatch):
    async def fake_has_recent(pool, org_id, category, hours=24):
        return False

    monkeypatch.setattr(sec, "has_recent_open_alert", fake_has_recent)
    pool = FakePool(fetchrow_results=[
        {"id": "alert-abuse", "category": "security_api_abuse"},
        {"id": "alert-iso", "category": "security_tenant_isolation"},
    ])
    api_abuse = [{"actor": "x@y.com", "action": "login_failed", "count": 10}]
    isolation = [{"table": "human_queue", "id": "h1", "issue": "cross-org"}]
    created = asyncio.run(sec.sync_alerts_from_scan(pool, "org-1", {"findings": []}, api_abuse, isolation))
    assert len(created) == 2


# ─── Report / dashboard (mock run_security_scan import) ─────────

def test_generate_security_report_rejects_invalid_type():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(sec.generate_security_report(pool, "org-1", "bogus"))


def test_dashboard_summary_aggregates(monkeypatch):
    async def fake_scan(pool, *, org_id):
        return {"score": 85, "findings_count": 1, "findings": []}

    import bn_platform.security as security_mod
    monkeypatch.setattr(security_mod, "run_security_scan", fake_scan)

    pool = FakePool(fetch_results=[[{"severity": "medium", "cnt": 1}]])
    result = asyncio.run(sec.dashboard_summary(pool, "org-1"))
    assert result["score"] == 85
    assert result["risk_level"] == "medium"
    assert result["open_alerts_by_severity"]["medium"] == 1


def test_generate_summary_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(sec.SecurityAgent, "_call_llm_json", fake_call_llm_json)
    agent = sec.SecurityAgent(api_key="test-key")
    result = asyncio.run(agent.generate_summary({"score": 80}))
    assert result is None


def test_generate_summary_returns_text(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        return {"summary": "Risiko keamanan rendah minggu ini."}

    monkeypatch.setattr(sec.SecurityAgent, "_call_llm_json", fake_call_llm_json)
    agent = sec.SecurityAgent(api_key="test-key")
    result = asyncio.run(agent.generate_summary({"score": 80}))
    assert result == "Risiko keamanan rendah minggu ini."


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_new_routes_with_security_permission():
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

    build_security_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        hash_password=lambda x: x,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("security.read") == 3
    assert requested_keys.count("security.write") == 3


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_security_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, hash_password=lambda x: x,
        get_agent_config=lambda: {"api_key": ""},
    )


def test_update_risk_alert_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "a1", "status": "acknowledged"}])
    router = _build_router(pool)
    handler = _route(router, "/risk-alerts/{alert_id}", "PATCH")
    result = asyncio.run(handler(
        alert_id="a1", body={"status": "acknowledged"},
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "acknowledged"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_update_risk_alert_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/risk-alerts/{alert_id}", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            alert_id="a1", body={"status": "resolved"},
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_generate_security_report_route_rejects_invalid_type():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/reports/generate", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            body={"report_type": "bogus"},
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422
