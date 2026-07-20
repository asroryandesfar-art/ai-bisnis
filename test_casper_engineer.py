"""Casper Engineer — agen software-engineer otonom (plan/analyze/verify/critique).

Uji pipeline deterministik dengan LLM di-stub (tanpa API). Casper Blockchain
tidak diimpor di sini — modul terpisah, tidak boleh saling mengubah."""
import asyncio

from casper_engineer import (
    CasperEngineerAgent, CRITIQUE_CATEGORIES, SCORE_DIMENSIONS,
    SCORE_PASS_THRESHOLD, _audit_evidence,
)


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
        if "penilai mandiri" in blob:
            return responses["score"]
        if "analisis repository" in blob:
            return responses["analyze"]
        return responses["plan"]
    return fake


def _good_responses():
    return {
        "plan": {"understanding": "Tambah fitur X", "subtasks": [{"id": 1, "title": "a"}],
                 "execution_order": [1], "risks": [{"risk": "r", "severity": "high", "mitigation": "m"}]},
        "analyze": {"structure": "src/", "architecture": "modular-monolith", "dependencies": ["fastapi"],
                    "conventions": ["snake_case"], "existing_patterns": ["factory router"],
                    "integration_points": ["main.py"], "constraints": [],
                    "evidence_log": [{"claim": "FastAPI app", "evidence": "src/main.py", "type": "fact"}]},
        "verify": {"complete": True, "gaps": [], "reasoning": "cukup"},
        "critique": {"issues": [{"category": "security", "severity": "high", "detail": "d", "fix": "f"}],
                     "improved_plan": {"summary": "s", "steps": ["1"]}, "overall_confidence": 0.82},
        "score": {"scores": {d: 9 for d in SCORE_DIMENSIONS}, "justification": "solid, berbukti"},
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


def _decisions_stub(decisions):
    it = iter(decisions)

    async def fake(messages, **kwargs):
        try:
            return next(it)
        except StopIteration:
            return {"done": True}
    return fake


def _exec_recorder(calls, result=None):
    async def execute(org_id, tool, args, *, device_id=None, initiated_by="", timeout=30, pool=None):
        calls.append({"tool": tool, "args": args, "initiated_by": initiated_by})
        return result if result is not None else {"success": True, "content": "file body"}
    return execute


def test_investigate_readonly_loop_builds_findings():
    agent = _agent()
    agent._call_llm_json = _decisions_stub([
        {"done": False, "tool": "scan_project", "args": {"path": "."}, "reason": "overview"},
        {"done": False, "tool": "read_file", "args": {"path": "main.py"}, "reason": "entry"},
        {"done": True, "summary": "FastAPI app, entry main.py"},
    ])
    calls = []
    out = asyncio.run(agent.investigate("goal", _exec_recorder(calls), "org-1", None, max_rounds=5))
    assert [c["tool"] for c in calls] == ["scan_project", "read_file"]
    assert out["rounds"] == 2
    assert "scan_project" in out["findings"] and "RINGKASAN" in out["findings"]
    assert all(c["initiated_by"] == "casper_engineer_investigate" for c in calls)


def test_investigate_skips_write_tools():
    agent = _agent()
    agent._call_llm_json = _decisions_stub([
        {"done": False, "tool": "run_command", "args": {"command": "rm -rf /"}},   # HARUS dilewati
        {"done": False, "tool": "write_file", "args": {"path": "x", "content": "y"}},  # dilewati
        {"done": True, "summary": "selesai"},
    ])
    calls = []
    out = asyncio.run(agent.investigate("g", _exec_recorder(calls), "org-1", None))
    assert calls == []                                   # tak ada tool tulis yang dieksekusi
    assert any(x.get("skipped") == "not-readonly" for x in out["trace"])


def test_investigate_stops_on_device_error():
    agent = _agent()
    agent._call_llm_json = _decisions_stub([
        {"done": False, "tool": "read_file", "args": {"path": "a"}},
        {"done": False, "tool": "read_file", "args": {"path": "b"}},
    ])

    async def boom(*a, **k):
        raise RuntimeError("device gone")
    out = asyncio.run(agent.investigate("g", boom, "org-1", None))
    assert out["rounds"] == 1                             # berhenti setelah error pertama
    assert any("error" in x for x in out["trace"])


def test_investigate_bounded_by_max_rounds():
    agent = _agent()
    # Selalu minta baca (tak pernah 'done') -> harus berhenti di max_rounds.
    agent._call_llm_json = _decisions_stub([{"done": False, "tool": "list_dir", "args": {"path": "."}}] * 20)
    calls = []
    out = asyncio.run(agent.investigate("g", _exec_recorder(calls), "org-1", None, max_rounds=3))
    assert len(calls) == 3


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


def test_self_score_present_and_no_retrain_when_all_pass():
    agent = _agent()
    agent._call_llm_json = _route_stub(_good_responses())
    res = asyncio.run(agent.run({"goal": "Tambah fitur X", "repo_context": "src/main.py FastAPI"}))
    sc = res.output["self_score"]
    assert set(sc["scores"]) == set(SCORE_DIMENSIONS)          # 7 dimensi
    assert sc["overall"] == 9.0
    assert sc["weakest_dimensions"] == []
    assert sc["retrain_needed"] is False
    assert res.output["retrain_needed"] is False


def test_retrain_flagged_when_dimension_below_threshold():
    agent = _agent()
    r = _good_responses()
    r["score"] = {"scores": {d: 9 for d in SCORE_DIMENSIONS} | {"security": 6, "accuracy": 8},
                  "justification": "security lemah"}
    agent._call_llm_json = _route_stub(r)
    res = asyncio.run(agent.run({"goal": "g", "repo_context": "ctx"}))
    sc = res.output["self_score"]
    assert sc["retrain_needed"] is True
    assert sc["weakest_dimensions"] == ["security", "accuracy"]   # terlemah dulu
    assert sc["overall"] < SCORE_PASS_THRESHOLD


def test_finalize_score_clamps_and_ignores_bad_values():
    out = CasperEngineerAgent._finalize_score(
        {"scores": {"accuracy": 12, "reasoning": -3, "security": "oops"}, "justification": "x"}
    )
    assert out["scores"]["accuracy"] == 10.0     # clamp atas
    assert out["scores"]["reasoning"] == 0.0     # clamp bawah
    assert "security" not in out["scores"]        # nilai non-numerik dibuang


def test_audit_evidence_separates_fact_from_assumption():
    analysis = {"evidence_log": [
        {"claim": "pakai FastAPI", "evidence": "main.py:1 import fastapi", "type": "fact"},
        {"claim": "mungkin ada cache", "evidence": "", "type": "assumption"},
        {"claim": "klaim tanpa tipe", "evidence": "somefile.py"},   # bukan 'fact' -> unverified
        {"claim": ""},                                              # kosong -> diabaikan
    ]}
    au = _audit_evidence(analysis)
    assert [v["claim"] for v in au["verified"]] == ["pakai FastAPI"]
    assert len(au["unverified"]) == 2
    assert au["integrity"] == round(1 / 3, 3)


def test_audit_evidence_none_when_no_log():
    assert _audit_evidence({"structure": "x"})["integrity"] is None


def test_repo_incomplete_status_halts_without_context():
    agent = _agent()
    agent._call_llm_json = _route_stub(_good_responses())
    res = asyncio.run(agent.run({"goal": "bikin sesuatu"}))       # tanpa repo_context
    assert res.output["status"] == "repo_incomplete"
    assert res.output["needs_repo_context"] is True
