"""
test_identity_reasoning.py — Tes untuk Reasoning Engine, Truthfulness Policy,
Comparison Engine, Self Identity Engine, Sales Control Policy, Context-Aware
Follow Up, dan VerificationAgent.score_meta_answer().

Mencakup 10 pertanyaan wajib dari spesifikasi "BotNesia harus berhenti
terdengar seperti brosur marketing":
  1. Apa kelebihanmu dibanding ChatGPT dan Claude?
  2. Apakah kamu lebih pintar dari Claude?
  3. Kenapa saya harus pilih BotNesia?
  4. Apa kelemahan BotNesia?
  5. Kalau ChatGPT lebih pintar, kenapa saya pakai BotNesia?
  6. Kapan saya sebaiknya tidak pakai BotNesia?
  7. Apa bedamu dengan chatbot biasa?
  8. Kenapa?
  9. Maksudnya?
  10. Apakah kamu cuma chatbot marketing?
"""
import asyncio

from base import BaseAgent
from identity_agent import (
    BOTNESIA_IDENTITY,
    BOTNESIA_LIMITATIONS,
    BOTNESIA_POSITIONING,
    BOTNESIA_STRENGTHS,
    IdentityAgent,
    is_comparison_question,
    is_meta_question,
    is_self_awareness_question,
)
from reasoning_controller import ReasoningController
from verification_agent import VerificationAgent


MANDATORY_QUESTIONS = [
    "Apa kelebihanmu dibanding ChatGPT dan Claude?",
    "Apakah kamu lebih pintar dari Claude?",
    "Kenapa saya harus pilih BotNesia?",
    "Apa kelemahan BotNesia?",
    "Kalau ChatGPT lebih pintar, kenapa saya pakai BotNesia?",
    "Kapan saya sebaiknya tidak pakai BotNesia?",
    "Apa bedamu dengan chatbot biasa?",
    "Kenapa?",
    "Maksudnya?",
    "Apakah kamu cuma chatbot marketing?",
]

_PRIOR_HISTORY = [
    {"role": "user", "content": "Apa bedamu dengan Claude?"},
    {"role": "assistant", "content": "Untuk reasoning umum Claude lebih kuat..."},
]


# ─────────────────────────────────────────────────────────────────
# 1) IdentityAgent — Self Identity Engine
# ─────────────────────────────────────────────────────────────────

def test_identity_block_contains_identity_strengths_limitations_positioning():
    agent = IdentityAgent()
    block = agent.identity_block()

    assert BOTNESIA_IDENTITY in block
    assert BOTNESIA_POSITIONING in block
    for s in BOTNESIA_STRENGTHS:
        assert s in block
    for l in BOTNESIA_LIMITATIONS:
        assert l in block


def test_identity_policy_blocks_are_non_empty():
    agent = IdentityAgent()
    assert "Truthfulness Policy" in agent.truthfulness_policy()
    assert "Sales Control Policy" in agent.sales_control_policy()
    assert "Perbandingan" in agent.comparison_format()
    assert "Kebijakan Jawaban" in agent.core_policy_block()


# ─────────────────────────────────────────────────────────────────
# 2) Deteksi pertanyaan meta (Comparison Engine + Self-Awareness)
# ─────────────────────────────────────────────────────────────────

def test_mandatory_questions_are_meta_or_followup():
    rc = ReasoningController()
    for q in MANDATORY_QUESTIONS:
        brief = rc.analyze({"user_message": q, "messages": _PRIOR_HISTORY})
        assert brief["is_meta"] or brief["is_followup"], f"not detected: {q}"
        assert brief["style_guidance"], f"missing style guidance: {q}"


def test_comparison_questions_mentioning_competitors():
    comparison_questions = [
        "Apa kelebihanmu dibanding ChatGPT dan Claude?",
        "Apakah kamu lebih pintar dari Claude?",
        "Kalau ChatGPT lebih pintar, kenapa saya pakai BotNesia?",
        "Apa bedamu dengan chatbot biasa?",
    ]
    for q in comparison_questions:
        assert is_comparison_question(q), q
        assert is_meta_question(q), q


def test_self_awareness_questions_without_competitor_mention():
    self_awareness_questions = [
        "Kenapa saya harus pilih BotNesia?",
        "Apa kelemahan BotNesia?",
        "Kapan saya sebaiknya tidak pakai BotNesia?",
        "Apakah kamu cuma chatbot marketing?",
    ]
    for q in self_awareness_questions:
        assert is_self_awareness_question(q), q
        assert is_meta_question(q), q


# ─────────────────────────────────────────────────────────────────
# 3) Context-Aware Follow Up
# ─────────────────────────────────────────────────────────────────

def test_short_followups_are_detected_with_history():
    rc = ReasoningController()
    for q in ("Kenapa?", "Maksudnya?", "Terus?"):
        brief = rc.analyze({"user_message": q, "messages": _PRIOR_HISTORY})
        assert brief["is_followup"] is True, q
        assert brief["intent_type"] == "followup"
        assert "Follow-up" in brief["style_guidance"]


