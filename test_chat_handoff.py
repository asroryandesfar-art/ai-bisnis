"""Unit test for _apply_handoff (chat handler decomposition step 8)."""
import asyncio
import types

import main

_BOT = {"org_id": "22222222-2222-2222-2222-222222222222"}


def _call(**over):
    kw = dict(
        should_handoff=False,
        result=types.SimpleNamespace(escalation_message="Menghubungkan ke tim manusia."),
        answer="Jawaban.", pool=object(), bot=_BOT, bot_id="bot-1", conv_id="conv-1",
        handoff_reason="angry", handoff_priority="high", user_meta={},
    )
    kw.update(over)
    return asyncio.run(main._apply_handoff(**kw))


def test_no_handoff_returns_answer_unchanged(monkeypatch):
    enq = {"n": 0}

    async def _enq(*a, **k):
        enq["n"] += 1

    monkeypatch.setattr(main, "_platform_enqueue_handoff", _enq)
    out = _call(should_handoff=False)
    assert out == "Jawaban."
    assert enq["n"] == 0


def test_handoff_appends_message_and_enqueues(monkeypatch):
    enq = {"reason": None, "priority": None}

    async def _enq(pool, *, org_id, conversation_id, reason, priority):
        enq["reason"] = reason
        enq["priority"] = priority

    async def _noop_trigger(*a, **k):
        return None

    monkeypatch.setattr(main, "_platform_enqueue_handoff", _enq)
    monkeypatch.setattr(main, "_dispatch_workflow_trigger", _noop_trigger)
    out = _call(should_handoff=True)
    assert "Menghubungkan ke tim manusia." in out
    assert enq["reason"] == "angry"
    assert enq["priority"] == "high"


def test_handoff_message_not_duplicated_if_already_present(monkeypatch):
    async def _enq(*a, **k):
        return None

    async def _noop_trigger(*a, **k):
        return None

    monkeypatch.setattr(main, "_platform_enqueue_handoff", _enq)
    monkeypatch.setattr(main, "_dispatch_workflow_trigger", _noop_trigger)
    msg = "Menghubungkan ke tim manusia."
    out = _call(should_handoff=True, answer=f"Jawaban. {msg}")
    # message already present -> not appended again
    assert out.count(msg) == 1
