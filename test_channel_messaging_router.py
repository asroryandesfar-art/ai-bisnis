"""test_channel_messaging_router.py — bn_platform/channel_messaging.py: RBAC
gating per route (read/approve tier) and approve/reject endpoint behavior.
Mirror pola test_computer_agent_router.py."""
import asyncio

import pytest
from fastapi import HTTPException

from bn_platform.channel_messaging import build_channel_messaging_router, RejectTaskRequest


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
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


def test_router_gates_every_route_with_correct_permission_tier():
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

    build_channel_messaging_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
    )

    assert requested_keys.count("channel_messaging.read") == 2     # list + get
    assert requested_keys.count("channel_messaging.approve") == 2  # approve + reject
    assert set(requested_keys) == {"channel_messaging.read", "channel_messaging.approve"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_channel_messaging_router(
        get_pool=get_pool, get_current_user=get_current_user, require_permission=require_permission,
    )


def test_get_task_route_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}", "GET")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(task_id="t1", user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert exc.value.status_code == 404


def test_approve_task_route_404_when_not_pending_approval():
    pool = FakePool(fetchrow_results=[{"id": "t1", "status": "sent"}])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}/approve", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            task_id="t1", user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404


def test_reject_task_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[
        {"id": "t1", "status": "pending_approval"},
        {"id": "t1", "status": "rejected", "rejected_reason": "tidak relevan"},
    ])
    router = _build_router(pool)
    handler = _route(router, "/tasks/{task_id}/reject", "POST")
    result = asyncio.run(handler(
        task_id="t1", body=RejectTaskRequest(reason="tidak relevan"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "rejected"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_list_tasks_route_returns_tasks_key():
    pool = FakePool(fetch_results=[[{"id": "t1"}, {"id": "t2"}]])
    router = _build_router(pool)
    handler = _route(router, "/tasks", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1"}, pool=pool, status=None, limit=50))
    assert len(result["tasks"]) == 2
