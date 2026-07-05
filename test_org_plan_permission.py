"""
PATCH /org/plan let any authenticated org member (including a Viewer role)
change their own org's billing plan/limits -- it only had
Depends(get_current_user), no permission check at all. Every other
plan/limit-mutating endpoint (e.g. bn_platform/billing.py's /cancel) requires
the "billing.manage" permission.

main.py's plain (non-bn_platform) endpoints can't use
Depends(require_permission(...)) directly in their signature because
require_permission is only created later, inside the Phase 2 wiring's `try`
block at the bottom of the file (factory-pattern DI to avoid circular
imports) -- a default-parameter Depends(...) would be evaluated at function
*definition* time, long before that block runs, and raise NameError.

So the fix manually invokes the checker inside the handler body via the new
module-level `_platform_require_permission` placeholder (same pattern
bn_platform/security.py already uses for conditional/scoped checks:
`await require_permission(key)(user=user, pool=pool)`), guarded by `if
_platform_require_permission` the same way every other `_platform_*`
callback in main.py degrades gracefully when bn_platform fails to import.
"""
import asyncio

import pytest
from fastapi import HTTPException

import main


class _FakePool:
    def __init__(self, active_bots=0, docs_count=0, current_plan="scale"):
        self.active_bots = active_bots
        self.docs_count = docs_count
        self.current_plan = current_plan
        self.executed = []

    async def fetchval(self, sql, *params):
        if "SELECT plan FROM organizations" in sql:
            return self.current_plan
        if "FROM bots" in sql:
            return self.active_bots
        if "FROM documents" in sql:
            return self.docs_count
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def execute(self, sql, *params):
        self.executed.append((sql, params))
        return "UPDATE 1"


def _allow_checker(permission_key):
    async def _checker(*, user, pool):
        return user
    return _checker


def _deny_checker(permission_key):
    async def _checker(*, user, pool):
        raise HTTPException(403, f"Akun Anda tidak memiliki izin '{permission_key}' untuk aksi ini.")
    return _checker


def test_update_org_plan_rejects_user_without_billing_manage_permission(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _deny_checker)
    pool = _FakePool()
    user = {"id": "user-1", "org_id": "org-1", "role": "viewer"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="scale"), user=user, pool=pool))

    assert exc_info.value.status_code == 403
    assert pool.executed == []  # plan tidak boleh berubah kalau ditolak


def test_update_org_plan_allows_downgrade_with_permission(monkeypatch):
    """Owner boleh DOWNGRADE (scale -> growth) lewat endpoint legacy ini."""
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    pool = _FakePool(current_plan="scale")
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}

    result = asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="growth"), user=user, pool=pool))

    assert result["plan"] == "growth"
    assert len(pool.executed) == 1


def test_update_org_plan_allows_same_tier(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    pool = _FakePool(current_plan="growth")
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}
    result = asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="growth"), user=user, pool=pool))
    assert result["plan"] == "growth"


def test_update_org_plan_blocks_free_upgrade(monkeypatch):
    """H-01/H-02: upgrade ke tier lebih tinggi TANPA pembayaran ditolak 402,
    walau punya izin billing.manage."""
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    pool = _FakePool(current_plan="starter")
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="scale"), user=user, pool=pool))

    assert exc_info.value.status_code == 402
    assert pool.executed == []  # plan tidak berubah


def test_update_org_plan_still_validates_downgrade_limits_after_permission_check(monkeypatch):
    monkeypatch.setattr(main, "_platform_require_permission", _allow_checker)
    pool = _FakePool(active_bots=5, docs_count=0, current_plan="scale")
    user = {"id": "user-1", "org_id": "org-1", "role": "owner"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="starter"), user=user, pool=pool))

    assert exc_info.value.status_code == 409
    assert pool.executed == []


def test_update_org_plan_blocks_upgrade_even_when_platform_unavailable(monkeypatch):
    """Guard upgrade-tanpa-bayar independen dari wiring RBAC: walau
    _platform_require_permission None, upgrade tetap ditolak 402."""
    monkeypatch.setattr(main, "_platform_require_permission", None)
    pool = _FakePool(current_plan="starter")
    user = {"id": "user-1", "org_id": "org-1", "role": "viewer"}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.update_org_plan(main.OrgPlanUpdateReq(plan="growth"), user=user, pool=pool))
    assert exc_info.value.status_code == 402
