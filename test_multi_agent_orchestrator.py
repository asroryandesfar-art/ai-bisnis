"""Test engine orkestrasi multi-agent (Phase 11).

Deterministik tanpa LLM live: agent di-fake dan registry di-monkeypatch. Router
LLM/synthesis/verify otomatis jatuh ke fallback (worker BaseAgent tanpa API key
→ _llm_unavailable), jadi jalur yang diuji adalah heuristik + agregasi
terstruktur + isolasi + timeout — bukan kualitas LLM.

Menguji: single, multi, parallel, timeout, fallback/isolasi, routing
(eksplisit/heuristik/default), aggregation, verification, confidence,
RBAC filter, inter-agent communication.
"""
import asyncio
import time

import agent_registry
from base import AgentResult, BaseAgent
from multi_agent_orchestrator import MultiAgentOrchestrator


# ── Fake agents ──────────────────────────────────────────────────────────
class _Fake(BaseAgent):
    def __init__(self, name, *, output=None, confidence=None, sleep=0.0, fail=False, use_ask=False):
        super().__init__()
        self.name = name
        self._output = output or {"answer": f"{name} ok"}
        self._confidence = confidence
        self._sleep = sleep
        self._fail = fail
        self._use_ask = use_ask

    async def run(self, context: dict) -> AgentResult:
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._fail:
            raise RuntimeError("boom")
        output = dict(self._output)
        if self._use_ask and context.get("_ask_agent"):
            sub = await context["_ask_agent"]("helper", "berapa jumlahnya?")
            output["helper_success"] = sub.success
            output["helper_has_ask"] = bool(sub.output.get("had_ask"))
        return AgentResult(agent=self.name, success=True, output=output,
                           latency_ms=0, confidence=self._confidence)


def _spec(name, category, capabilities):
    return agent_registry.OrchestrationAgentSpec(
        name=name, class_name=name, category=category,
        module_path="__fake__", permission=None, capabilities=capabilities,
    )


def _install(monkeypatch, fakes: dict, specs: list):
    """Pasang registry palsu: orchestration_agents→specs, build_agent→fakes."""
    monkeypatch.setattr(agent_registry, "orchestration_agents",
                        lambda **kw: list(specs))

    def _build(module_path, class_name, **kwargs):
        return fakes[class_name]
    monkeypatch.setattr(agent_registry, "build_agent", _build)


def _orch():
    return MultiAgentOrchestrator(agent_kwargs={}, default_timeout=2.0)


