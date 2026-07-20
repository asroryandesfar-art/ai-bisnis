"""test_casper_engineer_router.py — bn_platform/casper_engineer_router.py:
RBAC gating (workforce.write untuk run, workforce.read untuk read) + route shape.
Mirror pola test_agent_center_router.py."""
import asyncio

import pytest
from fastapi import HTTPException

from bn_platform.casper_engineer_router import (
    build_casper_engineer_router, ExecuteStepRequest, _load_json,
)


class FakePool:
    pass


def _build(record_keys=None):
    async def get_pool():
        return FakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    def require_permission(key):
        if record_keys is not None:
            record_keys.append(key)
        async def _checker(user=None, pool=None):
            return {"org_id": "org-1", "id": "user-1"}
        return _checker

    return build_casper_engineer_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def _endpoint(router, suffix, method):
    for r in router.routes:
        if r.path.endswith(suffix) and method in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"route not found: {method} {suffix}")


def test_routes_exist():
    router = _build()
    paths = {(r.path, tuple(sorted(m for m in r.methods if m in ("GET", "POST")))) for r in router.routes}
    have = {p for p, _ in paths}
    assert any(p.endswith("/casper/engineer/run") for p in have)
    assert any(p.endswith("/casper/engineer/runs") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}/propose-steps") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}/execute-step") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}/steps") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}/investigate") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}/anchor") for p in have)


def test_execute_step_rejects_non_allowlisted_tool():
    router = _build()
    ep = _endpoint(router, "/run/{run_id}/execute-step", "POST")
    # Tool di luar allowlist -> 400 SEBELUM menyentuh pool/perangkat.
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ep("run-1", ExecuteStepRequest(tool="format_disk", args={}),
                       user={"org_id": "o", "id": "u"}, pool=FakePool()))
    assert ei.value.status_code == 400


def test_rbac_uses_workforce_permissions():
    keys = []
    _build(record_keys=keys)
    assert "workforce.write" in keys       # POST /run
    assert "workforce.read" in keys        # GET /runs + /run/{id}
    # tak pakai permission tak dikenal (yang akan meledak di make_permission_checker asli)
    assert set(keys) <= {"workforce.write", "workforce.read"}


def test_load_json_handles_str_dict_and_garbage():
    assert _load_json('{"a": 1}') == {"a": 1}
    assert _load_json({"a": 1}) == {"a": 1}
    assert _load_json(None) == {}
    assert _load_json("not json") == {}
