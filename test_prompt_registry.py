"""P2-B — Prompt Management: registry versi/rollback/A-B + BaseAgent fallback + API.

Pola sama test_jobs_router/test_evaluation: pool Postgres nyata, org efemeral,
panggil registry & endpoint LANGSUNG dalam satu event loop.
"""
import asyncio
import uuid

import asyncpg

import main
import feature_flags as ff
from prompt_registry import PromptRegistry, ensure_prompt_schema, set_prompt_registry
from prompt_registry.registry import _bucket


def _run_db(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_prompt_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "PromptTest", f"prm-{org[:8]}")
            try:
                await body(pool, org)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


# ── registry: versi & fallback ────────────────────────────────────────────────
def test_create_version_increments_and_resolve_default_fallback():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        name = f"cs_agent.system#{org[:8]}"
        v1 = await reg.create_version(name, "prompt v1", org_id=org)
        v2 = await reg.create_version(name, "prompt v2", org_id=org)
        assert v1["version"] == 1 and v2["version"] == 2
        # belum ada yang aktif → fallback ke default (byte-identik)
        rp = await reg.resolve(name, org_id=org, default="HARDCODED")
        assert rp.source == "default" and rp.content == "HARDCODED" and rp.version is None
    _run_db(body)


def test_activate_single_then_rollback_exclusive():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        name = f"finance.system#{org[:8]}"
        await reg.create_version(name, "v1", org_id=org)
        await reg.create_version(name, "v2", org_id=org, activate=True)   # aktif = v2
        rp = await reg.resolve(name, org_id=org, default="D")
        assert rp.source == "registry" and rp.content == "v2" and rp.version == 2
        # rollback ke v1 (exclusive → hanya 1 aktif)
        row = await reg.activate(name, 1, org_id=org, exclusive=True)
        assert row is not None and row["version"] == 1
        rp = await reg.resolve(name, org_id=org, default="D")
        assert rp.content == "v1" and rp.version == 1
        actives = [v for v in await reg.list_versions(name, org_id=org) if v["active"]]
        assert len(actives) == 1
    _run_db(body)


def test_activate_unknown_version_returns_none():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        name = f"hr.system#{org[:8]}"
        await reg.create_version(name, "v1", org_id=org)
        assert await reg.activate(name, 99, org_id=org) is None
    _run_db(body)


# ── A/B: >1 varian aktif, pilih deterministik & split ─────────────────────────
def test_ab_deterministic_and_split():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        name = f"marketing.system#{org[:8]}"
        await reg.create_version(name, "A", org_id=org, variant="A", weight=50)
        await reg.create_version(name, "B", org_id=org, variant="B", weight=50)
        await reg.activate(name, 1, org_id=org, variant="A", exclusive=False)
        await reg.activate(name, 1, org_id=org, variant="B", exclusive=False)
        # deterministik: bucket_key sama → hasil sama
        r1 = await reg.resolve(name, org_id=org, bucket_key="user-42")
        r2 = await reg.resolve(name, org_id=org, bucket_key="user-42")
        assert r1.content == r2.content and r1.content in ("A", "B")
        # kedua varian benar-benar terpakai lintas key
        seen = set()
        for i in range(60):
            seen.add((await reg.resolve(name, org_id=org, bucket_key=f"u{i}")).content)
        assert seen == {"A", "B"}
    _run_db(body)


def test_list_names_summary():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        base = f"listnames#{org[:8]}"
        n1, n2 = f"{base}.a", f"{base}.b"
        await reg.create_version(n1, "v1", org_id=org, activate=True)
        await reg.create_version(n1, "v2", org_id=org, variant="B")
        await reg.create_version(n2, "x", org_id=org)
        names = {r["name"]: r for r in await reg.list_names(org_id=org)}
        assert n1 in names and n2 in names
        assert names[n1]["versions"] == 2 and names[n1]["variants"] == 2
        assert names[n1]["active_versions"] == 1 and names[n1]["latest_version"] == 1
        assert names[n2]["active_versions"] == 0
    _run_db(body)


def test_bucket_deterministic_within_range():
    assert _bucket("n", "k", 10) == _bucket("n", "k", 10)
    assert 0 <= _bucket("n", "k", 7) < 7


