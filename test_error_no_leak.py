"""M-01 — endpoint auth tidak boleh membocorkan detail exception internal.

Memaksa error internal di login/register lalu memastikan pesan ke klien
generik (tanpa detail DB/skema) dan status 500.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException

import main

_SECRET_MARKER = "SENSITIVE_DB_DETAIL_zzz_do_not_leak"


def _fake_request():
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host="203.0.113.5"),
        headers={},
    )


@pytest.fixture(autouse=True)
def _schema_ok(monkeypatch):
    async def _ok(pool):
        return True
    monkeypatch.setattr(main, "ensure_schema", _ok)


def test_login_hides_internal_error(monkeypatch):
    class _Pool:
        async def fetchrow(self, *a, **k):
            raise RuntimeError(_SECRET_MARKER)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.login(
            main.LoginReq(email="a@b.com", password="x"),
            _fake_request(), pool=_Pool(),
        ))
    assert exc.value.status_code == 500
    assert _SECRET_MARKER not in str(exc.value.detail)


def test_register_hides_internal_error(monkeypatch):
    class _Pool:
        def acquire(self, *a, **k):
            raise RuntimeError(_SECRET_MARKER)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.register(
            main.RegisterReq(org_name="Org", email="a@b.com", password="password123"),
            _fake_request(), pool=_Pool(),
        ))
    assert exc.value.status_code == 500
    assert _SECRET_MARKER not in str(exc.value.detail)
