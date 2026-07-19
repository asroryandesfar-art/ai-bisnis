"""test_casper_engineer_router.py — bn_platform/casper_engineer_router.py:
RBAC gating (workforce.write untuk run, workforce.read untuk read) + route shape.
Mirror pola test_agent_center_router.py."""
from bn_platform.casper_engineer_router import build_casper_engineer_router, _load_json


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


def test_routes_exist():
    router = _build()
    paths = {(r.path, tuple(sorted(m for m in r.methods if m in ("GET", "POST")))) for r in router.routes}
    have = {p for p, _ in paths}
    assert any(p.endswith("/casper/engineer/run") for p in have)
    assert any(p.endswith("/casper/engineer/runs") for p in have)
    assert any(p.endswith("/casper/engineer/run/{run_id}") for p in have)


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
