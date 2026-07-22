"""P1-C.2 — policy hooks: loader per-org (DB) + gate execute_tool (block/approval).

Pola DB nyata (org efemeral). Gate flag-gated `policy_engine` + fail-open.
"""
import asyncio
import uuid

import asyncpg

import main
import feature_flags as ff
from policy_engine import ensure_policy_schema, load_org_policy, set_org_policy, BLOCK, APPROVAL
import policy_engine.loader as loader
import tool_executor


def _run_db(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_policy_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "PolTest", f"pol-{org[:8]}")
            loader._cache.clear()
            ff.clear_all_overrides()
            try:
                await body(pool, org)
            finally:
                ff.clear_all_overrides()
                loader._cache.clear()
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


# ── loader per-org ────────────────────────────────────────────────────────────
def test_load_default_when_no_row():
    async def body(pool, org):
        pol = await load_org_policy(pool, org)
        # default: run_command berbahaya, domain apapun allow
        assert pol.check_tool("run_command").action == APPROVAL
        assert pol.check_url("https://ok.example").action != BLOCK
    _run_db(body)


def test_set_and_load_org_rules_merges_over_default():
    async def body(pool, org):
        await set_org_policy(pool, org, {"blacklist_domains": ["evil.example"],
                                         "cost_limit_usd": 0.5})
        pol = await load_org_policy(pool, org)
        assert pol.check_url("https://evil.example/x").action == BLOCK
        assert pol.check_url("https://sub.evil.example").action == BLOCK      # subdomain
        assert pol.check_cost(0.9).action == APPROVAL
        assert pol.check_tool("terminal_execute").action == APPROVAL          # default tetap
    _run_db(body)


def test_set_org_policy_invalidates_cache():
    async def body(pool, org):
        pol1 = await load_org_policy(pool, org)
        assert pol1.check_url("https://evil.example").action != BLOCK
        await set_org_policy(pool, org, {"blacklist_domains": ["evil.example"]})
        pol2 = await load_org_policy(pool, org)
        assert pol2.check_url("https://evil.example").action == BLOCK         # cache dibuang
    _run_db(body)


# ── gate execute_tool ─────────────────────────────────────────────────────────
def test_gate_off_by_default_no_effect():
    async def body(pool, org):
        await set_org_policy(pool, org, {"blacklist_domains": ["evil.example"]})
        # flag OFF → gate tak aktif → _policy_gate mengembalikan None (lolos)
        res = await tool_executor._policy_gate("web_read", {"url": "https://evil.example"},
                                               {"org_id": org, "pool": pool})
        assert res is None
    _run_db(body)


def test_gate_blocks_blacklisted_url_when_on():
    async def body(pool, org):
        await set_org_policy(pool, org, {"blacklist_domains": ["evil.example"]})
        ff.set_override("policy_engine", True)
        res = await tool_executor._policy_gate("web_read", {"url": "https://evil.example/x"},
                                               {"org_id": org, "pool": pool})
        assert res is not None and res.get("blocked") is True
        # domain aman → lolos
        ok = await tool_executor._policy_gate("web_read", {"url": "https://good.example"},
                                              {"org_id": org, "pool": pool})
        assert ok is None
    _run_db(body)


def test_gate_requires_approval_for_dangerous_tool():
    async def body(pool, org):
        ff.set_override("policy_engine", True)
        res = await tool_executor._policy_gate("terminal_execute", {"command": "ls"},
                                               {"org_id": org, "pool": pool})
        assert res is not None and res.get("requires_approval") is True
        # dengan approval → lolos gate
        ok = await tool_executor._policy_gate("terminal_execute",
                                              {"command": "ls", "approval_granted": True},
                                              {"org_id": org, "pool": pool})
        assert ok is None
    _run_db(body)


def test_gate_full_execute_tool_blocks_before_dispatch():
    async def body(pool, org):
        await set_org_policy(pool, org, {"blacklist_domains": ["evil.example"]})
        ff.set_override("policy_engine", True)
        # web_read ke domain blacklist → di-block SEBELUM agent_read dipanggil
        res = await tool_executor.execute_tool("web_read", {"url": "https://evil.example"},
                                               ctx={"org_id": org, "pool": pool})
        assert res.get("blocked") is True
    _run_db(body)


def test_gate_fail_open_on_no_org():
    async def run():
        # tanpa org_id → gate None (tak mengganggu jalur non-tenant)
        res = await tool_executor._policy_gate("terminal_execute", {}, {"pool": None})
        assert res is None
    asyncio.run(run())
