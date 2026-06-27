import asyncio

from base import BaseAgent
from cs_agent import CSAgent
from finance_fetcher import CryptoQuote
from planner_agent import AVAILABLE_LENSES, PlannerAgent
from reasoning_agent import ReasoningAgent
from verification_agent import VerificationAgent
import reasoning_agent as reasoning_agent_module


def test_planner_filters_invalid_lenses(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.1, max_tokens=200, default=None):
        return {
            "agents_to_invoke": ["market_technical", "invalid_lens", "risk"],
            "execution_strategy": "parallel",
            "synthesis_focus": "fokus penurunan harga",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    planner = PlannerAgent(api_key="test-key")
    result = asyncio.run(planner.plan({"user_message": "test"}))

    assert result["agents_to_invoke"] == ["market_technical", "risk"]
    assert all(a in AVAILABLE_LENSES for a in result["agents_to_invoke"])


def test_planner_falls_back_to_default_when_no_valid_lenses(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.1, max_tokens=200, default=None):
        return {"agents_to_invoke": ["bogus"], "execution_strategy": "parallel", "synthesis_focus": ""}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    planner = PlannerAgent(api_key="test-key")
    result = asyncio.run(planner.plan({"user_message": "test"}))

    assert result["agents_to_invoke"] == ["market_technical"]


def _patch_market_fetchers(monkeypatch):
    async def fake_fetch_crypto_quotes(query, timeout_s=15.0):
        return [
            CryptoQuote(
                coin_id="bitcoin", symbol="BTC", usd=59000.0, idr=900000000.0,
                usd_24h_change=-12.5, idr_24h_change=-12.5,
                fetched_at="2026-01-01T00:00:00+00:00",
            )
        ]

    async def fake_fetch_stock_quotes(query, timeout_s=15.0):
        return []

    monkeypatch.setattr(reasoning_agent_module, "fetch_crypto_quotes", fake_fetch_crypto_quotes)
    monkeypatch.setattr(reasoning_agent_module, "fetch_stock_quotes", fake_fetch_stock_quotes)


def test_run_lens_market_technical(monkeypatch):
    _patch_market_fetchers(monkeypatch)

    captured = {}

    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=400, default=None):
        captured["messages"] = messages
        return {
            "analysis": "BTC turun tajam 12.5% dalam 24 jam akibat tekanan jual besar.",
            "conclusion": "Tren bearish jangka pendek dengan support di 55k.",
            "confidence": 70,
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = ReasoningAgent(api_key="test-key")
    ctx = {"user_message": "Kenapa BTC turun dari 70k ke 59k?"}
    result = asyncio.run(agent.run_lens("market_technical", ctx))

    assert result.success
    assert not result.output.get("skipped")
    assert result.output["conclusion"] == "Tren bearish jangka pendek dengan support di 55k."
    assert result.output["confidence"] == 70

    prompt_text = captured["messages"][-1]["content"]
    assert "BTC" in prompt_text
    assert "59,000" in prompt_text


def test_run_lens_market_technical_skips_when_not_market_query(monkeypatch):
    _patch_market_fetchers(monkeypatch)

    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=400, default=None):
        raise AssertionError("LLM should not be called when there is no market data")

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = ReasoningAgent(api_key="test-key")
    ctx = {"user_message": "Bagaimana cara menghubungkan WhatsApp ke BotNesia?"}
    result = asyncio.run(agent.run_lens("market_technical", ctx))

    assert result.success
    assert result.output.get("skipped") is True
    assert result.output["reason"] == "no_data_available"


