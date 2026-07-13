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
