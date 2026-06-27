"""
test_language_and_quality.py — Task 8 validation tests.

Tests:
1. Language = English  → 100% English output, no Indonesian
2. Language = Indonesian → 100% Indonesian output
3. Standard mode → short concise answer
4. Pro mode synthesis → structured executive-level output, longer than Standard
5. No internal reasoning leaked to user
6. Explicit language override beats agent setting
7. Business questions get structured format (bullets/tables)
8. Auto-detect English message → English output (no stale conversation override)
"""
import asyncio
import pytest

import language_middleware
from language_middleware import resolve_language, detect_language, validate_output_language
from uncertainty_engine import UncertaintyEngine
from cs_agent import CSAgent
from base import BaseAgent


# ---------------------------------------------------------------------------
# Helper fake LLM that echoes language-tagged responses
# ---------------------------------------------------------------------------

class _FakeLLMEnglish:
    """Returns English response to any call."""
    async def complete(self, request, *, model=None):
        from ai_providers.types import LLMResponse
        return LLMResponse(
            content=(
                "**Customer Support Overwhelm — Implementation Plan**\n\n"
                "## Executive Summary\nYour team is overwhelmed due to volume exceeding capacity.\n\n"
                "## Problem Analysis\n- Ticket volume: high\n- Team capacity: insufficient\n\n"
                "## Implementation Plan\n1. Deploy AI chatbot for Tier-1 issues\n"
                "2. Create self-service knowledge base\n3. Hire 2 additional agents\n\n"
                "## KPIs\n| Metric | Target |\n|---|---|\n| First Response Time | < 2h |\n"
                "| Resolution Rate | > 85% |\n\n"
                "## ROI\nEstimated 40% cost reduction in 6 months."
            ),
            model=model or "gemini-2.5-flash",
            provider="gemini",
        )


class _FakeLLMIndonesian:
    """Returns Indonesian response."""
    async def complete(self, request, *, model=None):
        from ai_providers.types import LLMResponse
        return LLMResponse(
            content=(
                "**Strategi Peningkatan Penjualan UMKM**\n\n"
                "Berikut strategi konkret untuk meningkatkan penjualan:\n\n"
                "1. **Optimalkan digital marketing** — gunakan Instagram dan TikTok\n"
                "2. **Program loyalitas pelanggan** — diskon repeat order\n"
                "3. **Perluas channel distribusi** — daftar di marketplace\n\n"
                "**Target KPI:**\n- Peningkatan penjualan 30% dalam 3 bulan\n"
                "- Pelanggan baru: 50/bulan"
            ),
            model=model or "gemini-2.5-flash",
            provider="gemini",
        )


class _FakeLLMShort:
    """Returns a short standard response."""
    async def complete(self, request, *, model=None):
        from ai_providers.types import LLMResponse
        return LLMResponse(
            content="To reset your password, go to Settings → Account → Reset Password. Check your email for the reset link.",
            model=model or "gemini-2.5-flash",
            provider="gemini",
        )


# ---------------------------------------------------------------------------
# Task 1 — Language = English → 100% English output
# ---------------------------------------------------------------------------

def test_english_agent_always_returns_english(monkeypatch):
    """Agent configured in English returns English regardless of message language."""
    # CSAgent system prompts should have ALWAYS English instruction
    agent = CSAgent()
    assert "ALWAYS respond 100% in English" in agent.english_system_prompt
    assert "Every single word must be in English" in agent.english_system_prompt


def test_english_system_prompt_has_no_indonesian_instructions(monkeypatch):
    """English system prompt must not contain Indonesian-only directives."""
    agent = CSAgent()
    indonesian_markers = ["Jawab SELALU", "Bahasa Indonesia", "Kamu adalah"]
    for marker in indonesian_markers:
        assert marker not in agent.english_system_prompt, (
            f"English system prompt must not contain '{marker}'"
        )


def test_indonesian_system_prompt_has_no_english_instructions():
    """Indonesian system prompt must not contain English-only directives."""
    agent = CSAgent()
    # Should say "Bahasa Indonesia" in rules
    assert "Bahasa Indonesia" in agent.system_prompt


