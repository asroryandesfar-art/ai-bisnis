"""Unit test for _chat_error_fallback (chat handler decomposition step 10)."""
import asyncio

import main

_BOT = {"org_id": "22222222-2222-2222-2222-222222222222"}


def _call(**over):
    kw = dict(
        exc=RuntimeError("pipeline boom"), market_answer="", t_start=0.0, pool=object(),
        bot=_BOT, bot_id="bot-1", conv_id="conv-1", user_meta={},
    )
    kw.update(over)
    return asyncio.run(main._chat_error_fallback(**kw))


def test_market_answer_fallback():
    answer, model, itok, otok, lat, meta = _call(market_answer="BTC is $100k")
    assert answer == "BTC is $100k"
    assert model == "system:market-data"
    assert meta["fallback"] == "market-data"
    assert "pipeline boom" in meta["errors"][0]


def test_human_handoff_fallback_enqueues_ticket(monkeypatch):
    enq = {"reason": None, "priority": None}

    async def _enq(pool, *, org_id, conversation_id, reason, priority):
        enq["reason"] = reason
        enq["priority"] = priority

    async def _noop_trigger(*a, **k):
        return None

    monkeypatch.setattr(main, "_platform_enqueue_handoff", _enq)
    monkeypatch.setattr(main, "_dispatch_workflow_trigger", _noop_trigger)

    answer, model, itok, otok, lat, meta = _call(market_answer="")
    assert "tim manusia" in answer
    assert model == "system:human-handoff"
    assert meta["handoff_reason"] == "ai_error"
    assert enq["reason"] == "ai_error"
    assert enq["priority"] == "high"


def test_tokens_are_zeroed():
    _, _, itok, otok, _, _ = _call(market_answer="x")
    assert itok == 0 and otok == 0
