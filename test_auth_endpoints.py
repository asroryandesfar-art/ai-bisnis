"""Characterization tests for /auth/{register,login,logout}.

These endpoints had zero coverage and are security-critical, so this pins
current behavior (happy paths + every error branch) BEFORE the main.py
strangler split moves them into a router. Only the DB boundary is mocked
(via dependency_overrides); password hashing, token creation, and all
validation/branching run for real.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import main


class FakePool:
    """Minimal asyncpg-pool stand-in. `acquire()` yields the pool itself as the
    connection, so conn.* and pool.* share the same programmable behavior."""

    def __init__(self):
        self.fetchval_map: list[tuple[str, object]] = []
        self.fetchrow_value = None
        self.executed: list[str] = []

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool

            async def __aexit__(self, *a):
                return False

        return _Ctx()

    async def fetchval(self, sql, *args):
        for sub, val in self.fetchval_map:
            if sub in sql:
                return val
        return None

    async def fetchrow(self, sql, *args):
        return self.fetchrow_value

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "OK"


@pytest.fixture
def client(monkeypatch):
    # Get past the schema gate and the session/audit side effects without a DB.
    async def _schema_ok(_pool):
        return True

    async def _session(_pool, **_kw):
        return "sess-1"

    monkeypatch.setattr(main, "ensure_schema", _schema_ok)
    monkeypatch.setattr(main, "_start_session", _session)

    pool = FakePool()
    main.app.dependency_overrides[main.get_pool] = lambda: pool
    c = TestClient(main.app)
    c.fake_pool = pool
    try:
        yield c
    finally:
        main.app.dependency_overrides.pop(main.get_pool, None)
        main.app.dependency_overrides.pop(main.get_current_user, None)


# ── register ────────────────────────────────────────────────────

def test_register_creates_org_and_returns_token(client):
    client.fake_pool.fetchval_map = [("FROM users", None), ("FROM organizations", None)]
    r = client.post("/auth/register", json={
        "org_name": "Acme Travel", "email": "OWNER@acme.com",
        "password": "supersecret", "full_name": "Budi",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"] and isinstance(body["token"], str)
    assert body["org_id"]
    assert "trial_ends" in body
    # org + user inserts happened.
    assert any("INSERT INTO organizations" in s for s in client.fake_pool.executed)
    assert any("INSERT INTO users" in s for s in client.fake_pool.executed)


def test_register_rejects_duplicate_email(client):
    client.fake_pool.fetchval_map = [("FROM users", str(uuid.uuid4()))]
    r = client.post("/auth/register", json={
        "org_name": "Acme", "email": "dup@acme.com", "password": "supersecret",
    })
    assert r.status_code == 400
    assert "sudah terdaftar" in r.json()["detail"]


def test_register_enforces_min_password_length(client):
    r = client.post("/auth/register", json={
        "org_name": "Acme", "email": "x@acme.com", "password": "short",
    })
    assert r.status_code == 422  # pydantic Field(min_length=8)


# ── login ───────────────────────────────────────────────────────

def _user_row(password="supersecret", active=True):
    return {
        "id": uuid.uuid4(), "org_id": uuid.uuid4(),
        "hashed_password": main.hash_password(password), "is_active": active,
    }


def test_login_success_returns_token(client):
    client.fake_pool.fetchrow_value = _user_row(password="supersecret")
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})
    assert r.status_code == 200, r.text
    assert r.json()["token"]
    assert any("last_login_at" in s for s in client.fake_pool.executed)


def test_login_unknown_email_is_401(client):
    client.fake_pool.fetchrow_value = None
    r = client.post("/auth/login", json={"email": "nobody@b.com", "password": "whatever1"})
    assert r.status_code == 401
    assert "salah" in r.json()["detail"]


def test_login_wrong_password_is_401(client):
    client.fake_pool.fetchrow_value = _user_row(password="the-real-one")
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "wrong-guess"})
    assert r.status_code == 401


def test_login_inactive_account_is_403(client):
    client.fake_pool.fetchrow_value = _user_row(password="supersecret", active=False)
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})
    assert r.status_code == 403


def test_login_legacy_foreign_hash_returns_friendly_409(client):
    # A legacy/foreign hash (e.g. bcrypt from before the pbkdf2_sha256 switch)
    # must return the friendly 409 "please reset password", not a generic 500.
    # Regression guard for the is_supported_password_hash fix.
    row = _user_row()
    row["hashed_password"] = "$2b$12$abcdefghijklmnopqrstuuKk3s5j5j5j5j5j5j5j5j5j5j5j5j5j"  # bcrypt-style
    client.fake_pool.fetchrow_value = row
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})
    assert r.status_code == 409
    assert "reset password" in r.json()["detail"]


# ── logout ───────────────────────────────────────────────────────

def test_logout_returns_ok(client):
    main.app.dependency_overrides[main.get_current_user] = lambda: {
        "id": uuid.uuid4(), "org_id": uuid.uuid4(),
        "email": "a@b.com", "session_id": "sess-1",
    }
    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
