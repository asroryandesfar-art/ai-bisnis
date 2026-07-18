"""
test_local_agent_router.py — bn_platform/local_agent_router.py: RBAC gating
per route, and the local-agent risky-action approval queue (previously a
dead end: needs_approval was never persisted and pointed users at a queue
that could never show it). Mirrors test_computer_agent_router.py's
FakePool/_route/_build_router pattern.
"""
import asyncio

import pytest
from fastapi import HTTPException

from bn_platform.local_agent_router import build_local_agent_router, LocalAgentRejectRequest
import bn_platform.local_agent_router as local_agent_router


def _route(router, path, method):
    for r in router.routes:
        if getattr(r, "path", "").endswith(path) and method in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakePool:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.calls = []
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetch_results = list(fetch_results or [])

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_local_agent_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission,
        decode_token=lambda token: {"org": "org-1"},
    )


def test_router_gates_every_rest_route_with_correct_permission_tier():
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

    build_local_agent_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        decode_token=lambda token: {"org": "org-1"},
    )

    # status + disconnect + devices + device-rename + device-disconnect
    assert requested_keys.count("local_agent.manage") == 5
    # execute + run-local + approve + reject
    assert requested_keys.count("local_agent.execute") == 4
    # history
    assert requested_keys.count("local_agent.read") == 1


def test_approve_command_404_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "c1", "status": "completed", "tool": "run_command", "args": "{}"}])
    router = _build_router(pool)
    handler = _route(router, "/commands/{command_id}/approve", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            command_id="c1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_approve_command_404_when_missing():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/commands/{command_id}/approve", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            command_id="does-not-exist", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_approve_command_executes_via_manager_and_marks_completed(monkeypatch):
    """The core fix: approving a pending risky action must actually run it
    through LocalAgentManager.execute() (same path as direct /execute),
    not just flip a status flag."""
    pool = FakePool(fetchrow_results=[
        {"id": "c1", "status": "pending_approval", "tool": "run_command", "args": '{"command": "echo hi"}'},
        {"id": "c1", "status": "completed", "tool": "run_command", "args": '{"command": "echo hi"}',
         "result": '{"success": true}', "initiated_by": "user-1", "created_at": None, "completed_at": None},
    ])
    router = _build_router(pool)

    executed = {}

    class FakeManager:
        async def execute(self, org_id, tool, args, *, initiated_by, pool):
            executed["org_id"] = org_id
            executed["tool"] = tool
            executed["args"] = args
            executed["initiated_by"] = initiated_by
            return {"success": True, "output": "hi"}

    monkeypatch.setattr(local_agent_router, "get_manager", lambda: FakeManager())

    handler = _route(router, "/commands/{command_id}/approve", "POST")
    result = asyncio.run(handler(
        command_id="c1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))

    assert executed == {"org_id": "org-1", "tool": "run_command", "args": {"command": "echo hi"},
                         "initiated_by": "user-1"}
    assert result["status"] == "completed"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_approve_command_marks_failed_when_local_agent_not_connected(monkeypatch):
    """If the tenant's local agent isn't connected, approving must not leave
    the command stuck pending forever -- it should resolve to failed."""
    pool = FakePool(fetchrow_results=[
        {"id": "c1", "status": "pending_approval", "tool": "run_command", "args": "{}"},
        {"id": "c1", "status": "failed", "tool": "run_command", "args": "{}",
         "result": '{"success": false}', "initiated_by": "user-1", "created_at": None, "completed_at": None},
    ])
    router = _build_router(pool)

    class FakeManager:
        async def execute(self, org_id, tool, args, *, initiated_by, pool):
            raise HTTPException(503, "Local agent tidak terhubung.")

    monkeypatch.setattr(local_agent_router, "get_manager", lambda: FakeManager())

    handler = _route(router, "/commands/{command_id}/approve", "POST")
    result = asyncio.run(handler(
        command_id="c1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "failed"


def test_reject_command_marks_rejected_and_never_calls_manager(monkeypatch):
    pool = FakePool(fetchrow_results=[
        {"id": "c1", "status": "rejected", "tool": "run_command", "args": "{}",
         "initiated_by": "user-1", "created_at": None, "rejected_reason": "tidak relevan"},
    ])
    router = _build_router(pool)

    def _should_not_be_called():
        raise AssertionError("reject must never call get_manager()/execute a risky action")
    monkeypatch.setattr(local_agent_router, "get_manager", lambda: _should_not_be_called())

    handler = _route(router, "/commands/{command_id}/reject", "POST")
    result = asyncio.run(handler(
        command_id="c1", body=LocalAgentRejectRequest(reason="tidak relevan"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "rejected"
    assert result["rejected_reason"] == "tidak relevan"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_reject_command_404_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/commands/{command_id}/reject", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            command_id="c1", body=LocalAgentRejectRequest(reason="x"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_history_route_accepts_status_filter():
    pool = FakePool(fetch_results=[[{"id": "c1", "status": "pending_approval"}]])
    router = _build_router(pool)
    handler = _route(router, "/local-agent/history", "GET")
    result = asyncio.run(handler(
        user={"org_id": "org-1", "id": "user-1"}, pool=pool, limit=50, status="pending_approval",
    ))
    assert len(result["commands"]) == 1
    assert any("status=$2" in c[1] for c in pool.calls)


def test_computer_agent_run_local_persists_risky_step_as_pending_approval(monkeypatch):
    """Regression test for the original bug: risky steps from
    /computer-agent/run-local were returned in the HTTP response but never
    persisted anywhere, so the 'check the approval queue' message pointed at
    a queue that could never show them. This asserts the row actually gets
    INSERTed with status='pending_approval' and its id is surfaced back."""
    pool = FakePool(fetchrow_results=[{"id": "cmd-123"}])

    class FakeManager:
        def is_connected(self, org_id):
            return True
        def get_meta(self, org_id):
            return {"hostname": "test-host"}
        _conn_ids = {}

    monkeypatch.setattr(local_agent_router, "get_manager", lambda: FakeManager())

    async def fake_call_llm(prompt: str) -> str:
        return '[{"tool": "run_command", "args": {"command": "rm -rf /tmp/x"}, "reason": "cleanup"}]'

    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    router = build_local_agent_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission,
        decode_token=lambda token: {"org": "org-1"},
        call_llm=fake_call_llm,
    )
    handler = _route(router, "/computer-agent/run-local", "POST")

    from bn_platform.local_agent_router import ComputerAgentRequest
    result = asyncio.run(handler(
        body=ComputerAgentRequest(goal="hapus file sementara"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))

    assert len(result["needs_approval"]) == 1
    assert result["needs_approval"][0]["id"] == "cmd-123"
    assert result["steps"][0]["command_id"] == "cmd-123"
    insert_calls = [c for c in pool.calls if c[0] == "fetchrow" and "INSERT INTO local_agent_commands" in c[1]]
    assert len(insert_calls) == 1
    assert "'pending_approval'" in insert_calls[0][1]
