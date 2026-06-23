"""test_agent_center_router.py — bn_platform/agent_center.py: RBAC gating
(execution_log.read pada kedua route) dan response shape. Mirror pola
test_execution_log_router.py."""
import asyncio

from bn_platform.agent_center import build_agent_center_router


class FakePool:
    pass


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

    build_agent_center_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("execution_log.read") == 2
    assert set(requested_keys) == {"execution_log.read"}


def _build_router():
    pool = FakePool()

    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    def require_permission(_key):
        return get_current_user

    return build_agent_center_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    ), pool


def test_list_agents_route_returns_agents_key():
    router, pool = _build_router()
    handler = _route(router, "/agent-center/agents", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert len(result["agents"]) > 0
    assert all("skills" in a for a in result["agents"])


def test_overview_route_returns_combined_shape(monkeypatch):
    import execution_log
    import workforce_orchestrator
    import computer_agent

    async def fake_summary(pool, org_id):
        return {"by_source_type": {}, "by_status": {}}

    async def fake_dashboard(pool, org_id):
        return {}

    async def fake_list_tasks(pool, *, org_id, status=None, limit=50):
        return []

    monkeypatch.setattr(execution_log, "execution_log_summary", fake_summary)
    monkeypatch.setattr(workforce_orchestrator, "dashboard_summary", fake_dashboard)
    monkeypatch.setattr(computer_agent, "list_tasks", fake_list_tasks)

    router, pool = _build_router()
    handler = _route(router, "/agent-center/overview", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert "agents" in result
    assert "execution_log" in result
    assert "computer_agent_pending_approval_count" in result
