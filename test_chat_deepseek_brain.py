"""Unit test for _maybe_deepseek_brain_answer (chat decomposition step 4)."""
import asyncio
import types

import main

_BOT = {"plan": "starter", "org_id": "22222222-2222-2222-2222-222222222222", "system_prompt": ""}


class _Pool:
    async def execute(self, *a, **k):
        return "OK"


def _run(**over):
    kw = dict(message="halo", bot=_BOT, bot_id="bot-1", conv_id="conv-1", pool=_Pool())
    kw.update(over)
    return asyncio.run(main._maybe_deepseek_brain_answer(**kw))


def test_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(main.cfg, "deepseek_brain_enabled", False)
    assert _run() is None


def test_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr(main.cfg, "deepseek_brain_enabled", True)
    monkeypatch.setattr(main.cfg, "deepseek_api_key", "")
    assert _run() is None


def test_returns_response_dict_and_persists(monkeypatch):
    monkeypatch.setattr(main.cfg, "deepseek_brain_enabled", True)
    monkeypatch.setattr(main.cfg, "deepseek_api_key", "sk-test")

    tier = types.SimpleNamespace(name="FAST")
    br = types.SimpleNamespace(answer="Halo!", model="deepseek-chat", tier=tier, escalate=False)

    class _Brain:
        async def answer(self, *a, **k):
            return br

    monkeypatch.setattr(main, "get_deepseek_brain", lambda: _Brain())

    out = _run()
    assert out is not None
    assert out["answer"] == "Halo!"
    assert out["intent"] == "deepseek_fast"
    assert out["selected_agent"] == "DeepSeek FAST"
    assert out["session_id"] == "conv-1"


def test_falls_back_to_none_on_error(monkeypatch):
    monkeypatch.setattr(main.cfg, "deepseek_brain_enabled", True)
    monkeypatch.setattr(main.cfg, "deepseek_api_key", "sk-test")

    def _boom():
        raise RuntimeError("brain init failed")

    monkeypatch.setattr(main, "get_deepseek_brain", _boom)
    assert _run() is None