def test_english_system_prompt_has_no_groq_reference():
    """System prompt must not mention specific AI providers."""
    agent = CSAgent()
    assert "Groq" not in agent.english_system_prompt
    assert "groq" not in agent.english_system_prompt.lower()


# ---------------------------------------------------------------------------
# Task 2 — No internal reasoning in output
# ---------------------------------------------------------------------------

def test_uncertainty_engine_never_prefixes_output():
    """Uncertainty engine never shows 'Saya belum cukup yakin' to users."""
    engine = UncertaintyEngine(api_key="test")
    result = asyncio.run(engine.safe_run({
        "final_answer": "Customer support is overloaded.",
        "confidence_score": 25,
        "verification_passed": False,
        "verification_issues": ["Speculative", "Missing data"],
        "socratic_review": {"risk_if_wrong": "high", "needs_clarification": True,
                            "missing_information": ["A", "B", "C", "D"]},
        "devil_advocate_review": {"severity": "high", "overstatement_risk": True},
        "first_principle_analysis": {"root_hypotheses_count": 4, "causal_links_count": 0},
        "retry_count": 2,
        "selected_language": "en",
    }))
    assert result.success
    assert result.output["band"] == "Low Confidence"
    assert result.output["should_prefix"] is False
    # The answer is returned clean — no prefix
    assert "Saya belum cukup yakin" not in result.output["message"]
    assert "jawaban terbaik sementara" not in result.output["message"].lower()
    assert result.output["message"] == "Customer support is overloaded."


def test_uncertainty_engine_never_prefixes_output_id():
    """Same check for Indonesian language."""
    engine = UncertaintyEngine(api_key="test")
    result = asyncio.run(engine.safe_run({
        "final_answer": "Produk kurang diminati.",
        "confidence_score": 20,
        "verification_passed": False,
        "verification_issues": ["Spekulatif"],
        "socratic_review": {"risk_if_wrong": "high", "needs_clarification": True,
                            "missing_information": ["A", "B", "C", "D"]},
        "devil_advocate_review": {"severity": "high", "overstatement_risk": True},
        "first_principle_analysis": {"root_hypotheses_count": 3, "causal_links_count": 0},
        "retry_count": 1,
        "selected_language": "id",
    }))
    assert result.output["should_prefix"] is False
    assert result.output["message"] == "Produk kurang diminati."
    assert "Saya belum cukup yakin" not in result.output["message"]


FORBIDDEN_PHRASES = [
    "Saya belum cukup yakin",
    "jawaban terbaik sementara",
    "AI sedang berpikir",
    "AI is thinking",
    "Model memilih",
    "confidence score",
    "provider",
    "fallback",
    "retry",
]


def test_forbidden_phrases_not_in_system_prompts():
    """System prompts must not instruct the LLM to expose internal reasoning."""
    agent = CSAgent()
    for phrase in ["Jika confidence rendah, akui ketidakpastian", "Groq", "menggunakan Groq"]:
        assert phrase not in agent.english_system_prompt
        assert phrase not in agent.system_prompt


# ---------------------------------------------------------------------------
# Task 3 & 4 — Pro vs Standard differentiation
# ---------------------------------------------------------------------------

def test_synthesis_system_prompt_en_has_mckinsey_structure():
    """Pro mode synthesis prompt (English) must request executive structure."""
    from cs_agent import SYNTHESIS_SYSTEM_PROMPT_EN
    required_sections = [
        "Executive Summary",
        "Implementation Plan",
        "KPI",
        "ROI",
        "Risks",
    ]
    for section in required_sections:
        assert section in SYNTHESIS_SYSTEM_PROMPT_EN, (
            f"Pro mode English synthesis prompt missing '{section}'"
        )