# ── scoping: org menang atas global ───────────────────────────────────────────
def test_org_scoped_wins_over_global():
    async def body(pool, org):
        reg = PromptRegistry(pool)
        name = f"operations.system#{org[:8]}"
        await reg.create_version(name, "GLOBAL", org_id=None, activate=True)   # global default
        rp = await reg.resolve(name, org_id=org, default="D")
        assert rp.content == "GLOBAL"                                          # jatuh ke global
        await reg.create_version(name, "ORG", org_id=org, activate=True)       # override org
        rp = await reg.resolve(name, org_id=org, default="D")
        assert rp.content == "ORG"                                            # org menang
        try:
            await pool.execute("DELETE FROM agent_prompts WHERE name=$1", name)  # bersihkan baris global
        except Exception:
            pass
    _run_db(body)


# ── BaseAgent.resolved_system_prompt: flag-gated, fallback byte-identik ────────
def test_base_agent_resolved_prompt_flag_gated():
    from base import BaseAgent

    class _A(BaseAgent):
        name = f"probe_agent_{uuid.uuid4().hex[:6]}"
        system_prompt = "DEFAULT-HARDCODED"

    async def body(pool, org):
        reg = PromptRegistry(pool)
        set_prompt_registry(reg)
        ff.clear_all_overrides()
        agent = _A()
        # flag OFF → default byte-identik meski registry punya versi aktif
        await reg.create_version(f"{_A.name}.system", "FROM-REGISTRY", org_id=org, activate=True)
        assert await agent.resolved_system_prompt(org_id=org) == "DEFAULT-HARDCODED"
        # flag ON → pakai registry
        ff.set_override("prompt_registry", True)
        assert await agent.resolved_system_prompt(org_id=org) == "FROM-REGISTRY"
        # flag ON tapi tak ada versi aktif utk agen lain → fallback default
        agent2 = type("_B", (BaseAgent,), {"name": f"none_{uuid.uuid4().hex[:6]}",
                                           "system_prompt": "ONLY-DEFAULT"})()
        assert await agent2.resolved_system_prompt(org_id=org) == "ONLY-DEFAULT"
        ff.clear_all_overrides()
        set_prompt_registry(None)
    _run_db(body)


# ── Router API: panggil endpoint langsung ─────────────────────────────────────
def _router():
    from bn_platform.prompts_router import build_prompts_router

    async def get_pool():
        raise RuntimeError("unused")

    def require_permission(key):
        async def _checker(user=None, pool=None):
            return {"org_id": "unused", "id": "u1"}
        return _checker

    return build_prompts_router(get_pool=get_pool, require_permission=require_permission)


def _ep(router, suffix, method):
    for r in router.routes:
        if r.path.endswith(suffix) and method in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"route not found: {method} {suffix}")


def test_router_routes_exist():
    have = {r.path for r in _router().routes}
    assert any(p.endswith("/prompts/{name}") for p in have)
    assert any(p.endswith("/prompts/{name}/activate") for p in have)
    assert any(p.endswith("/prompts/{name}/resolve") for p in have)


def test_router_create_list_activate_resolve():
    from bn_platform.prompts_router import CreateVersionRequest, ActivateRequest
    router = _router()
    create = _ep(router, "/prompts/{name}", "POST")
    listv = _ep(router, "/prompts/{name}", "GET")
    activate = _ep(router, "/prompts/{name}/activate", "POST")
    resolve = _ep(router, "/prompts/{name}/resolve", "GET")

    async def body(pool, org):
        user = {"org_id": org, "id": "u1"}
        name = f"api.system#{org[:8]}"
        r1 = await create(name=name, body=CreateVersionRequest(content="c1"), user=user, pool=pool)
        assert r1["version"] == 1 and r1["active"] is False
        await create(name=name, body=CreateVersionRequest(content="c2", activate=True), user=user, pool=pool)
        rows = await listv(name=name, user=user, pool=pool)
        assert len(rows) == 2
        rp = await resolve(name=name, user=user, pool=pool, bucket_key=None)
        assert rp["content"] == "c2" and rp["source"] == "registry"
        act = await activate(name=name, body=ActivateRequest(version=1, exclusive=True), user=user, pool=pool)
        assert act["version"] == 1
        rp = await resolve(name=name, user=user, pool=pool, bucket_key=None)
        assert rp["content"] == "c1"
    _run_db(body)
