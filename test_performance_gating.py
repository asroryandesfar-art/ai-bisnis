"""
Performance Optimization (Production Readiness Phase, section 7): the
Socratic/First-Principle/Devil's-Advocate reasoning engines used to run
unconditionally on EVERY chat turn, each making its own sequential Groq
call (plus a 4th call if Devil's-Advocate requested a revision) — measured
live, this pushed simple factual/greeting questions ("Apa itu Bitcoin?",
"Halo, apa kabar?") to 13-30 seconds, far past the < 3s target.

supervisor.py STEP 0.26 now gates these 3 engines behind the existing
heuristic_complexity() (intent_classifier.py, originally built to decide
pro vs standard mode but unused for this) — skip them when the message is
unambiguously "simple", keep running them in full for "complex"/ambiguous
messages. No feature removed: the engines still exist, still run for
questions that warrant them.
"""
import asyncio

from base import BaseAgent
from supervisor import SupervisorAgent


def test_simple_message_skips_deep_reasoning_engines(monkeypatch):
    call_count = {"json": 0}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        call_count["json"] += 1
        return default or {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Jawaban singkat."

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    result = asyncio.run(SupervisorAgent(api_key="test").process({
        "user_message": "Apa itu Bitcoin?", "messages": [],
        "knowledge_base_context": "", "reasoning_mode": "standard",
    }))

    assert call_count["json"] == 0
    assert result.socratic_review == {}
    assert result.first_principle_analysis == {}
    assert result.devil_advocate_review == {}
    assert result.devil_revision_applied is False
    # Stub results still present in agent_results (key always exists), just
    # with empty output — downstream code reading these dicts never KeyErrors.
    assert result.agent_results["socratic_reasoning_engine"].output == {}
    assert result.agent_results["first_principle_agent"].output == {}
    assert result.agent_results["devil_advocate_agent"].output == {}


def test_complex_message_still_runs_deep_reasoning_engines(monkeypatch):
    call_count = {"json": 0}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        call_count["json"] += 1
        return default or {}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Jawaban panjang dengan analisis."

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    result = asyncio.run(SupervisorAgent(api_key="test").process({
        "user_message": "Kenapa penjualan saya turun bulan ini dan bagaimana cara meningkatkannya?",
        "messages": [],
        "knowledge_base_context": "", "reasoning_mode": "standard",
    }))

    # Socratic + First-Principle (+ memory write skipped for anonymous user)
    # both ran -> at least 2 _call_llm_json calls happened.
    assert call_count["json"] >= 2
    assert "socratic_reasoning_engine" in result.agent_results
    assert "first_principle_agent" in result.agent_results
