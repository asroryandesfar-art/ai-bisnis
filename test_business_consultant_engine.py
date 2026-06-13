"""
test_business_consultant_engine.py — Tes untuk Strategic Thinking Agent,
Business Consultant Mode, dan Prioritization Agent.

Mencakup pertanyaan dari spesifikasi "melatih otak BotNesia menjadi AI Business
Operating System / Consultant / Copilot / Thinker":
  - Kenapa bisnis saya sepi?
  - Haruskah saya merekrut karyawan?
  - Apa prioritas saya saat ini?
  - Haruskah saya menurunkan harga?
  - (multi-masalah) website lambat, penjualan turun, biaya tinggi, customer komplain
"""
import asyncio

from base import BaseAgent
from business_consultant_engine import (
    BUSINESS_CONSULTANT_BLOCK,
    PRIORITIZATION_BLOCK,
    STRATEGIC_THINKING_BLOCK,
    has_multiple_problems,
    is_business_strategy_question,
)
from reasoning_controller import ReasoningController


BUSINESS_STRATEGY_QUESTIONS = [
    "Kenapa bisnis saya sepi?",
    "Haruskah saya merekrut karyawan?",
    "Apa prioritas saya saat ini?",
    "Haruskah saya menurunkan harga?",
]

MULTI_PROBLEM_MESSAGE = (
    "Masalah saya banyak:\n"
    "- website lambat\n"
    "- penjualan turun\n"
    "- biaya tinggi\n"
    "- customer komplain\n"
    "Apa yang harus saya lakukan dulu?"
)


# ─────────────────────────────────────────────────────────────────
# 1) Deteksi pertanyaan strategi bisnis
# ─────────────────────────────────────────────────────────────────

def test_business_strategy_questions_are_detected():
    for q in BUSINESS_STRATEGY_QUESTIONS:
        assert is_business_strategy_question(q), q


def test_self_awareness_questions_are_not_business_strategy():
    # Pertanyaan tentang BotNesia sendiri (sudah ditangani Self Identity Engine)
    # tidak boleh ikut memicu Business Consultant Mode.
    for q in ("Apa kelemahanmu?", "Kenapa saya harus pilih BotNesia?"):
        rc = ReasoningController()
        brief = rc.analyze({"user_message": q, "messages": []})
        assert brief["is_business_strategy"] is False, q


def test_general_question_is_not_business_strategy():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})
    assert brief["is_business_strategy"] is False
    assert brief["intent_type"] == "general"


# ─────────────────────────────────────────────────────────────────
# 2) ReasoningController — Strategic Thinking + Business Consultant Mode
# ─────────────────────────────────────────────────────────────────

def test_business_strategy_questions_get_strategic_and_consultant_blocks():
    rc = ReasoningController()
    for q in BUSINESS_STRATEGY_QUESTIONS:
        brief = rc.analyze({"user_message": q, "messages": []})
        assert brief["intent_type"] == "business_strategy", q
        assert brief["is_business_strategy"] is True, q
        assert "Strategic Thinking" in brief["style_guidance"], q
        assert "Business Consultant Mode" in brief["style_guidance"], q


# ─────────────────────────────────────────────────────────────────
# 3) Prioritization — beberapa masalah sekaligus
# ─────────────────────────────────────────────────────────────────

def test_has_multiple_problems_detects_list():
    assert has_multiple_problems(MULTI_PROBLEM_MESSAGE) is True


def test_single_question_has_no_multiple_problems():
    assert has_multiple_problems("Haruskah saya menurunkan harga?") is False


def test_multi_problem_message_triggers_prioritization_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": MULTI_PROBLEM_MESSAGE, "messages": []})

    assert brief["is_business_strategy"] is True
    assert brief["needs_prioritization"] is True
    assert PRIORITIZATION_BLOCK.splitlines()[0] in brief["style_guidance"]
    assert STRATEGIC_THINKING_BLOCK.splitlines()[0] in brief["style_guidance"]
    assert BUSINESS_CONSULTANT_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_single_business_question_does_not_trigger_prioritization():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Haruskah saya menurunkan harga?", "messages": []})

    assert brief["is_business_strategy"] is True
    assert brief["needs_prioritization"] is False
    assert "Prioritization" not in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 4) Supervisor integration — Standard mode
# ─────────────────────────────────────────────────────────────────

async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def test_standard_mode_business_question_carries_consultant_guidance(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Jawaban konsultan tentang strategi harga."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Haruskah saya menurunkan harga?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_mode_used == "standard"
    assert result.reasoning_brief["intent_type"] == "business_strategy"
    assert result.reasoning_brief["is_business_strategy"] is True
    assert "Strategic Thinking" in result.reasoning_brief["style_guidance"]
    assert "Business Consultant Mode" in result.reasoning_brief["style_guidance"]
