import asyncio

from base import BaseAgent
from socratic_reasoning import SocraticReasoningEngine, format_socratic_brief


def test_socratic_engine_normalizes_structured_review(monkeypatch):
    async def fake_json(self, messages, temperature=0.1, max_tokens=700, default=None):
        return {
            "interpreted_question": "User meminta strategi menaikkan penjualan.",
            "user_goal": "Mendapat prioritas tindakan.",
            "assumptions": ["Data penjualan belum diberikan"],
            "ambiguities": ["Periode target belum jelas"],
            "available_evidence": ["Pertanyaan pengguna"],
            "missing_information": ["Baseline revenue", "Channel utama"],
            "alternative_perspectives": ["Masalah bisa berasal dari traffic atau conversion"],
            "risk_if_wrong": "HIGH",
            "answer_strategy": "Pisahkan diagnosis traffic dan conversion, lalu beri langkah awal.",
            "needs_clarification": True,
            "clarifying_questions": ["Berapa baseline revenue?", "Channel apa yang dominan?", "Pertanyaan ketiga dibuang"],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    result = asyncio.run(SocraticReasoningEngine(api_key="test").safe_run({"user_message": "Bagaimana menaikkan penjualan?"}))

    assert result.success
    assert result.output["risk_if_wrong"] == "high"
    assert result.output["needs_clarification"] is True
    assert len(result.output["clarifying_questions"]) == 2
    assert "traffic" in format_socratic_brief(result.output)


def test_socratic_engine_fallback_is_fail_open(monkeypatch):
    async def unavailable(self, messages, temperature=0.1, max_tokens=700, default=None):
        return {**(default or {}), "_llm_unavailable": True}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", unavailable)
    result = asyncio.run(SocraticReasoningEngine(api_key="test").safe_run({"user_message": "Apa risikonya?"}))

    assert result.success
    assert result.output["interpreted_question"] == "Apa risikonya?"
    assert "_llm_unavailable" not in result.output


def test_supervisor_runs_socratic_before_cs_and_keeps_review_internal(monkeypatch):
    from supervisor import SupervisorAgent

    calls = []

    async def fake_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "Socratic Reasoning Engine" in system:
            calls.append("socratic")
            return {
                "interpreted_question": "User meminta rekomendasi.",
                "user_goal": "Mendapat keputusan yang aman.",
                "assumptions": ["Konteks terbatas"],
                "ambiguities": [],
                "available_evidence": ["Pesan user"],
                "missing_information": ["Anggaran"],
                "alternative_perspectives": ["Ada opsi bertahap"],
                "risk_if_wrong": "medium",
                "answer_strategy": "Berikan opsi bertahap dan tandai asumsi.",
                "needs_clarification": True,
                "clarifying_questions": ["Berapa anggarannya?"],
            }
        return default or {}

    async def fake_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        system = messages[0]["content"] if messages else ""
        if "konsultan bisnis AI senior BotNesia" in system:
            calls.append("cs")
            assert "Brief Socratic internal" in system
            return "Dengan asumsi konteks masih terbatas, mulai dari opsi bertahap. Berapa anggaran Anda?"
        return '{"facts_to_store": [], "summary": "", "forget_keys": []}'

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_llm)
    supervisor = SupervisorAgent(api_key="test")
    result = asyncio.run(supervisor.process({
        # heuristic_complexity() must classify this as "complex" so the
        # Socratic gate (supervisor.py STEP 0.26, performance fix) doesn't
        # skip it — a bare "Berikan rekomendasi terbaik." now counts as
        # "simple" and would bypass this engine entirely.
        "user_message": "Bandingkan opsi yang ada dan berikan rekomendasi terbaik untuk bisnis saya.",
        "messages": [],
        "knowledge_base_context": "", "reasoning_mode": "standard",
    }))

    assert calls.index("socratic") < calls.index("cs")
    assert result.socratic_review["risk_if_wrong"] == "medium"
    assert "socratic_reasoning_engine" in result.agent_results
    assert "Brief Socratic internal" not in result.final_answer


def test_observability_redacts_detailed_socratic_review():
    from agent_observability import _output_summary

    summary = _output_summary({
        "interpreted_question": "detail internal",
        "assumptions": ["asumsi internal"],
        "clarifying_questions": ["pertanyaan internal"],
        "risk_if_wrong": "high",
        "needs_clarification": True,
    })

    assert summary == {"risk_if_wrong": "high", "needs_clarification": True}
