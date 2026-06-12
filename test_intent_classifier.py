import asyncio

import pytest

from base import BaseAgent, parse_json_response
from intent_classifier import heuristic_complexity, IntentClassifier


def test_heuristic_complexity_greeting_is_simple():
    assert heuristic_complexity("Halo, apa kabar?") == "simple"


def test_heuristic_complexity_btc_question_is_complex():
    assert heuristic_complexity("Kenapa BTC turun dari 70k ke 59k?") == "complex"


def test_heuristic_complexity_price_question_is_simple():
    assert heuristic_complexity("Halo, harga paket berapa?") == "simple"


def test_parse_json_response_with_markdown_fence():
    raw = '```json\n{"verified": true, "confidence_score": 80}\n```'
    assert parse_json_response(raw) == {"verified": True, "confidence_score": 80}


def test_parse_json_response_invalid_returns_default():
    assert parse_json_response("not json at all", default={"a": 1}) == {"a": 1}
    assert parse_json_response("not json at all") == {}


def test_call_llm_json_mode_includes_response_format(monkeypatch):
    captured = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["response_format"] = response_format
        return '{"complexity": "simple", "reason": "ok"}'

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    agent = BaseAgent(api_key="test-key")
    result = asyncio.run(agent._call_llm_json([{"role": "user", "content": "hi"}]))

    assert captured["response_format"] == {"type": "json_object"}
    assert result == {"complexity": "simple", "reason": "ok"}


def test_call_llm_plain_mode_omits_response_format(monkeypatch):
    captured = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["response_format"] = response_format
        return "plain text"

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    agent = BaseAgent(api_key="test-key")
    result = asyncio.run(agent._call_llm([{"role": "user", "content": "hi"}]))

    assert captured["response_format"] is None
    assert result == "plain text"


def test_intent_classifier_ambiguous_message_falls_back_to_llm(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return {"complexity": "complex", "reason": "butuh analisis"}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    classifier = IntentClassifier(api_key="test-key")
    # Pesan netral, panjang, tanpa kata kunci simple/complex -> ambigu
    msg = "Tolong jelaskan secara umum mengenai layanan yang tersedia di platform ini untuk kebutuhan tim kami"
    result = asyncio.run(classifier.classify(msg))

    assert result["source"] == "llm"
    assert result["complexity"] == "complex"


def test_supervisor_standard_mode_unchanged(monkeypatch):
    from supervisor import SupervisorAgent

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        if response_format is not None:
            return '{"facts_to_store": [], "summary": "", "forget_keys": []}'
        return "Jawaban dari CS Agent."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    supervisor = SupervisorAgent(api_key="test-key")
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Halo, apa kabar?",
        "messages": [],
        "knowledge_base_context": "",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_mode_used == "standard"
    assert result.final_answer == "Jawaban dari CS Agent."