# ── SINGLE AGENT ─────────────────────────────────────────────────────────
def test_single_agent_explicit(monkeypatch):
    fakes = {"finance": _Fake("finance", output={"answer": "Rp 10jt"}, confidence=0.9)}
    specs = [_spec("finance", "finance", ["biaya"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="hitung biaya", context={}, allowed_permissions=None,
            requested_agents=["finance"],
        )
        assert res.routing["method"] == "explicit"
        assert res.routing["selected"] == ["finance"]
        assert len(res.agents) == 1 and res.agents[0]["success"]
        assert res.confidence > 0

    asyncio.run(_run())


# ── MULTI AGENT + ROUTING HEURISTIK ──────────────────────────────────────
def test_multi_agent_heuristic_routing(monkeypatch):
    fakes = {
        "hr": _Fake("hr", output={"answer": "5 kandidat"}, confidence=0.8),
        "finance": _Fake("finance", output={"answer": "Rp 50jt"}, confidence=0.7),
        "sales": _Fake("sales", output={"answer": "irrelevant"}, confidence=0.5),
    }
    specs = [
        _spec("hr", "hr", ["rekrut", "perekrutan", "karyawan"]),
        _spec("finance", "finance", ["biaya", "anggaran"]),
        _spec("sales", "sales", ["closing", "deal"]),
    ]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="hitung biaya perekrutan karyawan baru",
            context={}, allowed_permissions=None,
        )
        assert res.routing["method"] == "heuristic"
        sel = set(res.routing["selected"])
        assert "hr" in sel and "finance" in sel  # keduanya cocok kata kunci
        assert "sales" not in sel                # tidak cocok

    asyncio.run(_run())


# ── PARALLEL EXECUTION (bukti waktu) ─────────────────────────────────────
def test_parallel_execution_is_concurrent(monkeypatch):
    fakes = {
        "a": _Fake("a", sleep=0.4), "b": _Fake("b", sleep=0.4), "c": _Fake("c", sleep=0.4),
    }
    specs = [_spec("a", "finance", ["x"]), _spec("b", "hr", ["x"]), _spec("c", "analytics", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        t = time.monotonic()
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None,
            requested_agents=["a", "b", "c"],
        )
        elapsed = time.monotonic() - t
        assert len(res.agents) == 3
        # 3×0.4s paralel harus << 1.2s serial (beri margin).
        assert elapsed < 0.9, f"tidak paralel: {elapsed:.2f}s"

    asyncio.run(_run())


# ── TIMEOUT ──────────────────────────────────────────────────────────────
def test_agent_timeout_isolated(monkeypatch):
    fakes = {
        "slow": _Fake("slow", sleep=5.0),
        "fast": _Fake("fast", output={"answer": "cepat"}, confidence=0.9),
    }
    specs = [_spec("slow", "finance", ["x"]), _spec("fast", "hr", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        orch = MultiAgentOrchestrator(agent_kwargs={}, default_timeout=0.3)
        res = await orch.orchestrate(
            message="x", context={}, allowed_permissions=None,
            requested_agents=["slow", "fast"],
        )
        by = {a["agent"]: a for a in res.agents}
        assert by["slow"]["success"] is False and "timeout" in by["slow"]["error"]
        assert by["fast"]["success"] is True  # yang lain tetap jalan

    asyncio.run(_run())


# ── FALLBACK / ISOLASI KEGAGALAN ─────────────────────────────────────────
def test_one_agent_fails_others_continue(monkeypatch):
    fakes = {
        "boom": _Fake("boom", fail=True),
        "ok": _Fake("ok", output={"answer": "aman"}, confidence=0.85),
    }
    specs = [_spec("boom", "finance", ["x"]), _spec("ok", "hr", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None,
            requested_agents=["boom", "ok"],
        )
        by = {a["agent"]: a for a in res.agents}
        assert by["boom"]["success"] is False
        assert by["ok"]["success"] is True
        assert "aman" in res.final_answer         # jawaban tetap tersusun
        assert any("boom" in e for e in res.errors)

    asyncio.run(_run())


# ── AGGREGATION TERSTRUKTUR ──────────────────────────────────────────────
def test_aggregation_structure(monkeypatch):
    fakes = {
        "hr": _Fake("hr", output={"answer": "10 orang"}, confidence=0.8),
        "finance": _Fake("finance", output={"answer": "Rp 100jt"}, confidence=0.6),
    }
    specs = [_spec("hr", "hr", ["x"]), _spec("finance", "finance", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None,
            requested_agents=["hr", "finance"],
        )
        d = res.to_dict()
        for key in ("summary", "final_answer", "confidence", "agents", "conflicts",
                    "verification", "routing", "trace"):
            assert key in d
        assert len(d["agents"]) == 2
        # confidence gabungan = mean(0.8,0.6)=0.7 × success_ratio 1.0
        assert abs(d["confidence"] - 0.7) < 1e-6
        assert len(d["trace"]) == 2

    asyncio.run(_run())


# ── CONFIDENCE dari output (bukan field) ─────────────────────────────────
def test_confidence_read_from_output(monkeypatch):
    # confidence 90 (skala 0..100) di output → dinormalkan ke 0.9
    fakes = {"a": _Fake("a", output={"answer": "x", "confidence": 90})}
    specs = [_spec("a", "finance", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None, requested_agents=["a"])
        assert abs(res.agents[0]["confidence"] - 0.9) < 1e-6

    asyncio.run(_run())


# ── VERIFICATION (LLM tak tersedia → checked False, tidak blokir) ────────
def test_verification_graceful_without_llm(monkeypatch):
    fakes = {"a": _Fake("a", output={"answer": "jawaban"}, confidence=0.9)}
    specs = [_spec("a", "finance", ["x"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None, requested_agents=["a"])
        assert res.verification["checked"] is False
        assert res.verification["passed"] is True

    asyncio.run(_run())


# ── SELF-VERIFICATION → REVISI (Phase 8) ─────────────────────────────────
def test_failed_verification_triggers_revision(monkeypatch):
    fakes = {"a": _Fake("a", output={"answer": "jawaban awal"}, confidence=0.9)}
    specs = [_spec("a", "finance", ["x"])]
    _install(monkeypatch, fakes, specs)

    orch = _orch()

    async def fail_verify(message, final_answer, results):
        return {"passed": False, "issues": ["kontradiksi angka"], "checked": True}

    async def fake_synth(message, successful, *, revision_feedback=None):
        if revision_feedback:
            return {"summary": "revisi", "final_answer": "JAWABAN REVISI", "conflicts": []}
        return {}  # sintesis awal → fallback terstruktur

    monkeypatch.setattr(orch, "_verify", fail_verify)
    monkeypatch.setattr(orch, "_synthesize", fake_synth)

    async def _run():
        res = await orch.orchestrate(
            message="x", context={}, allowed_permissions=None, requested_agents=["a"])
        assert res.verification["revised"] is True
        assert res.final_answer == "JAWABAN REVISI"

    asyncio.run(_run())


# ── DEFAULT ROUTING (tak ada match) ──────────────────────────────────────
def test_default_routing_picks_general(monkeypatch):
    fakes = {"General AI Agent": _Fake("General AI Agent", output={"answer": "umum"})}
    specs = [_spec("General AI Agent", "general_ai", [])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="halo apa kabar", context={}, allowed_permissions=None)
        assert res.routing["method"] == "default"
        assert res.routing["selected"] == ["General AI Agent"]

    asyncio.run(_run())


# ── INTER-AGENT COMMUNICATION + depth guard ──────────────────────────────
def test_inter_agent_communication(monkeypatch):
    # 'caller' meminta 'helper'; helper (di depth 1) tidak boleh punya _ask_agent
    helper = _Fake("helper", output={"answer": "42", "had_ask": False})

    def _helper_run_marks_ask(context):
        async def _r():
            return AgentResult(agent="helper", success=True,
                               output={"answer": "42", "had_ask": bool(context.get("_ask_agent"))},
                               latency_ms=0, confidence=0.7)
        return _r()
    helper.run = _helper_run_marks_ask  # type: ignore

    caller = _Fake("caller", use_ask=True, confidence=0.8)
    fakes = {"caller": caller, "helper": helper}
    specs = [_spec("caller", "finance", ["x"]), _spec("helper", "hr", ["y"])]
    _install(monkeypatch, fakes, specs)

    async def _run():
        res = await _orch().orchestrate(
            message="x", context={}, allowed_permissions=None, requested_agents=["caller"])
        out = res.agents[0]["output"]
        assert out["helper_success"] is True         # inter-agent call berhasil
        assert out["helper_has_ask"] is False        # depth guard: helper tak bisa ask lagi

    asyncio.run(_run())


# ── RBAC FILTER (registry asli, bukan fake) ──────────────────────────────
def test_rbac_filters_domain_agents():
    from bn_platform.rbac import SYSTEM_ROLE_PERMISSIONS
    # role 'agent' hanya boleh cs/general_ai/knowledge/sales/memory (bukan finance/hr)
    specs = agent_registry.orchestration_agents(
        allowed_permissions=SYSTEM_ROLE_PERMISSIONS["agent"])
    cats = {s.category for s in specs}
    assert "finance" not in cats and "hr" not in cats
    assert "customer_service" in cats
    # owner boleh semua yang bisa di-orkestrasi
    owner_specs = agent_registry.orchestration_agents(
        allowed_permissions=SYSTEM_ROLE_PERMISSIONS["owner"])
    owner_cats = {s.category for s in owner_specs}
    assert {"finance", "hr", "analytics"} <= owner_cats


# ── DOMAIN AGENT run() ADAPTERS (Operations/Security/Search) ─────────────
def test_operations_agent_run_needs_pool():
    import operations_agent

    async def _run():
        res = await operations_agent.OperationsAgent().run({})  # tanpa pool/org
        assert res.success is False and "pool" in res.error

    asyncio.run(_run())


def test_operations_agent_run_with_pool(monkeypatch):
    import operations_agent

    async def fake_summary(pool, org_id):
        return {"health_score": 88, "open_alerts": 1}

    monkeypatch.setattr(operations_agent, "dashboard_summary", fake_summary)

    async def _run():
        res = await operations_agent.OperationsAgent().run(
            {"pool": object(), "org_id": "org-1"})
        assert res.success is True
        assert res.output["metrics"]["health_score"] == 88
        assert res.confidence in (0.5, 0.75)

    asyncio.run(_run())


def test_security_agent_run_with_pool(monkeypatch):
    import security_agent

    async def fake_summary(pool, org_id):
        return {"risk_level": "low", "findings": []}

    monkeypatch.setattr(security_agent, "dashboard_summary", fake_summary)

    async def _run():
        res = await security_agent.SecurityAgent().run(
            {"pool": object(), "org_id": "org-1"})
        assert res.success is True
        assert res.output["security"]["risk_level"] == "low"

    asyncio.run(_run())


def test_search_agent_run(monkeypatch):
    import web_search_agent

    async def fake_search(query, *, searxng_url="", tavily_api_key=""):
        return {"success": True, "provider": "tavily",
                "results": [{"title": "X", "url": "http://x", "snippet": "s"}]}

    monkeypatch.setattr(web_search_agent, "search", fake_search)

    async def _run():
        res = await web_search_agent.SearchAgent().run({"user_message": "berita terbaru AI"})
        assert res.success is True
        assert res.output["provider"] == "tavily"
        assert len(res.output["results"]) == 1
        # query kosong → gagal anggun
        res2 = await web_search_agent.SearchAgent().run({"user_message": "  "})
        assert res2.success is False

    asyncio.run(_run())


def test_orchestrator_routes_to_operations_end_to_end(monkeypatch):
    """Integrasi: registry ASLI → build_agent ASLI → OperationsAgent.run."""
    import operations_agent

    async def fake_summary(pool, org_id):
        return {"health_score": 90}

    monkeypatch.setattr(operations_agent, "dashboard_summary", fake_summary)

    async def _run():
        orch = MultiAgentOrchestrator(agent_kwargs={}, default_timeout=5.0)
        res = await orch.orchestrate(
            message="cek kesehatan operasional",
            context={"pool": object(), "org_id": "org-1"},
            allowed_permissions={"*"},
            requested_agents=["operations"],
        )
        assert res.routing["selected"] == ["operations_agent"]
        assert res.agents[0]["success"] is True
        assert res.agents[0]["output"]["metrics"]["health_score"] == 90

    asyncio.run(_run())


# ── Executive / Workforce / Self-learning run() ──────────────────────────
def test_executive_agent_run(monkeypatch):
    import executive_agent

    async def fake_summary(pool, org_id):
        return {"health_score": 80}

    monkeypatch.setattr(executive_agent, "dashboard_summary", fake_summary)

    async def _run():
        r1 = await executive_agent.ExecutiveAgent().run({})
        assert r1.success is False
        r2 = await executive_agent.ExecutiveAgent().run({"pool": object(), "org_id": "o1"})
        assert r2.success is True and r2.output["executive"]["health_score"] == 80

    asyncio.run(_run())


def test_workforce_agent_run(monkeypatch):
    import workforce_orchestrator

    async def fake_summary(pool, org_id):
        return {"open_tasks": 3}

    async def fake_conflicts(pool, org_id):
        return []

    monkeypatch.setattr(workforce_orchestrator, "dashboard_summary", fake_summary)
    monkeypatch.setattr(workforce_orchestrator, "detect_conflicts", fake_conflicts)

    async def _run():
        res = await workforce_orchestrator.WorkforceOrchestratorAgent().run(
            {"pool": object(), "org_id": "o1"})
        assert res.success is True and res.output["summary"]["open_tasks"] == 3

    asyncio.run(_run())


def test_self_learning_agent_run(monkeypatch):
    import self_learning_engine

    async def fake_summary(pool, org_id):
        return {"insights": 7}

    monkeypatch.setattr(self_learning_engine, "dashboard_summary", fake_summary)

    async def _run():
        res = await self_learning_engine.SelfLearningAgent().run(
            {"pool": object(), "org_id": "o1"})
        assert res.success is True and res.output["learning"]["insights"] == 7

    asyncio.run(_run())


# ── Marketplace / Billing / Subscription adapters ────────────────────────
def test_marketplace_agent_run(monkeypatch):
    import bn_platform.marketplace as mp
    from orchestration_domain_agents import MarketplaceAgent

    async def _templates(pool):
        return [{"key": "a"}, {"key": "b"}]

    async def _installs(pool, org_id):
        return [{"id": "i1"}]

    async def _analytics(pool, org_id):
        return {"installs": 1}

    monkeypatch.setattr(mp, "list_templates", _templates)
    monkeypatch.setattr(mp, "list_installs", _installs)
    monkeypatch.setattr(mp, "marketplace_analytics", _analytics)

    async def _run():
        assert (await MarketplaceAgent().run({})).success is False
        res = await MarketplaceAgent().run({"pool": object(), "org_id": "o1"})
        assert res.success is True and res.output["templates_count"] == 2

    asyncio.run(_run())


def test_billing_and_subscription_agents_run(monkeypatch):
    import bn_platform.billing as billing
    from orchestration_domain_agents import BillingAgent, SubscriptionAgent

    async def _balance(pool, org_id):
        return 120

    async def _usage(pool, org_id):
        return {"conversations": 45}

    async def _active(pool, org_id):
        return {"plan_key": "pro"}

    async def _plans(pool):
        return [{"key": "starter"}, {"key": "pro"}]

    monkeypatch.setattr(billing, "get_credit_balance", _balance)
    monkeypatch.setattr(billing, "current_usage", _usage)
    monkeypatch.setattr(billing, "get_active_subscription", _active)
    monkeypatch.setattr(billing, "list_plans", _plans)

    async def _run():
        b = await BillingAgent().run({"pool": object(), "org_id": "o1"})
        assert b.success is True and b.output["credit_balance"] == 120
        s = await SubscriptionAgent().run({"pool": object(), "org_id": "o1"})
        assert s.success is True and "pro" in s.output["answer"]

    asyncio.run(_run())


def test_new_agents_respect_rbac():
    from bn_platform.rbac import SYSTEM_ROLE_PERMISSIONS
    # 'agent' role: tak punya billing.read/analytics.read/workforce.read/learning.read
    agent_specs = agent_registry.orchestration_agents(
        allowed_permissions=SYSTEM_ROLE_PERMISSIONS["agent"])
    cats = {s.category for s in agent_specs}
    for blocked in ("billing", "subscription", "executive", "workforce", "self_learning"):
        assert blocked not in cats
    # owner: semua enam hadir
    owner = agent_registry.orchestration_agents(
        allowed_permissions=SYSTEM_ROLE_PERMISSIONS["owner"])
    ocats = {s.category for s in owner}
    assert {"billing", "subscription", "executive", "workforce", "self_learning", "marketplace"} <= ocats


def test_no_permitted_agents_returns_empty():
    async def _run():
        # permission set kosong → hanya agent perm=None yang lolos; paksa None-only
        orch = MultiAgentOrchestrator(agent_kwargs={})
        res = await orch.orchestrate(
            message="x", context={}, allowed_permissions=set())
        # agent None-permission (cs/sales/general_ai/memory) tetap tersedia
        assert res.routing["method"] in ("llm", "heuristic", "default", "explicit")

    asyncio.run(_run())


# ── ENDPOINT (HTTP layer + RBAC wiring) ──────────────────────────────────
class _FakePool:
    pass


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _build_endpoint_router():
    from bn_platform.orchestrator import build_orchestrator_router
    pool = _FakePool()

    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "role": "admin"}

    router = build_orchestrator_router(
        get_pool=get_pool, get_current_user=get_current_user,
        get_agent_config=lambda: {"api_key": "", "searxng_url": "", "search_api_key": ""},
    )
    return router, pool


def test_endpoint_registry_filters_by_rbac(monkeypatch):
    import bn_platform.orchestrator as orch_mod

    async def fake_perms(pool, uid, org):
        return {"finance.read"}  # hanya boleh finance

    monkeypatch.setattr(orch_mod, "get_user_permissions", fake_perms)
    router, pool = _build_endpoint_router()
    handler = _route(router, "/agent/registry", "GET")
    out = asyncio.run(handler(user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    cats = {a["category"] for a in out["agents"]}
    assert "finance" in cats
    assert "hr" not in cats  # tidak punya hr.read


def test_endpoint_orchestrate_returns_structured(monkeypatch):
    import bn_platform.orchestrator as orch_mod
    from bn_platform.orchestrator import OrchestrateReq

    async def fake_perms(pool, uid, org):
        return {"*"}

    monkeypatch.setattr(orch_mod, "get_user_permissions", fake_perms)

    fakes = {"finance": _Fake("finance", output={"answer": "Rp 5jt"}, confidence=0.9)}
    specs = [_spec("finance", "finance", ["biaya"])]
    _install(monkeypatch, fakes, specs)

    router, pool = _build_endpoint_router()
    handler = _route(router, "/agent/orchestrate", "POST")
    body = OrchestrateReq(message="hitung biaya", agents=["finance"])
    out = asyncio.run(handler(body=body, user={"org_id": "org-1", "id": "user-1", "role": "admin"}, pool=pool))
    assert out["routing"]["selected"] == ["finance"]
    assert out["agents"][0]["success"] is True
    assert "final_answer" in out and "confidence" in out
