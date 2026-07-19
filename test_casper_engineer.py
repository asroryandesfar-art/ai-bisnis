"""Casper Engineer — agen software-engineer otonom (plan/analyze/verify/critique).

Uji pipeline deterministik dengan LLM di-stub (tanpa API). Casper Blockchain
tidak diimpor di sini — modul terpisah, tidak boleh saling mengubah."""
import asyncio

from casper_engineer import CasperEngineerAgent, CRITIQUE_CATEGORIES


def _agent():
    return CasperEngineerAgent()


def _route_stub(responses):
    """Kembalikan fake _call_llm_json yang memilih respons berdasar isi prompt."""
    async def fake(messages, **kwargs):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "verifier internal" in blob:
            return responses["verify"]
        if "self-critic" in blob:
            return responses["critique"]
        if "analisis repository" in blob:
            return responses["analyze"]
        return responses["plan"]
    return fake


def _good_responses():
    return {
        "plan": {"understanding": "Tambah fitur X", "subtasks": [{"id": 1, "title": "a"}],
                 "execution_order": [1], "risks": [{"risk": "r", "severity": "high", "mitigation": "m"}]},
        "analyze": {"structure": "src/", "dependencies": ["fastapi"], "conventions": ["snake_case"],
                    "existing_patterns": ["factory router"], "integration_points": ["main.py"], "constraints": []},
        "verify": {"complete": True, "gaps": [], "reasoning": "cukup"},
        "critique": {"issues": [{"category": "security", "severity": "high", "detail": "d", "fix": "f"}],
                     "improved_plan": {"summary": "s", "steps": ["1"]}, "overall_confidence": 0.82},
    }


def test_run_produces_structured_artifact():
    agent = _agent()
    agent._call_llm_json = _route_stub(_good_responses())
    res = asyncio.run(agent.run({"goal": "Tambah fitur X", "repo_context": "src/main.py FastAPI"}))
    assert res.success is True
    out = res.output
    assert set(["goal", "planning", "repository_analysis", "self_verification",
                "self_critique", "confidence", "status"]).issubset(out)
    assert out["status"] == "verified"          # verification.complete == True
    assert out["confidence"] == 0.82
    assert out["self_critique"]["issues"][0]["category"] in CRITIQUE_CATEGORIES
    assert res.confidence == 0.82


def test_needs_review_when_not_complete():
    agent = _agent()
    r = _good_responses()
    r["verify"] = {"complete": False, "gaps": ["butuh test"], "reasoning": "kurang test"}
    agent._call_llm_json = _route_stub(r)
    res = asyncio.run(agent.run({"goal": "g", "repo_context": "ctx"}))
    assert res.output["status"] == "needs_review"


def test_empty_goal_fails_fast():
    agent = _agent()
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        return {}
    agent._call_llm_json = boom
    res = asyncio.run(agent.run({"goal": "   "}))
    assert res.success is False
    assert called["n"] == 0                      # tak boleh panggil LLM untuk goal kosong


def test_no_repo_context_flags_needs_context_and_skips_analysis_llm():
    agent = _agent()
    seen = {"analyze": False}

    async def fake(messages, **kwargs):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "analisis repository" in blob:
            seen["analyze"] = True                # seharusnya TIDAK terpanggil
        if "verifier internal" in blob:
            return {"complete": False, "gaps": [], "reasoning": ""}
        if "self-critic" in blob:
            return {"issues": [], "improved_plan": {}, "overall_confidence": 0.3}
        return {"understanding": "x", "subtasks": [], "execution_order": [], "risks": []}
    agent._call_llm_json = fake
    res = asyncio.run(agent.run({"goal": "bikin sesuatu"}))          # tanpa repo_context
    assert res.output["needs_repo_context"] is True
    assert seen["analyze"] is False


def test_propose_steps_filters_to_allowlist_and_flags_write_tools():
    agent = _agent()

    async def fake(messages, **kwargs):
        return {"steps": [
            {"tool": "read_file", "args": {"path": "a.py"}, "rationale": "baca"},
            {"tool": "run_command", "args": {"command": "pytest"}, "rationale": "test"},
            {"tool": "format_disk", "args": {}, "rationale": "jahat"},      # tak diizinkan -> dibuang
            {"tool": "write_file", "args": "bukan-dict"},                    # args invalid -> dibuang
        ]}
    agent._call_llm_json = fake
    out = asyncio.run(agent.propose_steps("goal", {"summary": "x"}, "repo"))
    tools = [s["tool"] for s in out["steps"]]
    assert tools == ["read_file", "run_command"]                           # jahat + invalid dibuang
    approvals = {s["tool"]: s["requires_approval"] for s in out["steps"]}
    assert approvals["run_command"] is True and approvals["read_file"] is False


def test_propose_steps_fail_open_empty():
    agent = _agent()

    async def down(messages, **kwargs):
        return {"_llm_unavailable": True}
    agent._call_llm_json = down
    out = asyncio.run(agent.propose_steps("g", {}, ""))
    assert out["steps"] == [] and out["_llm_unavailable"] is True


def test_degraded_when_all_stages_llm_unavailable():
    agent = _agent()

    async def down(messages, **kwargs):
        # _call_llm_json asli menandai _llm_unavailable saat API gagal; tiru itu.
        return {"_llm_unavailable": True}
    agent._call_llm_json = down
    res = asyncio.run(agent.run({"goal": "g", "repo_context": "ctx"}))
    assert res.success is False
    assert res.output["status"] == "degraded"
    assert res.confidence is None
