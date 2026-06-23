"""test_base_tool_calling.py — BaseAgent._call_llm_with_tools(): loop
tool-calling sungguhan (Groq tools= -> tool_calls -> eksekusi -> re-call),
bukan dispatch if/else manual. Mock di level httpx (transport), bukan
di level method, supaya request/response shape ke Groq benar-benar diuji."""
import asyncio
import json

import base
from base import BaseAgent


class _FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    """Mengembalikan satu response per call sesuai urutan `responses`."""
    def __init__(self, responses, captured):
        self._responses = list(responses)
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured.append(json)
        return self._responses.pop(0)


def _patch_httpx(monkeypatch, responses):
    captured = []
    monkeypatch.setattr(base, "httpx", type("M", (), {
        "AsyncClient": lambda timeout=None: _FakeAsyncClient(responses, captured),
    }))
    return captured


def _groq_message(*, content=None, tool_calls=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_no_tool_call_returns_final_answer_in_one_round(monkeypatch):
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)
    responses = [_FakeResponse(200, _groq_message(content="Jawaban langsung tanpa tool."))]
    _patch_httpx(monkeypatch, responses)

    agent = BaseAgent(api_key="fake-key", model="test-model")
    result = asyncio.run(agent._call_llm_with_tools(
        [{"role": "user", "content": "hai"}], tools=[], tool_ctx={"pool": None, "org_id": "org-1"},
    ))
    assert result["final_answer"] == "Jawaban langsung tanpa tool."
    assert result["tool_calls"] == []
    assert result["rounds"] == 1


def test_tool_call_is_actually_executed_then_model_called_again(monkeypatch):
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    executed = {}

    async def fake_executor(name, args, *, ctx):
        executed["name"] = name
        executed["args"] = args
        executed["ctx"] = ctx
        return {"success": True, "results": ["data nyata dari tool"]}

    monkeypatch.setattr("tool_executor.execute_tool", fake_executor)

    tool_call = {
        "id": "call_1",
        "function": {"name": "knowledge_search", "arguments": json.dumps({"query": "jam buka toko"})},
    }
    responses = [
        _FakeResponse(200, _groq_message(tool_calls=[tool_call])),
        _FakeResponse(200, _groq_message(content="Berdasarkan knowledge base, toko buka 09:00-17:00.")),
    ]
    _patch_httpx(monkeypatch, responses)

    agent = BaseAgent(api_key="fake-key", model="test-model")
    result = asyncio.run(agent._call_llm_with_tools(
        [{"role": "user", "content": "jam buka toko jam berapa?"}],
        tools=[{"type": "function", "function": {"name": "knowledge_search"}}],
        tool_ctx={"pool": None, "org_id": "org-1"},
    ))

    assert executed["name"] == "knowledge_search"
    assert executed["args"] == {"query": "jam buka toko"}
    assert result["final_answer"] == "Berdasarkan knowledge base, toko buka 09:00-17:00."
    assert result["rounds"] == 2
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["result"]["success"] is True


def test_max_rounds_stops_infinite_tool_call_loop(monkeypatch):
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    async def fake_executor(name, args, *, ctx):
        return {"success": True}
    monkeypatch.setattr("tool_executor.execute_tool", fake_executor)

    tool_call = {"id": "call_x", "function": {"name": "web_search", "arguments": "{}"}}
    # Model SELALU minta tool lagi, tidak pernah berhenti -- harus dipotong max_rounds.
    responses = [_FakeResponse(200, _groq_message(tool_calls=[tool_call])) for _ in range(5)]
    _patch_httpx(monkeypatch, responses)

    agent = BaseAgent(api_key="fake-key", model="test-model")
    result = asyncio.run(agent._call_llm_with_tools(
        [{"role": "user", "content": "cari terus"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        tool_ctx={"pool": None, "org_id": "org-1"}, max_rounds=3,
    ))
    assert result["rounds"] == 3
    assert len(result["tool_calls"]) == 3


def test_no_api_key_raises_clear_error():
    agent = BaseAgent(api_key="", model="test-model")
    try:
        asyncio.run(agent._call_llm_with_tools([{"role": "user", "content": "x"}], tools=[], tool_ctx={}))
        assert False, "harus raise"
    except RuntimeError as exc:
        assert "API key kosong" in str(exc)