def test_synthesize_combines_specialist_outputs(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=1400, default=None):
        return {
            "answer": "BTC turun karena tekanan jual besar dan sentimen negatif, dengan support di 55k.",
            "confidence_score": 72,
            "topics": ["BTC", "market"],
            "suggested_followup": "Mau analisis risiko lebih lanjut?",
            "reasoning_summary": "Kombinasi analisis teknikal dan sentimen.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = CSAgent(api_key="test-key")
    specialist_results = {
        "market_technical": {"analysis": "Harga turun 15% dalam 24 jam.", "conclusion": "Tren bearish.", "confidence": 70},
        "sentiment": {"analysis": "Berita negatif mendominasi.", "conclusion": "Sentimen negatif.", "confidence": 65},
        "risk": {"skipped": True, "reason": "no_cross_context"},
    }
    result = asyncio.run(agent.synthesize({"user_message": "Kenapa BTC turun?"}, specialist_results))

    assert "turun" in result["answer"]
    assert result["confidence_score"] == 72
    assert result["topics"] == ["BTC", "market"]


def _fake_call_llm_dispatch(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
    system = messages[0]["content"] if messages else ""
    if "asisten AI bisnis BotNesia" in system:
        return "Halo! Untuk informasi harga paket, silakan cek halaman pricing kami."
    return '{"facts_to_store": [], "summary": "", "forget_keys": []}'


async def _fake_call_llm_dispatch_async(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
    return _fake_call_llm_dispatch(self, messages, temperature, max_tokens, response_format)


def test_supervisor_pro_mode_complex_query(monkeypatch):
    from supervisor import SupervisorAgent

    _patch_market_fetchers(monkeypatch)

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "perencana tim analis" in system:
            return {
                "agents_to_invoke": ["market_technical"],
                "execution_strategy": "parallel",
                "synthesis_focus": "Fokus pada penyebab penurunan harga BTC",
            }
        if "analis pasar teknikal" in system:
            return {
                "analysis": "BTC turun 12.5% dalam 24 jam akibat tekanan jual besar.",
                "conclusion": "Tren bearish jangka pendek dengan support di 55k.",
                "confidence": 70,
            }
        if "konsultan" in system and ("eksekutif" in system or "McKinsey" in system or "executive" in system.lower()):
            return {
                "answer": "BTC turun dari 70k ke 59k karena tekanan jual besar dan sentimen pasar negatif.",
                "confidence_score": 72,
                "topics": ["BTC"],
                "suggested_followup": "Mau analisis risiko lebih lanjut?",
                "reasoning_summary": "Analisis teknikal menunjukkan tren bearish jangka pendek.",
            }
        if "quality checker" in system:
            return {"verified": True, "confidence_score": 88, "issues": []}
        return default or {}

    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    supervisor = SupervisorAgent(api_key="test-key")
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Kenapa BTC turun dari 70k ke 59k?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "pro",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_mode_used == "pro"
    assert result.confidence_score == 80
    assert result.plan["agents_to_invoke"] == ["market_technical"]
    assert "market_technical" in result.specialist_results
    assert result.specialist_results["market_technical"]["conclusion"] == (
        "Tren bearish jangka pendek dengan support di 55k."
    )
    assert "BTC turun dari 70k" in result.final_answer
    assert "reasoning_agent:market_technical" in result.agent_results
    assert "planner_agent" in result.agent_results
    assert result.verification_passed is True
    assert result.retry_count == 0
    assert "verification_agent" in result.agent_results


def test_supervisor_pro_mode_simple_query_skips_pipeline(monkeypatch):
    from supervisor import SupervisorAgent

    call_count = {"json": 0}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        call_count["json"] += 1
        return default or {}

    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    supervisor = SupervisorAgent(api_key="test-key")
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Halo, harga paket berapa?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "pro",
    }
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_mode_used == "standard"
    assert result.plan is None
    # "Halo, harga paket berapa?" is also heuristic_complexity()=="simple", so
    # the Socratic/First-Principle/Devil's-Advocate deep-reasoning engines are
    # now skipped too (performance optimization: these used to run
    # unconditionally on every turn, adding ~13s+ of sequential LLM calls to
    # trivial messages) — zero extra JSON calls, not 3.
    assert call_count["json"] == 0
    assert "socratic_reasoning_engine" in result.agent_results
    assert "first_principle_agent" in result.agent_results
    assert "devil_advocate_agent" in result.agent_results


def test_verification_flags_shallow_answer(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.0, max_tokens=300, default=None):
        return {
            "verified": False,
            "confidence_score": 30,
            "issues": ["Jawaban terlalu pendek dan tidak menjawab pertanyaan."],
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = VerificationAgent(api_key="test-key")
    result = asyncio.run(agent.verify({"user_message": "Kenapa BTC turun?"}, "Tidak tahu.", {}))

    assert result["verified"] is False
    assert result["confidence_score"] == 30
    assert "pendek" in result["issues"][0]


_BTC_CONTEXT = {
    "bot_id": "bot-1",
    "org_id": "org-1",
    "conversation_id": "conv-1",
    "user_message": "Kenapa BTC turun dari 70k ke 59k?",
    "messages": [],
    "knowledge_base_context": "",
    "reasoning_mode": "pro",
}


def test_supervisor_pro_mode_retry_loop_stops_at_max_retries(monkeypatch):
    from supervisor import SupervisorAgent, MAX_RETRIES

    _patch_market_fetchers(monkeypatch)

    synth_calls = {"n": 0}
    verify_calls = {"n": 0}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "perencana tim analis" in system:
            return {"agents_to_invoke": ["market_technical"], "execution_strategy": "parallel", "synthesis_focus": "fokus"}
        if "analis pasar teknikal" in system:
            return {"analysis": "Analisis pasar.", "conclusion": "Tren bearish.", "confidence": 60}
        if "konsultan" in system and ("eksekutif" in system or "McKinsey" in system or "executive" in system.lower()):
            synth_calls["n"] += 1
            return {
                "answer": f"Jawaban versi {synth_calls['n']}.",
                "confidence_score": 50,
                "topics": [], "suggested_followup": None, "reasoning_summary": "",
            }
        if "quality checker" in system:
            verify_calls["n"] += 1
            return {"verified": False, "confidence_score": 40, "issues": ["Jawaban terlalu dangkal."]}
        return default or {}

    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_BTC_CONTEXT)))

    assert result.retry_count == MAX_RETRIES
    assert result.verification_passed is False
    assert synth_calls["n"] == MAX_RETRIES + 1
    assert verify_calls["n"] == MAX_RETRIES + 1
    assert result.uncertainty_band == "Low Confidence"
    # Uncertainty prefix is suppressed — users never see internal confidence disclaimers
    assert "Saya belum cukup yakin" not in result.final_answer
    assert f"Jawaban versi {MAX_RETRIES + 1}." in result.final_answer


