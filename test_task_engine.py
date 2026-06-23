"""test_task_engine.py — task_engine.run_agent_task(): Goal->Plan->Subtasks->
Tool Selection->Execution->Verification->Report, dengan urutan & persist
yang benar-benar diuji (mock di level BaseAgent method, pola sama dengan
test_devil_advocate_agent.py)."""
import asyncio

import task_engine
from base import AgentResult, BaseAgent


class FakePool:
    def __init__(self):
        self.inserted: dict | None = None

    async def fetchrow(self, sql, *args):
        (org_id, bot_id, agent_name, goal, plan, tool_calls, verification, report, status) = args
        self.inserted = {
            "org_id": org_id, "bot_id": bot_id, "agent_name": agent_name, "goal": goal,
            "plan": plan, "tool_calls": tool_calls, "verification": verification,
            "report": report, "status": status,
        }
        import datetime
        return {"id": "11111111-1111-1111-1111-111111111111", "created_at": datetime.datetime(2026, 6, 24)}


class _DummyAgent(BaseAgent):
    name = "test_agent"
    system_prompt = "Kamu adalah test agent."
    tools: list[str] = ["knowledge_search", "web_search"]


def test_run_agent_task_follows_plan_then_execute_then_verify_order(monkeypatch):
    calls = []

    async def fake_json(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        if "Pecah goal ini" in prompt:
            calls.append("plan")
            return {"subtasks": ["cari info A", "cari info B"], "relevant_tools": ["knowledge_search"]}
        if "verifier internal" in messages[0]["content"]:
            calls.append("verify")
            return {"verified": True, "reasoning": "Kedua subtask terjawab dengan tool nyata."}
        return kwargs.get("default", {})

    async def fake_with_tools(self, messages, tools, *, tool_ctx, **kwargs):
        calls.append("execute:" + messages[-1]["content"])
        return {
            "final_answer": f"jawaban untuk: {messages[-1]['content']}",
            "tool_calls": [{"name": "knowledge_search", "args": {"query": "x"}, "result": {"success": True}}],
            "rounds": 1,
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm_with_tools", fake_with_tools)

    agent = _DummyAgent(api_key="fake-key", model="test-model")
    pool = FakePool()
    result = asyncio.run(task_engine.run_agent_task(agent, "cari info perusahaan", pool=pool, org_id="org-1"))

    assert calls == ["plan", "execute:cari info A", "execute:cari info B", "verify"]
    assert result["status"] == "completed"
    assert len(result["tool_calls"]) == 2
    assert "cari info A" in result["report"] and "cari info B" in result["report"]
    assert result["id"] == "11111111-1111-1111-1111-111111111111"


def test_run_agent_task_marks_failed_when_verification_says_not_verified(monkeypatch):
    async def fake_json(self, messages, **kwargs):
        if "Pecah goal ini" in messages[-1]["content"]:
            return {"subtasks": ["goal saja"], "relevant_tools": []}
        return {"verified": False, "reasoning": "Tool web_search gagal/skipped, hasil tidak bisa dipercaya."}

    async def fake_with_tools(self, messages, tools, *, tool_ctx, **kwargs):
        return {"final_answer": "tidak ada data", "tool_calls": [{"name": "web_search", "args": {}, "result": {"success": False, "skipped": True}}], "rounds": 1}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm_with_tools", fake_with_tools)

    agent = _DummyAgent(api_key="fake-key", model="test-model")
    pool = FakePool()
    result = asyncio.run(task_engine.run_agent_task(agent, "cari berita AI", pool=pool, org_id="org-1"))

    assert result["status"] == "failed"
    assert result["verification"]["verified"] is False


def test_run_agent_task_filters_relevant_tools_to_agent_own_tools(monkeypatch):
    """Plan boleh saja menyebut tool yang TIDAK ada di agent.tools -- harus difilter, bukan dipercaya buta."""
    captured_tools = {}

    async def fake_json(self, messages, **kwargs):
        if "Pecah goal ini" in messages[-1]["content"]:
            return {"subtasks": ["satu subtask"], "relevant_tools": ["knowledge_search", "database_query"]}
        return {"verified": True, "reasoning": "ok"}

    async def fake_with_tools(self, messages, tools, *, tool_ctx, **kwargs):
        captured_tools["names"] = [t["function"]["name"] for t in tools]
        return {"final_answer": "ok", "tool_calls": [], "rounds": 1}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm_with_tools", fake_with_tools)

    agent = _DummyAgent(api_key="fake-key", model="test-model")  # tools = ["knowledge_search", "web_search"]
    pool = FakePool()
    asyncio.run(task_engine.run_agent_task(agent, "goal apapun", pool=pool, org_id="org-1"))

    # database_query TIDAK ada di agent.tools -- harus disaring, tidak boleh ikut terkirim ke LLM
    assert captured_tools["names"] == ["knowledge_search"]


def test_run_agent_task_persists_to_agent_task_executions_with_correct_org_scope(monkeypatch):
    async def fake_json(self, messages, **kwargs):
        if "Pecah goal ini" in messages[-1]["content"]:
            return {"subtasks": ["s1"], "relevant_tools": []}
        return {"verified": True, "reasoning": "ok"}

    async def fake_with_tools(self, messages, tools, *, tool_ctx, **kwargs):
        assert tool_ctx["org_id"] == "org-real"
        return {"final_answer": "ok", "tool_calls": [], "rounds": 1}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm_with_tools", fake_with_tools)

    agent = _DummyAgent(api_key="fake-key", model="test-model")
    pool = FakePool()
    asyncio.run(task_engine.run_agent_task(agent, "goal", pool=pool, org_id="org-real", bot_id="bot-1"))

    assert pool.inserted["org_id"] == "org-real"
    assert pool.inserted["bot_id"] == "bot-1"
    assert pool.inserted["agent_name"] == "test_agent"
    assert pool.inserted["status"] == "completed"
