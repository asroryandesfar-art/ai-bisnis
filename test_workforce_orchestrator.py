"""Tests untuk Workforce Orchestrator (AI Workforce Phase 7): task
assignment, conflict detection, escalation, human approval gate, dan
endpoint bn_platform/workforce.py. Modul ini SENGAJA tidak pernah
memanggil supervisor.py -- tidak ada test yang menyentuh chat pipeline.

Mengikuti pola FakePool queue-based dari test_operations_agent.py."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import workforce_orchestrator as wf
from bn_platform.workforce import build_workforce_router, TaskCreateRequest, TaskStatusRequest, TaskAssignRequest


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


# ─── Task CRUD ───────────────────────────────────────────────────

def test_create_task_rejects_invalid_domain():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(wf.create_task(pool, org_id="org-1", domain="bogus", title="x"))


def test_create_task_rejects_invalid_priority():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(wf.create_task(pool, org_id="org-1", domain="finance", title="x", priority="urgent"))


def test_create_task_inserts():
    pool = FakePool(fetchrow_results=[{"id": "task-1", "domain": "finance", "title": "Investigasi invoice"}])
    task = asyncio.run(wf.create_task(pool, org_id="org-1", domain="finance", title="Investigasi invoice"))
    assert task["id"] == "task-1"
    assert any("INSERT INTO workforce_tasks" in c[1] for c in pool.calls)


def test_update_task_status_rejects_invalid_status():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(wf.update_task_status(pool, org_id="org-1", task_id="t1", status="bogus"))


def test_update_task_status_blocks_completion_without_approval():
    pool = FakePool(fetchrow_results=[{"requires_approval": True, "approved_at": None}])
    with pytest.raises(ValueError):
        asyncio.run(wf.update_task_status(pool, org_id="org-1", task_id="t1", status="completed"))


def test_update_task_status_allows_completion_when_approved():
    pool = FakePool(fetchrow_results=[
        {"requires_approval": True, "approved_at": datetime.now(timezone.utc)},
        {"id": "t1", "status": "completed"},
    ])
    result = asyncio.run(wf.update_task_status(pool, org_id="org-1", task_id="t1", status="completed"))
    assert result["status"] == "completed"


def test_update_task_status_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    result = asyncio.run(wf.update_task_status(pool, org_id="org-1", task_id="t1", status="in_progress"))
    assert result is None


def test_approve_task_only_updates_when_requires_approval():
    pool = FakePool(fetchrow_results=[{"id": "t1", "approved_by": "u1"}])
    result = asyncio.run(wf.approve_task(pool, org_id="org-1", task_id="t1", approver_id="u1"))
    assert result["approved_by"] == "u1"
    assert "requires_approval=TRUE" in pool.calls[0][1]


# ─── Conflict detection / escalation ─────────────────────────────

def test_detect_conflicts_flags_shared_source():
    import uuid
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    pool = FakePool(fetch_results=[[
        {"domain": "finance", "source_id": uuid.uuid4(), "task_ids": [id1, id2], "cnt": 2},
    ]])
    conflicts = asyncio.run(wf.detect_conflicts(pool, "org-1"))
    assert len(conflicts) == 1
    assert len(conflicts[0]["task_ids"]) == 2
    assert any("UPDATE workforce_tasks SET has_conflict=TRUE" in c[1] for c in pool.calls)


def test_detect_conflicts_empty_when_no_shared_source():
    pool = FakePool(fetch_results=[[]])
    conflicts = asyncio.run(wf.detect_conflicts(pool, "org-1"))
    assert conflicts == []


def test_escalate_overdue_tasks_returns_escalated():
    pool = FakePool(fetch_results=[[{"id": "t1", "domain": "operations", "title": "x", "due_at": datetime.now(timezone.utc) - timedelta(days=1)}]])
    escalated = asyncio.run(wf.escalate_overdue_tasks(pool, "org-1"))
    assert len(escalated) == 1


# ─── Dashboard ───────────────────────────────────────────────────

def test_dashboard_summary_aggregates():
    pool = FakePool(fetch_results=[
        [{"status": "pending", "cnt": 3}],
        [{"domain": "finance", "cnt": 2}],
    ], fetchval_results=[1, 0])
    result = asyncio.run(wf.dashboard_summary(pool, "org-1"))
    assert result["by_status"]["pending"] == 3
    assert result["by_domain"]["finance"] == 2
    assert result["pending_approval_count"] == 1
    assert result["conflicts_count"] == 0


# ─── WorkforceOrchestratorAgent (advisory LLM) ──────────────────

def test_suggest_conflict_resolution_returns_none_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(wf.WorkforceOrchestratorAgent, "_call_llm_json", fake_call_llm_json)
    agent = wf.WorkforceOrchestratorAgent(api_key="test-key")
    result = asyncio.run(agent.suggest_conflict_resolution([{"title": "A"}, {"title": "B"}]))
    assert result is None


def test_suggest_conflict_resolution_returns_text(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=512, default=None):
        return {"suggestion": "Prioritaskan task dengan severity tertinggi."}

    monkeypatch.setattr(wf.WorkforceOrchestratorAgent, "_call_llm_json", fake_call_llm_json)
    agent = wf.WorkforceOrchestratorAgent(api_key="test-key")
    result = asyncio.run(agent.suggest_conflict_resolution([{"title": "A"}, {"title": "B"}]))
    assert result == "Prioritaskan task dengan severity tertinggi."


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_workforce_permission():
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

    build_workforce_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("workforce.read") == 2
    assert requested_keys.count("workforce.write") == 4
    assert requested_keys.count("workforce.approve") == 1


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_workforce_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_create_task_route_rejects_invalid_domain():
    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/tasks", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            body=TaskCreateRequest(domain="bogus", title="x"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_update_task_status_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[
        {"requires_approval": False, "approved_at": None},
        {"id": "t1", "status": "in_progress"},
    ])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}/status", "PATCH")
    result = asyncio.run(handler(
        task_id="t1", body=TaskStatusRequest(status="in_progress"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "in_progress"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_assign_task_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}/assign", "PATCH")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            task_id="t1", body=TaskAssignRequest(assigned_to="user-2"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_approve_task_route_404_when_not_eligible():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}/approve", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            task_id="t1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404