def test_supervisor_pro_mode_retry_loop_stops_when_verified(monkeypatch):
    from supervisor import SupervisorAgent

    _patch_market_fetchers(monkeypatch)

    synth_calls = {"n": 0}
    verify_calls = {"n": 0}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "perencana tim analis" in system:
            return {"agents_to_invoke": ["market_technical"], "execution_strategy": "parallel", "synthesis_focus": "fokus"}
        if "analis pasar teknikal" in system:
            return {"analysis": "Analisis pasar.", "conclusion": "Tren bearish.", "confidence": 60}
        if "konsultan" in system and ("eksekutif" in system or "McKinsey" in system or "executive" in system.lower()):
            synth_calls["n"] += 1
            return {
                "answer": f"Jawaban versi {synth_calls['n']}.",
                "confidence_score": 50,
                "topics": [], "suggested_followup": None, "reasoning_summary": "",
            }
        if "quality checker" in system:
            verify_calls["n"] += 1
            if verify_calls["n"] >= 2:
                return {"verified": True, "confidence_score": 80, "issues": []}
            return {"verified": False, "confidence_score": 40, "issues": ["Kurang mendalam."]}
        return default or {}

    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_BTC_CONTEXT)))

    assert result.retry_count == 1
    assert result.verification_passed is True
    assert synth_calls["n"] == 2
    assert verify_calls["n"] == 2
    assert result.final_answer == "Jawaban versi 2."


