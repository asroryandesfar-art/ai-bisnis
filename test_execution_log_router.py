"""test_execution_log_router.py — bn_platform/execution_log.py: RBAC gating
(execution_log.read pada kedua route) dan response shape. Mirror pola
test_computer_agent_router.py."""
import asyncio

from bn_platform.execution_log import build_execution_log_router


class FakePool:
    def __init__(self, fetch_results=None):
        self.calls = []
        self._fetch_results = list(fetch_results or [])

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_router_gates_both_routes_with_execution_log_read():
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

    build_execution_log_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("execution_log.read") == 2
    assert set(requested_keys) == {"execution_log.read"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    def require_permission(_key):
        return get_current_user

    return build_execution_log_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_list_route_returns_entries_key():
    pool = FakePool(fetch_results=[[{"source_type": "chat_agent"}, {"source_type": "workflow"}]])
    router = _build_router(pool)
    handler = _route(router, "/execution-log", "GET")
    result = asyncio.run(handler(
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
        source_type=None, status=None, limit=50,
    ))
    assert len(result["entries"]) == 2


def test_summary_route_returns_aggregated_shape():
    pool = FakePool(fetch_results=[[{"source_type": "workflow", "status": "success", "cnt": 3}]])
    router = _build_router(pool)
    handler = _route(router, "/execution-log/summary", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert result["by_source_type"]["workflow"] == 3
    assert result["by_status"]["success"] == 3
