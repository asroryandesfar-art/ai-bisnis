import asyncio

from base import BaseAgent
from first_principle_agent import FirstPrincipleAgent, format_first_principle_brief


def test_first_principle_decomposes_business_problem(monkeypatch):
    async def fake_json(self, messages, temperature=0.0, max_tokens=900, default=None):
        return {
            "problem_statement": "Penjualan rendah, penyebab belum diketahui.",
            "fundamental_facts": ["User menyatakan bisnis sepi"],
            "assumptions": ["Promosi kurang"],
            "unknowns": ["Demand", "Conversion rate"],
            "root_variables": ["Kualitas produk", "Demand", "Harga", "Marketing", "Lokasi"],
            "causal_links": [
                {"cause": "Demand rendah", "effect": "Traffic rendah", "confidence": "MEDIUM", "evidence": "Belum ada data"},
                {"cause": "Harga tidak sesuai", "effect": "Conversion rendah", "confidence": "high", "evidence": "Perlu data pembanding"},
            ],
            "root_hypotheses": [
                {"hypothesis": "Masalah awareness", "why_plausible": "Traffic mungkin rendah", "evidence_needed": "Reach dan traffic"},
                {"hypothesis": "Masalah product-market fit", "why_plausible": "Demand belum terbukti", "evidence_needed": "Wawancara dan repeat order"},
            ],
            "disconfirming_tests": ["Jika traffic tinggi tetapi conversion rendah, promosi bukan akar utama"],
            "priority_investigation": ["Ukur demand", "Pisahkan traffic dan conversion"],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    result = asyncio.run(FirstPrincipleAgent(api_key="test").safe_run({"user_message": "Kenapa bisnis saya sepi?"}))

    assert result.success
    assert result.output["causal_links_count"] == 2
    assert result.output["root_hypotheses_count"] == 2
    assert result.output["causal_links"][0]["confidence"] == "medium"
    brief = format_first_principle_brief(result.output)
    for dimension in ("Kualitas produk", "Demand", "Harga", "Marketing", "Lokasi"):
        assert dimension in brief
    assert "Promosi kurang" in brief


def test_first_principle_fallback_is_fail_open(monkeypatch):
    async def unavailable(self, messages, temperature=0.0, max_tokens=900, default=None):
        return {**(default or {}), "_llm_unavailable": True}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", unavailable)
    result = asyncio.run(FirstPrincipleAgent(api_key="test").safe_run({"user_message": "Kenapa bisnis sepi?"}))
    assert result.success
    assert result.output["problem_statement"] == "Kenapa bisnis sepi?"
    assert result.output["causal_links_count"] == 0
    assert "_llm_unavailable" not in result.output


def test_supervisor_runs_first_principle_before_cs(monkeypatch):
    from supervisor import SupervisorAgent

    calls = []

    async def fake_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "Socratic Reasoning Engine" in system:
            calls.append("socratic")
            return default or {}
        if "FirstPrincipleAgent" in system:
            calls.append("first_principle")
            return {
                "problem_statement": "Bisnis sepi dengan penyebab belum diketahui",
                "fundamental_facts": ["Penjualan sepi"],
                "assumptions": ["Promosi kurang"],
                "unknowns": ["Traffic", "Conversion"],
                "root_variables": ["Produk", "Demand", "Harga", "Marketing", "Lokasi"],
                "causal_links": [],
                "root_hypotheses": [],
                "disconfirming_tests": [],
                "priority_investigation": ["Pisahkan traffic dari conversion"],
            }
        if "DevilAdvocateAgent" in system:
            return default or {}
        return default or {}

    async def fake_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        system = messages[0]["content"] if messages else ""
        if "konsultan bisnis AI senior BotNesia" in system:
            calls.append("cs")
            assert "Decomposition first-principles internal" in system
            assert "Demand" in system and "Harga" in system and "Lokasi" in system
            return "Pisahkan dulu apakah masalahnya traffic atau conversion; promosi hanya salah satu hipotesis."
        return '{"facts_to_store": [], "summary": "", "forget_keys": []}'

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_json)
    monkeypatch.setattr(BaseAgent, "_call_llm", fake_llm)
    result = asyncio.run(SupervisorAgent(api_key="test").process({
        "user_message": "Kenapa bisnis saya sepi?", "messages": [],
        "knowledge_base_context": "", "reasoning_mode": "standard",
    }))

    assert calls.index("first_principle") < calls.index("cs")
    assert "first_principle_agent" in result.agent_results
    assert result.first_principle_analysis["root_variables"][1] == "Demand"
    assert "promosi hanya salah satu hipotesis" in result.final_answer


def test_observability_redacts_first_principle_details():
    from agent_observability import _output_summary

    summary = _output_summary({
        "fundamental_facts": ["internal"],
        "assumptions": ["internal"],
        "causal_links": [{"cause": "internal"}],
        "root_hypotheses": [{"hypothesis": "internal"}],
        "causal_links_count": 3,
        "root_hypotheses_count": 2,
    })
    assert summary == {"causal_links_count": 3, "root_hypotheses_count": 2}
