"""Tests untuk Enterprise Security Platform: session management (active
sessions, revoke, suspicious login detection), API key rotation/expiration/
usage tracking, security event feed, dan endpoint baru di
bn_platform/security.py (build_security_router: /sessions, /sessions/{id}/revoke,
/api-keys/{id}/rotate, /dashboard).

Mengikuti pola FakePool + _route (test_workflow_builder.py /
test_knowledge_builder.py) — tidak ada koneksi database sungguhan.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from bn_platform.security import (
    create_session,
    touch_session,
    list_sessions,
    revoke_session,
    generate_api_key,
    record_api_key_usage,
    authenticate_api_key,
    rotate_api_key,
    list_security_events,
    run_security_scan,
    build_security_router,
    write_audit_log,
)
from bn_platform.observability import metrics_snapshot


# ─── Helpers ────────────────────────────────────────────────────

def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakePool:
    """Pool sederhana: cocokkan query via substring (urutan dicoba berurutan,
    pola lebih spesifik harus didaftarkan lebih dulu)."""

    def __init__(self, fetch_results=None, fetchrow_results=None):
        self.fetch_results = fetch_results or []      # list of (substring, value|callable)
        self.fetchrow_results = fetchrow_results or []  # list of (substring, value|callable)
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


# ─── Session management ────────────────────────────────────────

def test_create_session_not_suspicious_without_prior_ips():
    pool = FakePool(
        fetch_results=[("SELECT DISTINCT ip_address FROM sessions", [])],
        fetchrow_results=[("INSERT INTO sessions", {"id": "sess-1", "is_suspicious": False})],
    )
    result = asyncio.run(create_session(
        pool, user_id="user-1", org_id="org-1", ip_address="1.2.3.4", user_agent="UA",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    assert result == {"id": "sess-1", "is_suspicious": False}


def test_create_session_detects_suspicious_new_ip():
    pool = FakePool(
        fetch_results=[("SELECT DISTINCT ip_address FROM sessions", [{"ip_address": "1.1.1.1"}])],
        fetchrow_results=[("INSERT INTO sessions", lambda args: {"id": "sess-2", "is_suspicious": args[4]})],
    )
    result = asyncio.run(create_session(
        pool, user_id="user-1", org_id="org-1", ip_address="9.9.9.9", user_agent="UA",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    assert result["is_suspicious"] is True


def test_create_session_known_ip_not_suspicious():
    pool = FakePool(
        fetch_results=[("SELECT DISTINCT ip_address FROM sessions", [{"ip_address": "9.9.9.9"}])],
        fetchrow_results=[("INSERT INTO sessions", lambda args: {"id": "sess-3", "is_suspicious": args[4]})],
    )
    result = asyncio.run(create_session(
        pool, user_id="user-1", org_id="org-1", ip_address="9.9.9.9", user_agent="UA",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    assert result["is_suspicious"] is False


def test_touch_session_active_vs_revoked():
    pool_active = FakePool(fetchrow_results=[("UPDATE sessions SET last_seen_at=NOW()", {"id": "sess-1"})])
    assert asyncio.run(touch_session(pool_active, "sess-1")) is True

    pool_revoked = FakePool(fetchrow_results=[("UPDATE sessions SET last_seen_at=NOW()", None)])
    assert asyncio.run(touch_session(pool_revoked, "sess-1")) is False


def test_list_sessions_scopes_org_vs_user():
    rows = [{
        "id": "sess-1", "user_id": "user-1", "user_email": "a@x.com", "ip_address": "1.2.3.4",
        "user_agent": "UA", "is_suspicious": False, "created_at": "now", "last_seen_at": "now",
        "expires_at": "later", "revoked_at": None,
    }]
    pool = FakePool(fetch_results=[("FROM sessions s JOIN users u", rows)])

    result = asyncio.run(list_sessions(pool, org_id="org-1"))
    assert result == rows
    _, sql, params = pool.calls[-1]
    assert "s.org_id=$1" in " ".join(sql.split())
    assert params == ("org-1",)

    asyncio.run(list_sessions(pool, org_id="org-1", user_id="user-1"))
    _, sql, params = pool.calls[-1]
    assert "s.user_id=$2" in " ".join(sql.split())
    assert params == ("org-1", "user-1")


def test_revoke_session_success_and_already_revoked():
    pool = FakePool(fetchrow_results=[("UPDATE sessions SET revoked_at=NOW()", {"id": "sess-1", "user_id": "user-1"})])
    result = asyncio.run(revoke_session(pool, session_id="sess-1", org_id="org-1"))
    assert result == {"id": "sess-1", "user_id": "user-1"}

    pool_none = FakePool(fetchrow_results=[("UPDATE sessions SET revoked_at=NOW()", None)])
    assert asyncio.run(revoke_session(pool_none, session_id="sess-1", org_id="org-1")) is None


# ─── API key: generation, usage, rotation ──────────────────────

def test_generate_api_key_format():
    raw, prefix = generate_api_key()
    assert raw.startswith("bn_live_")
    assert prefix == raw[:14]
    assert len(prefix) == 14


def test_record_api_key_usage_increments_counter():
    pool = FakePool()
    asyncio.run(record_api_key_usage(pool, "key-1"))
    assert pool.calls[0][0] == "execute"
    assert "usage_count=usage_count+1" in pool.calls[0][1]
    assert pool.calls[0][2] == ("key-1",)


def test_authenticate_api_key_valid_records_usage():
    raw, prefix = generate_api_key()
    row = {"id": "key-1", "org_id": "org-1", "key_hash": "hashed", "scopes": ["chat:write"],
           "is_active": True, "expires_at": None}
    pool = FakePool(fetch_results=[("FROM api_keys WHERE key_prefix=$1", [row])])

    result = asyncio.run(authenticate_api_key(pool, raw, verify_password=lambda plain, hashed: hashed == "hashed"))
    assert result == {"id": "key-1", "org_id": "org-1", "scopes": ["chat:write"]}
    assert any(call[0] == "execute" and "usage_count" in call[1] for call in pool.calls)


def test_authenticate_api_key_rejects_invalid_prefix():
    pool = FakePool()
    result = asyncio.run(authenticate_api_key(pool, "not-a-key", verify_password=lambda *a: True))
    assert result is None


def test_authenticate_api_key_rejects_expired_or_inactive():
    raw, _ = generate_api_key()
    expired_row = {"id": "key-1", "org_id": "org-1", "key_hash": "hashed", "scopes": [],
                    "is_active": True, "expires_at": datetime.now(timezone.utc) - timedelta(days=1)}
    pool = FakePool(fetch_results=[("FROM api_keys WHERE key_prefix=$1", [expired_row])])
    assert asyncio.run(authenticate_api_key(pool, raw, verify_password=lambda *a: True)) is None

    inactive_row = {**expired_row, "is_active": False, "expires_at": None}
    pool2 = FakePool(fetch_results=[("FROM api_keys WHERE key_prefix=$1", [inactive_row])])
    assert asyncio.run(authenticate_api_key(pool2, raw, verify_password=lambda *a: True)) is None


def test_rotate_api_key_success_and_not_found():
    pool = FakePool(fetchrow_results=[("UPDATE api_keys SET key_hash=", {"id": "key-1"})])
    raw = asyncio.run(rotate_api_key(pool, key_id="key-1", org_id="org-1", hash_password=lambda x: f"hashed:{x}"))
    assert raw.startswith("bn_live_")

    pool_none = FakePool(fetchrow_results=[("UPDATE api_keys SET key_hash=", None)])
    assert asyncio.run(rotate_api_key(pool_none, key_id="key-1", org_id="org-1", hash_password=lambda x: x)) is None


# ─── Security events & automated scan ──────────────────────────

def test_list_security_events_queries_audit_logs():
    rows = [{"id": "log-1", "actor_email": "a@x.com", "action": "login_failed",
             "resource_type": "user", "resource_id": "user-1", "ip_address": "1.2.3.4",
             "metadata": {}, "created_at": "now"}]
    pool = FakePool(fetch_results=[("(action IN", rows)])
    result = asyncio.run(list_security_events(pool, org_id="org-1"))
    assert result == rows


def test_run_security_scan_includes_suspicious_login_finding():
    pool = FakePool(fetch_results=[("s.is_suspicious=TRUE", [{"id": "sess-1", "email": "user@x.com"}])])
    result = asyncio.run(run_security_scan(pool, org_id="org-1"))
    finding = next(f for f in result["findings"] if f["category"] == "sessions")
    assert "user@x.com" in finding["title"]
    assert any(call[0] == "execute" and "security_scan" in call[2] for call in pool.calls)


# ─── Router: /security/sessions, /api-keys/{id}/rotate, /dashboard ─

def _build_router(pool, *, permissions=None):
    permissions = permissions or set()

    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@x.com"}

    def require_permission(key):
        async def _checker(user, pool):
            if key not in permissions:
                raise HTTPException(403, f"Tidak punya izin: {key}")
            return user
        return _checker

    return build_security_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, hash_password=lambda x: f"hashed:{x}",
    )


def _user():
    return {"org_id": "org-1", "id": "user-1", "email": "owner@x.com"}


def test_get_sessions_scope_me():
    rows = [{"id": "sess-1", "user_id": "user-1", "user_email": "owner@x.com"}]
    pool = FakePool(fetch_results=[("FROM sessions s JOIN users u", rows)])
    router = _build_router(pool)
    handler = _route(router, "/sessions", "GET")
    result = asyncio.run(handler(user=_user(), pool=pool, scope="me"))
    assert result == {"sessions": rows}
    _, sql, params = pool.calls[-1]
    assert "s.user_id=$2" in " ".join(sql.split())
    assert params == ("org-1", "user-1")


def test_get_sessions_scope_org_requires_permission():
    pool = FakePool(fetch_results=[("FROM sessions s JOIN users u", [])])
    router = _build_router(pool, permissions=set())
    handler = _route(router, "/sessions", "GET")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(user=_user(), pool=pool, scope="org"))
    assert exc.value.status_code == 403


def test_get_sessions_scope_org_with_permission():
    rows = [{"id": "sess-1", "user_id": "other-user", "user_email": "other@x.com"}]
    pool = FakePool(fetch_results=[("FROM sessions s JOIN users u", rows)])
    router = _build_router(pool, permissions={"audit.read"})
    handler = _route(router, "/sessions", "GET")
    result = asyncio.run(handler(user=_user(), pool=pool, scope="org"))
    assert result == {"sessions": rows}


def test_revoke_own_session_succeeds_without_team_manage():
    pool = FakePool(
        fetchrow_results=[
            ("SELECT user_id FROM sessions WHERE id=$1 AND org_id=$2", {"user_id": "user-1"}),
            ("UPDATE sessions SET revoked_at=NOW()", {"id": "sess-1", "user_id": "user-1"}),
        ],
    )
    router = _build_router(pool, permissions=set())
    handler = _route(router, "/sessions/{session_id}/revoke", "POST")
    result = asyncio.run(handler(session_id="sess-1", user=_user(), pool=pool))
    assert result == {"ok": True}


def test_revoke_other_users_session_requires_team_manage():
    pool = FakePool(
        fetchrow_results=[
            ("SELECT user_id FROM sessions WHERE id=$1 AND org_id=$2", {"user_id": "other-user"}),
            ("UPDATE sessions SET revoked_at=NOW()", {"id": "sess-2", "user_id": "other-user"}),
        ],
    )
    router = _build_router(pool, permissions=set())
    handler = _route(router, "/sessions/{session_id}/revoke", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(session_id="sess-2", user=_user(), pool=pool))
    assert exc.value.status_code == 403

    router_admin = _build_router(pool, permissions={"team.manage"})
    handler_admin = _route(router_admin, "/sessions/{session_id}/revoke", "POST")
    result = asyncio.run(handler_admin(session_id="sess-2", user=_user(), pool=pool))
    assert result == {"ok": True}


def test_revoke_session_not_found():
    pool = FakePool(fetchrow_results=[("SELECT user_id FROM sessions WHERE id=$1 AND org_id=$2", None)])
    router = _build_router(pool)
    handler = _route(router, "/sessions/{session_id}/revoke", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(session_id="missing", user=_user(), pool=pool))
    assert exc.value.status_code == 404


def test_rotate_api_key_route_success_and_not_found():
    pool = FakePool(fetchrow_results=[("UPDATE api_keys SET key_hash=", {"id": "key-1"})])
    router = _build_router(pool, permissions={"apikeys.manage"})
    handler = _route(router, "/api-keys/{key_id}/rotate", "POST")
    result = asyncio.run(handler(key_id="key-1", user=_user(), pool=pool))
    assert result["key"].startswith("bn_live_")

    pool_none = FakePool(fetchrow_results=[("UPDATE api_keys SET key_hash=", None)])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(key_id="missing", user=_user(), pool=pool_none))
    assert exc.value.status_code == 404


def test_security_dashboard_aggregates_summary():
    sessions = [{"id": "sess-1", "user_id": "user-1", "is_suspicious": True}]
    audit_logs = [{"id": "log-1", "action": "login", "actor_user_id": "user-1", "actor_email": "owner@x.com",
                    "resource_type": "user", "resource_id": "user-1", "ip_address": "1.2.3.4",
                    "metadata": {}, "created_at": "now"}]
    security_events = [{"id": "log-2", "actor_email": "owner@x.com", "action": "login_failed",
                         "resource_type": "user", "resource_id": "user-1", "ip_address": "1.2.3.4",
                         "metadata": {}, "created_at": "now"}]
    api_keys = [{"id": "key-1", "name": "Integration", "key_prefix": "bn_live_abcd12", "scopes": [],
                  "usage_count": 5, "last_used_at": "now", "rotated_at": None, "expires_at": None,
                  "is_active": True, "created_at": "now"}]
    pool = FakePool(fetch_results=[
        ("s.id, s.user_id, u.email AS user_email", sessions),
        ("actor_user_id, actor_email, action, resource_type", audit_logs),
        ("(action IN", security_events),
        ("FROM api_keys WHERE org_id=$1", api_keys),
        # run_security_scan() sub-queries (kini juga dipanggil oleh /dashboard
        # lewat security_agent.dashboard_summary, AI Workforce Phase 5) --
        # default ke [] lewat FakePool, kecuali yang sengaja dicocokkan di atas.
    ])
    router = _build_router(pool, permissions={"audit.read"})
    handler = _route(router, "/dashboard", "GET")
    result = asyncio.run(handler(user=_user(), pool=pool))
    assert result["active_sessions_count"] == 1
    assert result["suspicious_sessions_count"] == 1
    assert result["active_api_keys_count"] == 1
    assert result["audit_logs"] == audit_logs
    assert result["security_events"] == security_events
    assert result["api_keys"] == api_keys


def test_write_audit_log_failure_is_counted_and_does_not_raise():
    """write_audit_log() must stay fail-open (caller flows must not crash if
    audit_logs insert fails), but the failure needs to be visible somewhere
    other than a log line that's easy to miss -- it's now counted in the
    bn_audit_log_failures_total Prometheus counter, surfaced via
    metrics_snapshot()/system_health."""
    class _BoomPool:
        async def execute(self, sql, *args):
            raise RuntimeError("simulated DB failure")

    before = metrics_snapshot()["audit_log_failures_total"]

    asyncio.run(write_audit_log(
        _BoomPool(), org_id="org-1", actor_user_id="user-1", actor_email="owner@x.com",
        action="update", resource_type="bot", resource_id="bot-1",
    ))

    after = metrics_snapshot()["audit_log_failures_total"]
    assert after == before + 1
