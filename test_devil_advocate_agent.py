import asyncio

from base import BaseAgent
from devil_advocate_agent import DevilAdvocateAgent, format_devil_critique


def test_devil_advocate_normalizes_material_critique(monkeypatch):
    async def fake_json(self, messages, temperature=0.0, max_tokens=700, default=None):
        return {
            "needs_revision": True,
            "severity": "HIGH",
            "unsupported_claims": ["BotNesia pasti lebih baik"],
            "missing_evidence": ["Benchmark independen"],
            "ignored_weaknesses": ["Biaya integrasi"],
            "counterarguments": ["Produk lain mungkin lebih matang"],
            "competitor_advantages": ["Alternatif bisa unggul untuk kebutuhan enterprise tertentu"],
            "overstatement_risk": True,
            "challenge_questions": ["Berdasarkan apa?", "Apa buktinya?"],
            "revision_instructions": ["Ubah klaim absolut menjadi perbandingan bersyarat"],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    result = asyncio.run(DevilAdvocateAgent(api_key="test").safe_run({
        "user_message": "Apakah BotNesia terbaik?",
        "bot_response": "BotNesia pasti lebih baik.",
    }))

    assert result.success
    assert result.output["severity"] == "high"
    assert result.output["needs_revision"] is True
    assert result.output["overstatement_risk"] is True
    assert "Benchmark" in format_devil_critique(result.output)


def test_devil_advocate_none_severity_does_not_force_revision():
    critique = DevilAdvocateAgent._normalize({"severity": "none", "needs_revision": True})
    assert critique["needs_revision"] is False


def test_supervisor_revises_marketing_claim_once(monkeypatch):
    from supervisor import SupervisorAgent

    calls = {"draft": 0, "revision": 0, "devil": 0}

    async def fake_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "Socratic Reasoning Engine" in system:
            return default or {}
        if "DevilAdvocateAgent" in system:
            calls["devil"] += 1
            return {
                "needs_revision": True,
                "severity": "high",
                "unsupported_claims": ["Klaim terbaik tanpa benchmark"],
                "missing_evidence": ["Perbandingan independen"],
                "ignored_weaknesses": ["Trade-off implementasi"],
                "counterarguments": ["Alternatif bisa lebih cocok"],
                "competitor_advantages": ["Kompetitor mungkin unggul untuk kebutuhan tertentu"],
                "overstatement_risk": True,
                "challenge_questions": ["Berdasarkan apa?"],
                "revision_instructions": ["Jadikan klaim bersyarat"],
            }
        if "editor jawaban konsultan" in system:
            calls["revision"] += 1
            return {"answer": "BotNesia dapat lebih cocok untuk kebutuhan tertentu, tetapi perlu dibandingkan berdasarkan fitur, biaya, dan implementasi."}
        return default or {}

    async def fake_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        system = messages[0]["content"] if messages else ""
        if "asisten AI bisnis BotNesia" in system:
            calls["draft"] += 1
            return "BotNesia pasti lebih baik daripada semua kompetitor."
        return '{"facts_to_store": [], "summary": "", "forget_keys": []}'

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_llm)
    result = asyncio.run(SupervisorAgent(api_key="test").process({
        # heuristic_complexity() must classify this as "complex" so the
        # Devil's-Advocate gate (supervisor.py STEP 0.26, performance fix)
        # doesn't skip it — a bare "Apakah BotNesia lebih baik?" now counts
        # as "simple" and would bypass this engine entirely.
        "user_message": "Bandingkan BotNesia dengan kompetitor, apakah BotNesia lebih baik?",
        "messages": [],
        "knowledge_base_context": "", "reasoning_mode": "standard",
    }))

    assert calls == {"draft": 1, "revision": 1, "devil": 1}
    assert result.devil_revision_applied is True
    assert result.devil_advocate_review["severity"] == "high"
    assert "dapat lebih cocok" in result.final_answer
    assert "DevilAdvocate" not in result.final_answer
    assert "devil_advocate_agent" in result.agent_results
    assert "cs_agent:devil_revision" in result.agent_results


def test_observability_redacts_detailed_devil_critique():
    from agent_observability import _output_summary

    summary = _output_summary({
        "unsupported_claims": ["internal"],
        "counterarguments": ["internal"],
        "revision_instructions": ["internal"],
        "severity": "high",
        "needs_revision": True,
        "overstatement_risk": True,
    })
    assert summary == {"severity": "high", "needs_revision": True, "overstatement_risk": True}
