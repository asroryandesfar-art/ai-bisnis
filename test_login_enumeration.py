"""L-01 — login tidak boleh membocorkan keberadaan email lewat timing.

Memastikan cabang 'email tidak ditemukan' TETAP menjalankan verify password
(terhadap hash dummy) sehingga durasi setara dengan email yang ada.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException

import main


def _fake_request():
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host="203.0.113.7"), headers={},
    )


@pytest.fixture(autouse=True)
def _schema_ok(monkeypatch):
    async def _ok(pool):
        return True
    monkeypatch.setattr(main, "ensure_schema", _ok)


def test_dummy_hash_is_valid():
    assert main.verify_password("timing-equalization-not-a-real-password", main._DUMMY_PWD_HASH)


def test_unknown_email_still_runs_password_verify(monkeypatch):
    calls = {"n": 0, "hashes": []}
    real_verify = main.verify_password

    def _spy(plain, hashed):
        calls["n"] += 1
        calls["hashes"].append(hashed)
        return real_verify(plain, hashed)

    monkeypatch.setattr(main, "verify_password", _spy)

    class _Pool:
        async def fetchrow(self, *a, **k):
            return None  # email tidak ditemukan
        async def execute(self, *a, **k):
            return "UPDATE 0"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.login(
            main.LoginReq(email="ghost@nowhere.test", password="whatever"),
            _fake_request(), pool=_Pool(),
        ))
    assert exc.value.status_code == 401
    # verify dipanggil walau email tak ada (timing equalization) memakai dummy hash
    assert calls["n"] >= 1
    assert main._DUMMY_PWD_HASH in calls["hashes"]
