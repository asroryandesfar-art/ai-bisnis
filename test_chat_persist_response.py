"""Unit test for _persist_and_build_chat_response (chat decomposition step 6)."""
import asyncio
import types

import main


class _Pool:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *a):
        self.executed.append(sql)
        return "OK"


def _call(pool, **over):
    kw = dict(
        pool=pool, bot={"org_id": "22222222-2222-2222-2222-222222222222"}, bot_id="bot-1",
        conv_id="conv-1", message="halo", answer="ANSWER", model_used="model-x",
        input_tokens=1, output_tokens=2, latency_ms=15,
        result=types.SimpleNamespace(suggested_followup=None, confidence=0.9),
        intent_routing={"intent": "general", "selected_agent": "CS Agent", "confidence": 0.9},
        should_handoff=False, handoff_reason=None, relevant_chunks=[],
        agent_meta=None, intelligence_context={}, is_new_conversation=True, user_meta={},
        chat_image_url=None, chat_image_provider=None, chat_ca_screenshot_url=None,
    )
    kw.update(over)
    return asyncio.run(main._persist_and_build_chat_response(**kw))


def test_builds_response_contract_and_persists():
    pool = _Pool()
    resp = _call(pool)
    assert resp["answer"] == "ANSWER"
    assert resp["session_id"] == "conv-1"
    assert resp["intent"] == "general"
    assert resp["selected_agent"] == "CS Agent"
    assert resp["handoff_offered"] is False
    assert resp["sources"] == []
    assert resp["message_id"]
    # assistant message + conversation stats persisted
    assert any("INSERT INTO messages" in s for s in pool.executed)
    assert any("UPDATE conversations" in s for s in pool.executed)


def test_sources_derived_from_relevant_chunks():
    pool = _Pool()
    chunks = [{"id": "c1", "filename": "doc.pdf", "chunk_index": 3}]
    resp = _call(pool, relevant_chunks=chunks)
    assert resp["sources"] == [{"document": "doc.pdf", "chunk_index": 3}]


def test_follow_up_from_result_suggestion():
    pool = _Pool()
    resp = _call(pool, result=types.SimpleNamespace(suggested_followup="Mau lanjut?", confidence=0.5))
    assert resp["follow_up_questions"] == ["Mau lanjut?"]


def test_handoff_offered_reflected():
    pool = _Pool()
    resp = _call(pool, should_handoff=True, handoff_reason="angry")
    assert resp["handoff_offered"] is True