def test_risk_lens_receives_cross_context_from_other_lenses(monkeypatch):
    from supervisor import SupervisorAgent

    _patch_market_fetchers(monkeypatch)

    captured = {}

    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "perencana tim analis" in system:
            return {
                "agents_to_invoke": ["market_technical", "risk"],
                "execution_strategy": "parallel",
                "synthesis_focus": "fokus",
            }
        if "analis pasar teknikal" in system:
            return {"analysis": "Analisis pasar.", "conclusion": "Tren bearish jangka pendek.", "confidence": 60}
        if "analis risiko" in system:
            captured["messages"] = messages
            return {"analysis": "Risiko utama adalah volatilitas tinggi.", "conclusion": "Waspadai volatilitas lanjutan.", "confidence": 55}
        if "konsultan" in system and ("eksekutif" in system or "McKinsey" in system or "executive" in system.lower()):
            return {"answer": "Jawaban lengkap.", "confidence_score": 70, "topics": [], "suggested_followup": None, "reasoning_summary": ""}
        if "quality checker" in system:
            return {"verified": True, "confidence_score": 70, "issues": []}
        return default or {}

    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_BTC_CONTEXT)))

    assert "risk" in result.specialist_results
    assert result.specialist_results["risk"]["conclusion"] == "Waspadai volatilitas lanjutan."
    prompt_text = captured["messages"][-1]["content"]
    assert "Tren bearish jangka pendek." in prompt_text


def test_persist_intelligence_includes_reasoning_metrics(monkeypatch):
    from intelligence import pipeline
    from supervisor import SupervisorResult

    result = SupervisorResult(
        final_answer="x", confidence=0.7, topics=[], suggested_followup=None,
        should_escalate=False, escalation_urgency="low", escalation_reason=None,
        escalation_message=None, recommended_team=None,
        sentiment={"label": "neutral", "score": 0.0}, intent="unknown",
        bot_quality_score=0.7, friction_points=[], product_insights=[], conversation_summary="",
        trainer_score=0.0, improved_response=None, training_examples=[], prompt_suggestions=[],
        faq_match=None, sales_signals=[], sales_has_objection=False, sales_recommended_angle=None,
        kg_product_mentions=[], agent_results={}, total_latency_ms=100, errors=[],
        reasoning_mode_used="pro", confidence_score=72, verification_passed=True, retry_count=1,
        plan={"agents_to_invoke": ["market_technical"]}, specialist_results={"market_technical": {}},
        verification_issues=[], uncertainty_band="Low Confidence", uncertainty_score=41,
        uncertainty_reasons=["verifikasi belum lolos"], uncertainty_message="Saya belum cukup yakin.",
    )

    captured = {}

    async def fake_persist_conversation(context, **kwargs):
        captured["extra_metrics"] = kwargs.get("extra_metrics")
        return {}

    monkeypatch.setattr(pipeline.conversation_memory, "persist_conversation", fake_persist_conversation)

    context = {"bot_id": "bot-1", "org_id": "org-1", "conversation_id": "conv-1", "user_message": "x", "messages": []}
    asyncio.run(pipeline.persist_intelligence(context, result, bot_response="x"))

    extra = captured["extra_metrics"]
    assert extra["reasoning_mode_used"] == "pro"
    assert extra["confidence_score"] == 72
    assert extra["verification_passed"] is True
    assert extra["retry_count"] == 1
    assert extra["plan"] == {"agents_to_invoke": ["market_technical"]}
    assert extra["specialist_lenses_used"] == ["market_technical"]
    assert extra["uncertainty_band"] == "Low Confidence"
    assert extra["uncertainty_score"] == 41
    assert extra["uncertainty_reasons"] == ["verifikasi belum lolos"]
