"""
test_action_executor_router.py — Tes unit untuk Action Executor Router.

Menggunakan pola FakePool yang sudah establish di codebase ini.
"""
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bn_platform.action_executor_router import build_action_executor_router


# ─── FakePool ─────────────────────────────────────────────────────────────────

class FakePool:
    def __init__(self, rows_by_query: dict | None = None):
        self._rows = rows_by_query or {}

    def _match(self, sql: str):
        for key, val in self._rows.items():
            if key in sql:
                return val
        return []

    async def fetch(self, sql, *args, **kwargs):
        result = self._match(sql)
        if isinstance(result, list):
            return [dict(r) if isinstance(r, dict) else r for r in result]
        return []

    async def fetchrow(self, sql, *args, **kwargs):
        result = self._match(sql)
        if isinstance(result, list) and result:
            r = result[0]
            return dict(r) if isinstance(r, dict) else r
        if isinstance(result, dict):
            return result
        return None

    async def fetchval(self, sql, *args, **kwargs):
        result = self._match(sql)
        if isinstance(result, list) and result:
            return list(result[0].values())[0] if isinstance(result[0], dict) else result[0]
        return result

    async def execute(self, sql, *args, **kwargs):
        return "OK"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(org_id="org-abc", user_id="user-123", role="owner"):
    return {"org_id": org_id, "user_id": user_id, "role": role}


def _build_router(pool, rows=None):
    """Buat router dengan fake dependencies."""
    fake_pool = FakePool(rows or {})

    def get_pool():
        return fake_pool

    def get_current_user():
        return make_user()

    def require_permission(perm):
        async def dep():
            return make_user()
        return dep

    def get_agent_config(pool):
        return {"api_key": None, "model": "test"}

    router = build_action_executor_router(
        get_pool=get_pool,
        get_current_user=get_current_user,
        require_permission=require_permission,
        get_agent_config=get_agent_config,
    )
    return router, fake_pool


# ─── Helper: invoke route handler langsung ────────────────────────────────────

async def _route(router, method: str, path: str):
    """Cari route handler di router berdasarkan method dan path prefix."""
    for route in router.routes:
        if hasattr(route, "methods") and method.upper() in route.methods:
            if route.path == path or path.startswith(route.path.split("{")[0].rstrip("/")):
                return route.endpoint
    return None


# ─── Tests: RBAC gating ───────────────────────────────────────────────────────

def test_router_has_expected_routes():
    router, _ = _build_router(None)
    paths = {r.path for r in router.routes}
    assert "/permission/grants" in paths
    assert "/terminal/execute" in paths
    assert "/terminal/history" in paths
    assert "/sandbox/sessions" in paths
    assert "/agent/execute" in paths
    assert "/agent/executions" in paths
    assert "/agent/audit-log" in paths


def test_router_permission_gating_count():
    """Pastikan semua route punya require_permission (bukan bebas akses)."""
    router, _ = _build_router(None)
    routes_with_deps = 0
    for route in router.routes:
        if hasattr(route, "dependant") and route.dependant.dependencies:
            routes_with_deps += 1
    assert routes_with_deps >= 7, f"Harus ada minimal 7 routes dengan dependency, dapat {routes_with_deps}"


# ─── Tests: terminal/history ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_terminal_history_returns_logs():
    rows = {
        "FROM agent_audit_log": [
            {"id": "log-1", "action_type": "terminal_execute", "target": "ls -la",
             "status": "completed", "duration_ms": 50, "created_at": "2026-06-28T00:00:00Z",
             "agent_name": "terminal_api", "initiated_by": "agent", "approved_by": None,
             "error": None, "updated_at": "2026-06-28T00:00:00Z"},
        ]
    }
    router, fake_pool = _build_router(None, rows)
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/terminal/history":
            handler = route.endpoint
            break
    assert handler is not None

    with patch("audit_logger.list_logs", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = rows["FROM agent_audit_log"]
        result = await handler(limit=10, user=user, pool=fake_pool)

    assert result["total"] == 1
    assert result["history"][0]["action_type"] == "terminal_execute"


# ─── Tests: sandbox sessions list ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_sandbox_sessions_empty():
    router, fake_pool = _build_router(None)
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/sandbox/sessions" and "GET" in (getattr(route, "methods", set())):
            handler = route.endpoint
            break
    assert handler is not None

    result = await handler(user=user, pool=fake_pool)
    assert "sessions" in result
    assert isinstance(result["sessions"], list)


# ─── Tests: agent executions list ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_agent_executions():
    rows = {
        "FROM agent_action_executions": [
            {"id": "exec-1", "goal": "test goal", "status": "completed",
             "summary": "done", "duration_ms": 1000,
             "created_at": "2026-06-28T00:00:00Z"},
        ]
    }
    router, fake_pool = _build_router(None, rows)
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/agent/executions" and "GET" in (getattr(route, "methods", set())):
            handler = route.endpoint
            break
    assert handler is not None

    result = await handler(status=None, limit=20, user=user, pool=fake_pool)
    assert result["total"] == 1
    assert result["executions"][0]["goal"] == "test goal"


@pytest.mark.asyncio
async def test_get_agent_execution_not_found():
    from fastapi import HTTPException
    router, fake_pool = _build_router(None, {})  # empty — fetchrow returns None
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/agent/executions/{execution_id}":
            handler = route.endpoint
            break
    assert handler is not None

    with pytest.raises(HTTPException) as exc:
        await handler(execution_id="nonexistent", user=user, pool=fake_pool)
    assert exc.value.status_code == 404


# ─── Tests: permission grants ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_permission_grants():
    rows = {
        "FROM agent_permission_grants": [
            {"id": "grant-1", "permission": "run_terminal", "mode": "allow_always",
             "resource": "", "reason": "test", "granted_by": "user-1",
             "created_at": "2026-06-28T00:00:00Z", "expires_at": None},
        ]
    }
    router, fake_pool = _build_router(None, rows)
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/permission/grants" and "GET" in (getattr(route, "methods", set())):
            handler = route.endpoint
            break
    assert handler is not None

    result = await handler(permission=None, user=user, pool=fake_pool)
    assert result["grants"][0]["permission"] == "run_terminal"


@pytest.mark.asyncio
async def test_revoke_permission_grant_not_found():
    from fastapi import HTTPException
    router, fake_pool = _build_router(None, {})
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/permission/grants/{grant_id}" and "DELETE" in (getattr(route, "methods", set())):
            handler = route.endpoint
            break
    assert handler is not None

    with pytest.raises(HTTPException) as exc:
        await handler(grant_id="nonexistent", user=user, pool=fake_pool)
    assert exc.value.status_code == 404


# ─── Tests: audit log ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_audit_log():
    router, fake_pool = _build_router(None)
    user = make_user()

    handler = None
    for route in router.routes:
        if route.path == "/agent/audit-log":
            handler = route.endpoint
            break
    assert handler is not None

    with patch("audit_logger.list_logs", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        result = await handler(action_type=None, status=None, limit=20, user=user, pool=fake_pool)

    assert result["total"] == 0
    assert result["logs"] == []
