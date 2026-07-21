"""Tests untuk cognitive_loop (P1-A) — LLM di-stub (deterministik, tanpa API)."""
import asyncio

from cognitive_loop import CognitiveLoop, ACCEPT, REVISE, REPLAN, make_tool_worker


def _run(coro):
    return asyncio.run(coro)


class StubAgent:
    """Fake agent: _call_llm_json memilih respons berdasar peran di prompt.
    `responses[role]` = callable(call_index) -> dict."""
    def __init__(self, responses):
        self.responses = responses
        self.calls = {"plan": 0, "work": 0, "critique": 0}

    async def _call_llm_json(self, messages, **kwargs):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "kamu critic" in blob:
            self.calls["critique"] += 1
            return self.responses["critique"](self.calls["critique"])
        if "kamu worker" in blob:
            self.calls["work"] += 1
            return self.responses["work"](self.calls["work"])
        self.calls["plan"] += 1
        return self.responses["plan"](self.calls["plan"])


def _plan_ok(_):
    return {"strategy": "s", "steps": ["a", "b"]}


def _work_ok(i):
    return {"answer": f"jawaban-{i}"}


def test_accept_on_first_critique():
    agent = StubAgent({
        "plan": _plan_ok, "work": _work_ok,
        "critique": lambda _: {"score": 0.95, "accept": True, "action": ACCEPT, "issues": []},
    })
    out = _run(CognitiveLoop(max_iters=3).run(agent, "goal"))
    assert out["accepted"] is True and out["stop_reason"] == "accepted"
    assert out["iterations"] == 1
    assert agent.calls == {"plan": 1, "work": 1, "critique": 1}     # tanpa rework


def test_revise_then_accept():
    crit = [
        {"score": 0.4, "accept": False, "action": REVISE, "issues": ["kurang detail"]},
        {"score": 0.9, "accept": True, "action": ACCEPT, "issues": []},
    ]
    agent = StubAgent({"plan": _plan_ok, "work": _work_ok, "critique": lambda i: crit[i - 1]})
    out = _run(CognitiveLoop(max_iters=3).run(agent, "goal"))
    assert out["accepted"] is True and out["iterations"] == 2
    assert agent.calls["work"] == 2 and agent.calls["plan"] == 1     # revise = Worker ulang, plan tetap


def test_replan_then_accept():
    crit = [
        {"score": 0.3, "accept": False, "action": REPLAN, "issues": ["strategi salah"]},
        {"score": 0.85, "accept": True, "action": ACCEPT, "issues": []},
    ]
    agent = StubAgent({"plan": _plan_ok, "work": _work_ok, "critique": lambda i: crit[i - 1]})
    out = _run(CognitiveLoop(max_iters=3).run(agent, "goal"))
    assert out["accepted"] is True
    assert agent.calls["plan"] == 2 and agent.calls["work"] == 2     # replan = Planner rencana baru


def test_max_iters_exhausted_best_effort():
    agent = StubAgent({
        "plan": _plan_ok, "work": _work_ok,
        "critique": lambda _: {"score": 0.5, "accept": False, "action": REVISE, "issues": ["belum cukup"]},
    })
    out = _run(CognitiveLoop(max_iters=3).run(agent, "goal"))
    assert out["accepted"] is False and out["stop_reason"] == "max_iters"
    assert out["iterations"] == 3 and out["final_score"] == 0.5


def test_threshold_accept_without_explicit_accept_flag():
    agent = StubAgent({
        "plan": _plan_ok, "work": _work_ok,
        "critique": lambda _: {"score": 0.82, "accept": False, "action": REVISE, "issues": []},
    })
    out = _run(CognitiveLoop(max_iters=3, accept_threshold=0.8).run(agent, "goal"))
    assert out["accepted"] is True and out["stop_reason"] == "accepted"   # score≥threshold


def test_degraded_when_llm_unavailable():
    down = {"_llm_unavailable": True}
    agent = StubAgent({"plan": lambda _: down, "work": lambda _: down, "critique": lambda _: down})
    out = _run(CognitiveLoop(max_iters=3).run(agent, "goal"))
    assert out["_degraded"] is True and out["stop_reason"] == "degraded"
    assert out["iterations"] == 1                                    # tak loop saat LLM down


def test_custom_worker_fn_used():
    seen = {}

    async def worker_fn(*, goal, plan, context, feedback, prior):
        seen["called"] = True
        return {"answer": "hasil tool-loop"}

    agent = StubAgent({
        "plan": _plan_ok, "work": _work_ok,
        "critique": lambda _: {"score": 0.95, "accept": True, "action": ACCEPT, "issues": []},
    })
    out = _run(CognitiveLoop().run(agent, "goal", worker_fn=worker_fn))
    assert seen.get("called") and out["answer"] == "hasil tool-loop"
    assert agent.calls["work"] == 0                                 # Worker LLM default tak dipakai


# ── P1-A.2: tool-worker + BaseAgent.reason ──────────────────────────────────
def test_make_tool_worker_uses_tool_loop():
    class A:
        name = "a"
        async def _call_llm_with_tools(self, messages, *, tools, tool_ctx):
            return {"final_answer": "hasil", "tool_calls": [{"tool": "t"}]}
    wf = make_tool_worker(A(), tool_ctx={}, tools=[])
    res = _run(wf(goal="g", plan={"strategy": "s", "steps": ["x"]}, context={}, feedback=None, prior=None))
    assert res["answer"] == "hasil" and res["_deg"] is False


def test_make_tool_worker_failopen():
    class A:
        name = "a"
        async def _call_llm_with_tools(self, messages, *, tools, tool_ctx):
            raise RuntimeError("boom")
    wf = make_tool_worker(A(), tool_ctx={}, tools=[])
    res = _run(wf(goal="g", plan={}, context={}))
    assert res["_deg"] is True and res["answer"] == ""


def test_base_agent_reason_llm_only():
    from base import BaseAgent
    agent = BaseAgent()

    async def stub(messages, **kw):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "kamu critic" in blob:
            return {"score": 0.9, "accept": True, "action": ACCEPT, "issues": []}
        if "kamu worker" in blob:
            return {"answer": "jawaban final"}
        return {"strategy": "s", "steps": ["a"]}
    agent._call_llm_json = stub
    out = _run(agent.reason("goal"))
    assert out["accepted"] is True and out["answer"] == "jawaban final"


def test_base_agent_reason_with_tools_routes_worker_through_tool_loop():
    from base import BaseAgent
    agent = BaseAgent()
    agent.tools = ["web_read"]

    async def json_stub(messages, **kw):
        blob = " ".join(str(m.get("content", "")) for m in messages).lower()
        if "kamu critic" in blob:
            return {"score": 0.95, "accept": True, "action": ACCEPT, "issues": []}
        return {"strategy": "s", "steps": ["a"]}          # Planner

    async def tool_stub(messages, *, tools, tool_ctx):
        return {"final_answer": "jawaban-tool", "tool_calls": []}

    agent._call_llm_json = json_stub
    agent._call_llm_with_tools = tool_stub
    out = _run(agent.reason("goal", use_tools=True))
    assert out["accepted"] is True and out["answer"] == "jawaban-tool"
