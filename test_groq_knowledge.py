"""
test_groq_knowledge.py — Tes untuk pengetahuan Groq (groq_knowledge.py),
GroqExpertAgent, lensa "groq_expert" di reasoning Pro, dan wiring ke
ReasoningController / supervisor (Universal Knowledge Access Layer).
"""
import asyncio

import groq_knowledge as gk
import knowledge_access_engine as kae
from base import BaseAgent
from groq_expert_agent import GroqExpertAgent
from planner_agent import AVAILABLE_LENSES
from reasoning_agent import ReasoningAgent
from reasoning_controller import ReasoningController


# ─────────────────────────────────────────────────────────────────
# 1) Deteksi pertanyaan Groq
# ─────────────────────────────────────────────────────────────────

def test_looks_like_groq_question_true_cases():
    for q in (
        "Model Groq apa yang paling cepat?",
        "Kenapa saya kena error 429 dari Groq API?",
        "Bagaimana cara pakai tool calling di Groq?",
        "Apa itu reasoning_effort di GPT-OSS?",
    ):
        assert gk.looks_like_groq_question(q), q


def test_looks_like_groq_question_false_for_unrelated():
    assert gk.looks_like_groq_question("Bagaimana cara menghubungkan WhatsApp?") is False
    assert gk.looks_like_groq_question("Apa prioritas saya saat ini?") is False


# ─────────────────────────────────────────────────────────────────
# 2) Topik dokumentasi
# ─────────────────────────────────────────────────────────────────

def test_select_groq_topics_rate_limit():
    assert "rate_limits" in gk.select_groq_topics("Kena 429 rate limit terus di Groq")


def test_select_groq_topics_errors():
    assert "errors" in gk.select_groq_topics("Apa arti error 503 dari Groq API?")


def test_select_groq_topics_tool_use():
    assert "tool_use" in gk.select_groq_topics("Bagaimana implementasi tool calling di Groq?")


def test_select_groq_topics_reasoning():
    assert "reasoning" in gk.select_groq_topics("Apa itu reasoning_effort di model GPT-OSS?")


def test_select_groq_topics_default_models():
    assert gk.select_groq_topics("Model Groq apa yang bagus?") == ["models"]


# ─────────────────────────────────────────────────────────────────
# 3) build_groq_context
# ─────────────────────────────────────────────────────────────────

def test_build_groq_context_empty_for_unrelated_question():
    assert gk.build_groq_context("Bagaimana cara menghubungkan WhatsApp?") == ""


def test_build_groq_context_includes_relevant_topic_and_models():
    ctx = gk.build_groq_context("Kena error 429 rate limit di Groq, kenapa?")
    assert "Rate Limit" in ctx
    assert "Katalog Model" in ctx


def test_build_groq_context_includes_model_catalog_for_model_question():
    ctx = gk.build_groq_context("Model Groq apa yang paling cepat untuk customer service?")
    assert "llama-3.1-8b-instant" in ctx
    assert "llama-3.3-70b-versatile" in ctx


# ─────────────────────────────────────────────────────────────────
# 4) Katalog model & recommend_model
# ─────────────────────────────────────────────────────────────────

def test_model_catalog_entries_have_required_fields():
    for m in gk.MODEL_CATALOG:
        for key in ("id", "developer", "speed_tier", "cost_tier", "best_for", "notes"):
            assert key in m, m


def test_recommend_model_speed():
    rec = gk.recommend_model("speed")
    assert rec["recommended"]["id"] == "llama-3.1-8b-instant"
    assert rec["note"] == ""


def test_recommend_model_reasoning():
    rec = gk.recommend_model("reasoning")
    assert rec["recommended"]["id"] == "openai/gpt-oss-120b"


def test_recommend_model_customer_service():
    rec = gk.recommend_model("customer_service")
    assert rec["recommended"]["id"] == "llama-3.3-70b-versatile"


def test_recommend_model_coding():
    rec = gk.recommend_model("coding")
    assert "coding" in rec["recommended"]["best_for"]