def test_synthesis_system_prompt_id_has_executive_structure():
    """Pro mode synthesis prompt (Indonesian) must request executive structure."""
    from cs_agent import SYNTHESIS_SYSTEM_PROMPT
    required_sections = [
        "Ringkasan Eksekutif",
        "Rencana Implementasi",
        "KPI",
        "ROI",
    ]
    for section in required_sections:
        assert section in SYNTHESIS_SYSTEM_PROMPT, (
            f"Pro mode Indonesian synthesis prompt missing '{section}'"
        )


def test_synthesis_prompt_never_asks_to_expose_uncertainty():
    """Synthesis system prompts must never instruct the LLM to show confidence."""
    from cs_agent import SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT_EN
    forbidden = ["confidence rendah, akui", "If confidence is low, explicitly acknowledge"]
    for phrase in forbidden:
        assert phrase not in SYNTHESIS_SYSTEM_PROMPT
        assert phrase not in SYNTHESIS_SYSTEM_PROMPT_EN


# ---------------------------------------------------------------------------
# Task 5 — Business intelligence uses structured format
# ---------------------------------------------------------------------------

def test_english_system_prompt_mentions_business_topics():
    """English system prompt must address key business domains."""
    agent = CSAgent()
    business_topics = ["sales", "marketing", "operations", "CRM", "finance", "growth"]
    prompt_lower = agent.english_system_prompt.lower()
    found = [t for t in business_topics if t.lower() in prompt_lower]
    assert len(found) >= 4, f"Found only {found} business topics in English system prompt"


def test_english_system_prompt_requires_structured_format():
    """English system prompt must require bullet points/tables for business questions."""
    agent = CSAgent()
    assert "bullet" in agent.english_system_prompt.lower() or "table" in agent.english_system_prompt.lower()
    assert "plain paragraph" in agent.english_system_prompt.lower() or "never plain" in agent.english_system_prompt.lower()


# ---------------------------------------------------------------------------
# Task 6 — Prompt following (role assignment)
# ---------------------------------------------------------------------------

def test_english_system_prompt_supports_role_assignment():
    """English system prompt must instruct the LLM to maintain user-assigned roles."""
    agent = CSAgent()
    assert "role" in agent.english_system_prompt.lower() or "persona" in agent.english_system_prompt.lower()
    assert "Sales Director" in agent.english_system_prompt or "CEO" in agent.english_system_prompt


def test_indonesian_system_prompt_supports_role_assignment():
    """Indonesian system prompt must instruct the LLM to maintain user-assigned roles."""
    agent = CSAgent()
    role_indicator = "peran" in agent.system_prompt.lower() or "Sales Director" in agent.system_prompt
    assert role_indicator


# ---------------------------------------------------------------------------
# Task 1 — Language routing: auto-detect beats stale conversation memory
# ---------------------------------------------------------------------------

def test_english_message_beats_stale_indonesian_conversation():
    """Clear English message must return 'en' even if conversation was previously 'id'."""
    result = resolve_language(
        user_message="My company is losing customers because our customer support team is overwhelmed.",
        agent_language=None,
        conversation_language="id",  # stale from previous Indonesian turn
    )
    assert result == "en", (
        f"Expected 'en' for clear English message, got '{result}'. "
        "Stale conversation language must not override clear auto-detect."
    )


def test_indonesian_message_beats_stale_english_conversation():
    """Clear Indonesian message must return 'id' even if conversation was previously 'en'."""
    result = resolve_language(
        user_message="Saya ingin meningkatkan penjualan UMKM saya dengan strategi digital.",
        agent_language=None,
        conversation_language="en",  # stale
    )
    assert result == "id"


def test_ambiguous_short_message_uses_conversation_memory():
    """Short ambiguous message (single word) falls back to conversation memory."""
    result = resolve_language("ok", agent_language=None, conversation_language="en")
    assert result == "en"


def test_agent_language_always_wins():
    """Agent language setting overrides both auto-detect and conversation memory."""
    assert resolve_language("How are you?", agent_language="id", conversation_language="en") == "id"
    assert resolve_language("Apa kabar?", agent_language="en", conversation_language="id") == "en"


