import asyncio

from base import BaseAgent
from uncertainty_engine import UncertaintyEngine


def test_uncertainty_engine_marks_low_confidence_and_prefixes_answer():
    engine = UncertaintyEngine(api_key="test")
    result = asyncio.run(engine.safe_run({
        "final_answer": "Kemungkinan besar masalahnya promosi belum cukup.",
        "confidence_score": 38,
        "verification_passed": False,
        "verification_issues": ["Jawaban terlalu spekulatif"],
        "socratic_review": {
            "risk_if_wrong": "high",
            "needs_clarification": True,
            "missing_information": ["Data traffic", "Data conversion"],
        },
        "devil_advocate_review": {"severity": "high", "overstatement_risk": True},
        "first_principle_analysis": {"root_hypotheses_count": 3, "causal_links_count": 0},
        "retry_count": 1,
    }))

    assert result.success
    assert result.output["band"] == "Low Confidence"
    # should_prefix is always False — internal uncertainty is never shown to users
    assert result.output["should_prefix"] is False
    assert result.output["score"] < 40
    # message is the original answer, never prefixed with "Saya belum cukup yakin"
    assert result.output["message"] == "Kemungkinan besar masalahnya promosi belum cukup."
    joined_reasons = " ".join(result.output["reasons"])
    assert "verifikasi" in joined_reasons or "risiko" in joined_reasons


def test_uncertainty_engine_keeps_high_confidence_when_signals_are_strong():
    engine = UncertaintyEngine(api_key="test")
    result = asyncio.run(engine.safe_run({
        "final_answer": "Ini jawaban yang didukung data.",
        "confidence_score": 92,
        "verification_passed": True,
        "verification_issues": [],
        "socratic_review": {"risk_if_wrong": "low", "needs_clarification": False},
        "devil_advocate_review": {"severity": "none", "overstatement_risk": False},
        "first_principle_analysis": {"root_hypotheses_count": 1, "causal_links_count": 2},
        "retry_count": 0,
    }))

    assert result.success
    assert result.output["band"] == "High Confidence"
    assert result.output["should_prefix"] is False
    assert result.output["message"] == "Ini jawaban yang didukung data."


def test_supervisor_applies_uncertainty_prefix_for_low_confidence(monkeypatch):
    from supervisor import SupervisorAgent

    async def fake_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "Socratic Reasoning Engine" in system:
            return {
                "interpreted_question": "User meminta diagnosis bisnis",
                "user_goal": "Mencari akar masalah",
                "assumptions": ["Konteks terbatas"],
                "ambiguities": ["Data belum lengkap"],
                "available_evidence": ["Pesan pengguna"],
                "missing_information": ["Traffic", "Conversion"],
                "alternative_perspectives": ["Masalah bisa di produk atau channel"],
                "risk_if_wrong": "high",
                "answer_strategy": "Berikan diagnosis sementara dan tandai asumsi",
                "needs_clarification": True,
                "clarifying_questions": ["Berapa traffic sekarang?"],
            }
        if "DevilAdvocateAgent" in system:
            return {
                "needs_revision": False,
                "severity": "high",
                "unsupported_claims": ["Promosi kurang"],
                "missing_evidence": ["Bukti channel lemah"],
                "ignored_weaknesses": ["Produk belum diuji"],
                "counterarguments": ["Demand bisa jadi turun"],
                "competitor_advantages": ["Alternatif lain bisa lebih cocok"],
                "overstatement_risk": True,
                "challenge_questions": ["Berdasarkan apa?"],
                "revision_instructions": ["Turunkan kepastian"],
            }
        if "FirstPrincipleAgent" in system or "first principle" in system.lower():
            return {
                "problem_statement": "Bisnis sepi",
                "fundamental_facts": ["Belum ada data demand"],
                "assumptions": ["Traffic mungkin rendah"],
                "unknowns": ["Harga", "produk", "channel"],
                "root_variables": ["Demand", "Conversion"],
                "causal_links": ["Demand rendah menurunkan penjualan"],
                "root_hypotheses": ["Masalah demand"],
                "disconfirming_tests": ["Cek traffic dan conversion"],
                "priority_investigation": ["Audit demand"],
                "causal_links_count": 1,
                "root_hypotheses_count": 1,
            }
        if "quality checker" in system:
            return {"verified": False, "confidence_score": 35, "issues": ["Masih spekulatif"]}
        return default or {}

    async def fake_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        system = messages[0]["content"] if messages else ""
        if "asisten AI bisnis BotNesia" in system:
            return "Kemungkinan masalahnya promosi kurang."
        if "Kamu adalah editor jawaban konsultan" in system:
            return "{\"answer\": \"Kemungkinan masalahnya promosi kurang.\"}"
        return '{"facts_to_store": [], "summary": "", "forget_keys": []}'

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_llm)

    supervisor = SupervisorAgent(api_key="test")
    result = asyncio.run(supervisor.process({
        "user_message": "Kenapa bisnis saya sepi?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }))

    assert result.uncertainty_band == "Low Confidence"
    # Uncertainty prefix is suppressed — users never see "Saya belum cukup yakin"
    assert "Saya belum cukup yakin" not in result.uncertainty_message
    assert "Saya belum cukup yakin" not in result.final_answer
    assert "uncertainty_engine" in result.agent_results