def test_bedanya_is_both_followup_and_self_awareness():
    # "Bedanya?" continues a comparison topic ("Apa bedamu dengan Claude?") AND
    # itself matches the self-awareness pattern — both flags should be set so
    # the answer gets identity/comparison guidance AND the follow-up note.
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bedanya?", "messages": _PRIOR_HISTORY})

    assert brief["is_followup"] is True
    assert brief["is_meta"] is True
    assert "Follow-up" in brief["style_guidance"]
    assert "Identitas & Posisi BotNesia" in brief["style_guidance"]


def test_followup_not_detected_without_history():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Kenapa?", "messages": []})
    assert brief["is_followup"] is False


def test_general_question_only_gets_core_policy_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert brief["intent_type"] == "general"
    assert brief["is_meta"] is False
    assert "Kebijakan Jawaban" in brief["style_guidance"]
    assert "Identitas & Posisi BotNesia" not in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 4) VerificationAgent.score_meta_answer — heuristik anti-brosur
# ─────────────────────────────────────────────────────────────────

_BAD_ANSWER = (
    "Anda harus memilih BotNesia karena paket Enterprise BotNesia paling lengkap "
    "dan BotNesia adalah solusi terbaik untuk bisnis Anda."
)

_GOOD_ANSWER = (
    "Untuk reasoning umum, coding kompleks, dan pengetahuan luas, ChatGPT dan Claude "
    "kemungkinan masih lebih kuat dibanding BotNesia. Namun BotNesia punya tujuan "
    "berbeda: terhubung dengan data bisnis Anda seperti paket, billing, channel, dan "
    "knowledge base. BotNesia bukan pengganti ChatGPT/Claude untuk reasoning umum. "
    "Jadi jika Anda butuh AI umum, gunakan ChatGPT/Claude; jika Anda butuh AI yang "
    "terhubung dengan operasional bisnis Anda, BotNesia lebih relevan."
)


def test_score_meta_answer_flags_marketing_brochure_answer():
    agent = VerificationAgent(api_key="test-key")
    brief = ReasoningController().analyze(
        {"user_message": "Apa kelebihanmu dibanding ChatGPT dan Claude?", "messages": []}
    )

    scores = agent.score_meta_answer(
        "Apa kelebihanmu dibanding ChatGPT dan Claude?", _BAD_ANSWER, brief
    )

    assert scores["marketing_bias_score"] >= 50
    assert scores["needs_rewrite"] is True
    assert scores["issues"]


def test_score_meta_answer_accepts_honest_comparison_answer():
    agent = VerificationAgent(api_key="test-key")
    brief = ReasoningController().analyze(
        {"user_message": "Apa kelebihanmu dibanding ChatGPT dan Claude?", "messages": []}
    )

    scores = agent.score_meta_answer(
        "Apa kelebihanmu dibanding ChatGPT dan Claude?", _GOOD_ANSWER, brief
    )

    assert scores["marketing_bias_score"] == 0
    assert scores["needs_rewrite"] is False
    assert scores["truthfulness_score"] >= 60
    assert scores["comparison_score"] >= 50


# ─────────────────────────────────────────────────────────────────
# 5) Supervisor integration — Standard mode meta-question rewrite
# ─────────────────────────────────────────────────────────────────

async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def test_standard_mode_rewrites_marketing_brochure_meta_answer(monkeypatch):
    calls = {"n": 0}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        system = messages[0]["content"] if messages else ""
        calls["n"] += 1
        if "Catatan perbaikan dari verifikasi" in system:
            return _GOOD_ANSWER
        return _BAD_ANSWER

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Apa kelebihanmu dibanding ChatGPT dan Claude?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_mode_used == "standard"
    assert result.reasoning_brief["is_comparison"] is True
    assert result.meta_rewrite_applied is True
    assert result.meta_scores["needs_rewrite"] is False
    assert result.final_answer == _GOOD_ANSWER
    # Identity/Comparison/Truthfulness blocks must be injected for meta questions.
    assert "Identitas & Posisi BotNesia" in result.reasoning_brief["style_guidance"]
    assert "Truthfulness Policy" in result.reasoning_brief["style_guidance"]


def test_standard_mode_keeps_already_honest_meta_answer(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return _GOOD_ANSWER

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Apakah kamu lebih pintar dari Claude?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.meta_rewrite_applied is False
    assert result.meta_scores["needs_rewrite"] is False
    assert result.final_answer == _GOOD_ANSWER


def test_standard_mode_followup_carries_context_note(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Lanjutan dari jawaban sebelumnya."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Kenapa?",
        "messages": _PRIOR_HISTORY,
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_brief["is_followup"] is True
    assert result.reasoning_brief["intent_type"] == "followup"
    assert result.meta_rewrite_applied is False