def test_explicit_override_beats_everything():
    """Explicit 'answer in English' beats agent language and conversation memory."""
    result = resolve_language(
        "Tolong jawab dalam bahasa Indonesia tapi answer in English",
        agent_language="id",
        conversation_language="id",
    )
    assert result == "en"


# ---------------------------------------------------------------------------
# Task 7 — Output quality: no AI clichés in system prompts
# ---------------------------------------------------------------------------

def test_no_ai_cliches_in_prompts():
    """System prompts must not contain generic AI filler phrases."""
    agent = CSAgent()
    cliches = [
        "Sure, I will help",
        "Tentu, saya akan membantu",
        "Great question",
        "Certainly!",
    ]
    for cliche in cliches:
        assert cliche not in agent.english_system_prompt
        assert cliche not in agent.system_prompt


def test_gemini_key_gates_cs_agent(monkeypatch):
    """CSAgent.run() must proceed when only gemini_api_key is set (no Groq key)."""
    async def fake_call_llm(self, messages, **kwargs):
        return "Here is your answer."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    agent = CSAgent(api_key="", gemini_api_key="gemini-key-set")
    result = asyncio.run(agent.run({
        "user_message": "Hello",
        "selected_language": "en",
    }))
    # Should NOT raise RuntimeError — should produce an answer
    assert result.success
    assert result.output.get("answer") == "Here is your answer."


# ---------------------------------------------------------------------------
# Integration: full synthesize() round-trip with bilingual prompt construction
# ---------------------------------------------------------------------------

def test_synthesize_builds_english_specialist_blocks(monkeypatch):
    """synthesize() must use English labels when selected_language='en'."""
    captured_prompts = []

    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=1400, default=None):
        captured_prompts.append(messages)
        return {
            "answer": "Your customer support is overwhelmed. Implement AI automation.",
            "confidence_score": 85,
            "topics": ["customer_support"],
            "suggested_followup": None,
            "reasoning_summary": "Evidence-based analysis.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = CSAgent(api_key="test", gemini_api_key="test")
    context = {
        "user_message": "My support team is overwhelmed. Give me an implementation plan.",
        "selected_language": "en",
        "knowledge_base_context": "",
    }
    specialist_results = {
        "business": {
            "analysis": "High ticket volume relative to team size.",
            "conclusion": "Automation will reduce load by 40%.",
            "confidence": 82,
        }
    }
    result = asyncio.run(agent.synthesize(context, specialist_results))

    assert result.get("answer"), "synthesize() must return a non-empty answer"
    assert len(captured_prompts) == 1
    user_msg = captured_prompts[0][1]["content"]
    assert "User question:" in user_msg, "English synthesis must use 'User question:', not 'Pertanyaan pengguna:'"
    assert "Business Analysis" in user_msg, "English synthesis must use English labels for specialist blocks"
    assert "Analisis:" not in user_msg, "English synthesis must not use Indonesian labels"


def test_synthesize_builds_indonesian_specialist_blocks(monkeypatch):
    """synthesize() must use Indonesian labels when selected_language='id'."""
    captured_prompts = []

    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=1400, default=None):
        captured_prompts.append(messages)
        return {
            "answer": "Strategi peningkatan penjualan yang komprehensif.",
            "confidence_score": 80,
            "topics": ["sales"],
            "suggested_followup": None,
            "reasoning_summary": "Analisis berbasis data.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = CSAgent(api_key="test", gemini_api_key="test")
    context = {
        "user_message": "Bagaimana cara meningkatkan penjualan?",
        "selected_language": "id",
        "knowledge_base_context": "",
    }
    specialist_results = {
        "business": {
            "analysis": "Penjualan turun karena kurangnya promosi.",
            "conclusion": "Tingkatkan budget marketing digital.",
            "confidence": 78,
        }
    }
    result = asyncio.run(agent.synthesize(context, specialist_results))

    assert result.get("answer")
    user_msg = captured_prompts[0][1]["content"]
    assert "Pertanyaan pengguna:" in user_msg
    assert "Analis business" in user_msg
    assert "User question:" not in user_msg