def test_recommend_model_cost():
    rec = gk.recommend_model("cost")
    assert rec["recommended"]["id"] == "llama-3.1-8b-instant"


def test_recommend_model_unknown_use_case():
    rec = gk.recommend_model("rocket_science")
    assert rec["recommended"] is None
    assert "tidak dikenali" in rec["note"]


# ─────────────────────────────────────────────────────────────────
# 5) GroqExpertAgent
# ─────────────────────────────────────────────────────────────────

def test_groq_expert_agent_skips_non_groq_question():
    agent = GroqExpertAgent()
    result = asyncio.run(agent.run({"user_message": "Apa prioritas saya saat ini?"}))
    assert result.output["skipped"] is True
    assert result.output["reason"] == "not_groq_question"


def test_groq_expert_agent_answers_groq_question(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        assert "Groq" in messages[1]["content"]
        return {
            "analysis": "Untuk customer service, llama-3.3-70b-versatile paling seimbang.",
            "conclusion": "Gunakan llama-3.3-70b-versatile.",
            "confidence": 90,
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = GroqExpertAgent()
    result = asyncio.run(agent.run({"user_message": "Model Groq apa yang cocok untuk customer service?"}))
    assert "llama-3.3-70b-versatile" in result.output["analysis"]
    assert result.output["confidence"] == 90


def test_groq_expert_agent_recommend_model_passthrough():
    agent = GroqExpertAgent()
    rec = agent.recommend_model("speed")
    assert rec["recommended"]["id"] == "llama-3.1-8b-instant"


# ─────────────────────────────────────────────────────────────────
# 6) Lensa "groq_expert" di reasoning_agent / planner_agent
# ─────────────────────────────────────────────────────────────────

def test_groq_expert_lens_registered_in_planner():
    assert "groq_expert" in AVAILABLE_LENSES


def test_groq_expert_lens_skips_non_groq_question():
    agent = ReasoningAgent()
    result = asyncio.run(agent.run_lens("groq_expert", {"user_message": "Apa prioritas saya saat ini?"}))
    assert result.output["skipped"] is True


def test_groq_expert_lens_returns_analysis_for_groq_question(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return {
            "analysis": "openai/gpt-oss-120b cocok untuk reasoning kompleks.",
            "conclusion": "Gunakan openai/gpt-oss-120b.",
            "confidence": 85,
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = ReasoningAgent()
    result = asyncio.run(
        agent.run_lens("groq_expert", {"user_message": "Model Groq apa yang terbaik untuk reasoning?"})
    )
    assert result.agent == "reasoning_agent:groq_expert"
    assert result.output["lens"] == "groq_expert"
    assert "gpt-oss-120b" in result.output["analysis"]


# ─────────────────────────────────────────────────────────────────
# 7) knowledge_access_engine / reasoning_controller wiring
# ─────────────────────────────────────────────────────────────────

def test_select_knowledge_sources_detects_groq_question():
    routing = kae.select_knowledge_sources("Model Groq apa yang paling hemat?", [])
    assert "self_knowledge:groq_docs" in routing["reasons"]


def test_reasoning_controller_knowledge_routing_for_groq_question():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Kena error 429 dari Groq, gimana cara fix?", "messages": []})
    assert "self_knowledge:groq_docs" in brief["knowledge_routing"]["reasons"]


# ─────────────────────────────────────────────────────────────────
# 8) Supervisor integration — STEP 0.3 injects Groq context
# ─────────────────────────────────────────────────────────────────

async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def test_supervisor_injects_groq_context_for_groq_question(monkeypatch):
    captured: dict = {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        captured["system"] = messages[0]["content"]
        return "Rekomendasi model Groq."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Model Groq apa yang paling cepat untuk customer service?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_brief["knowledge_routing"]["reasons"].get("self_knowledge:groq_docs")
    assert "llama-3.1-8b-instant" in captured["system"]
    assert "GroqExpertAgent" in captured["system"]
