"""
POST /bots and PATCH /bots/{bot_id} only had Depends(get_current_user) -- any
authenticated org member, including a Viewer with no bot-management rights,
could create or reconfigure bots (system_prompt, status, reasoning_mode,
etc). Every other bot-affecting surface (workflows, per the sibling fix in
test_workflow_builder.py) requires "bots.write".

Same constraint as the /org/plan fix (test_org_plan_permission.py): these are
plain main.py endpoints defined before the Phase 2 wiring block creates
require_permission, so they call the _platform_require_permission
placeholder manually inside the handler body instead of using
Depends(require_permission(...)) in the signature.
"""
import asyncio

import pytest
from fastapi import HTTPException

import main


class _FakePool:
    def __init__(self, *, bot_row=None):
        self.bot_row = bot_row
        self.executed = []

    async def fetchval(self, sql, *params):
        if "FROM bots" in sql:
            return 0
        if "bot_limit" in sql:
            return 10
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def fetchrow(self, sql, *params):
        if "FROM bots" in sql:
            return self.bot_row
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql, *params):
        self.executed.append((sql, params))
        return "OK"


def _allow_checker(permission_key):
    async def _checker(*, user, pool):
        return user
    return _checker


def _deny_checker(permission_key):
    async def _checker(*, user, pool):
        raise HTTPException(403, f"Akun Anda tidak memiliki izin '{permission_key}' untuk aksi ini.")
    return _checker


def test_create_bot_rejects_user_without_bots_write_permission(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _deny_checker)
    pool = _FakePool()
    user = {"id": "user-1", "org_id": "org-1", "role": "viewer"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.create_bot(main.BotCreateReq(name="Bot Baru"), user=user, pool=pool))

    assert exc_info.value.status_code == 403
    assert pool.executed == []


async def _fake_check_limit(pool, org_id, dimension):
    return True, {"plan": "test", "used": 0, "limit": 10}


def test_create_bot_allows_user_with_bots_write_permission(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    monkeypatch.setattr(main, "_platform_check_limit", _fake_check_limit)
    pool = _FakePool()
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}

    result = asyncio.run(main.create_bot(main.BotCreateReq(name="Bot Baru"), user=user, pool=pool))

    assert result["message"] == "Bot berhasil dibuat"
    assert any("INSERT INTO bots" in sql for sql, _ in pool.executed)


def test_create_bot_skips_check_when_platform_unavailable(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", None)
    monkeypatch.setattr(main, "_platform_check_limit", _fake_check_limit)
    pool = _FakePool()
    user = {"id": "user-1", "org_id": "org-1", "role": "viewer"}

    result = asyncio.run(main.create_bot(main.BotCreateReq(name="Bot Baru"), user=user, pool=pool))
    assert result["message"] == "Bot berhasil dibuat"


def test_update_bot_rejects_user_without_bots_write_permission(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _deny_checker)
    pool = _FakePool(bot_row={"id": "bot-1"})
    user = {"id": "user-1", "org_id": "org-1", "role": "viewer"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.update_bot("bot-1", main.BotUpdateReq(name="Baru"), user=user, pool=pool))

    assert exc_info.value.status_code == 403
    assert pool.executed == []


def test_update_bot_allows_user_with_bots_write_permission(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    pool = _FakePool(bot_row={"id": "bot-1"})
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}

    result = asyncio.run(main.update_bot("bot-1", main.BotUpdateReq(name="Baru"), user=user, pool=pool))

    assert result["message"] == "Bot diperbarui"
    assert len(pool.executed) == 1
