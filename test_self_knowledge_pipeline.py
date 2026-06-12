"""
test_self_knowledge_pipeline.py — Tests untuk Phase 5 (self-knowledge, lensa
self_knowledge/business, AnswerQualityScorer, dan context memory).

Semua tes memakai pola mock _call_llm/_call_llm_json yang sama dengan
test_reasoning_pipeline.py — tidak ada panggilan Groq sungguhan.
"""
import asyncio
import json

from base import BaseAgent
import botnesia_knowledge as bk
from intent_classifier import heuristic_complexity
from memory_agent import MemoryAgent, MemoryStore
import memory_agent as memory_agent_module
from planner_agent import AVAILABLE_LENSES
from reasoning_agent import ReasoningAgent


# ─── Fixtures palsu ────────────────────────────────────────────

class _FakePool:
    """Pool asyncpg palsu untuk botnesia_knowledge.*."""

    def __init__(self, plan_rows=None, business_stats=None, topic_rows=None,
                 friction_rows=None, insight_rows=None, fail=False):
        self.plan_rows = plan_rows or []
        self.business_stats = business_stats
        self.topic_rows = topic_rows or []
        self.friction_rows = friction_rows or []
        self.insight_rows = insight_rows or []
        self.fail = fail

    async def fetch(self, query, *args):
        if self.fail:
            raise RuntimeError("db down")
        q = " ".join(query.split())
        if "FROM plans" in q:
            return self.plan_rows
        if "unnest(topics)" in q:
            return self.topic_rows
        if "friction_points" in q:
            return self.friction_rows
        if "product_insights" in q:
            return self.insight_rows
        return []

    async def fetchrow(self, query, *args):
        if self.fail:
            raise RuntimeError("db down")
        return self.business_stats


def _patch_billing(monkeypatch, sub, usage, channels):
    async def fake_sub(pool, org_id):
        return sub

    async def fake_usage(pool, org_id):
        return usage

    async def fake_channels(pool, org_id):
        return channels

    monkeypatch.setattr(bk, "get_active_subscription", fake_sub)
    monkeypatch.setattr(bk, "current_usage", fake_usage)
    monkeypatch.setattr(bk, "list_channel_accounts", fake_channels)


# ─── 1. botnesia_knowledge ─────────────────────────────────────

def test_build_self_knowledge_context_includes_sections(monkeypatch):
    sub = {
        "plan_name": "Pro", "plan_key": "pro", "status": "active",
        "current_period_end": "2026-07-01", "trial_ends_at": None,
        "max_conversations_per_month": 1000, "max_agents": 3, "max_users": 5,
        "max_knowledge_docs": 20, "max_channels": 3,
    }
    usage = {"conversations": 120, "agents": 1, "users": 1, "knowledge": 2, "channels": 1}
    channels = [
        {"channel_type": "whatsapp", "display_name": "Toko Saya", "is_active": True, "connected_at": "2026-01-01"},
        {"channel_type": "instagram", "display_name": "Toko IG", "is_active": False, "connected_at": "2026-02-01"},
    ]
    _patch_billing(monkeypatch, sub, usage, channels)

    plan_rows = [
        {"key": "free", "name": "Free", "price_monthly_idr": 0,
         "max_conversations_per_month": 100, "max_agents": 1, "max_users": 1,
         "max_knowledge_docs": 3, "max_channels": 1, "features": "{}"},
        {"key": "pro", "name": "Pro", "price_monthly_idr": 299000,
         "max_conversations_per_month": 1000, "max_agents": 3, "max_users": 5,
         "max_knowledge_docs": 20, "max_channels": 3,
         "features": json.dumps({"highlights": ["Reasoning Mode Pro", "Priority support"]})},
    ]
    pool = _FakePool(plan_rows=plan_rows)

    bot_row = {"reasoning_mode": "pro", "billing_status": "active"}
    ctx = asyncio.run(bk.build_self_knowledge_context(pool, "org-1", "bot-1", bot_row))

    assert "## Tentang BotNesia" in ctx
    assert "## Akun & Paket Anda" in ctx
    assert "Pro" in ctx
    assert "120 / 1000" in ctx
    assert "## Channel Terhubung" in ctx
    assert "WhatsApp" in ctx and "aktif" in ctx
    assert "Instagram" in ctx and "nonaktif" in ctx
    assert "## Perbandingan Paket" in ctx
    assert "Reasoning Mode Pro" in ctx


def test_build_self_knowledge_context_degrades_to_empty_on_db_error(monkeypatch):
    async def fake_sub(pool, org_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(bk, "get_active_subscription", fake_sub)
    pool = _FakePool()
    ctx = asyncio.run(bk.build_self_knowledge_context(pool, "org-1", "bot-1", {}))
    assert ctx == ""


def test_build_business_context_with_data():
    pool = _FakePool(
        business_stats={
            "total": 42, "avg_sentiment": 0.3, "resolved": 20, "unresolved": 10,
            "abandoned": 5, "escalated": 7, "leads": 12,
        },
        topic_rows=[{"topic": "pengiriman", "n": 10}],
        friction_rows=[{"friction": "respon lambat", "n": 5}],
        insight_rows=[{"insight": "minat ke produk B", "n": 3}],
    )
    ctx = asyncio.run(bk.build_business_context(pool, "org-1", "bot-1"))

    assert "## Ringkasan Performa Bisnis" in ctx
    assert "42" in ctx
    assert "pengiriman" in ctx
    assert "respon lambat" in ctx
    assert "minat ke produk B" in ctx


def test_build_business_context_no_data_returns_empty():
    pool = _FakePool(business_stats={"total": 0})
    ctx = asyncio.run(bk.build_business_context(pool, "org-1", "bot-1"))
    assert ctx == ""


def test_build_business_context_degrades_to_empty_on_db_error():
    pool = _FakePool(fail=True)
    ctx = asyncio.run(bk.build_business_context(pool, "org-1", "bot-1"))
    assert ctx == ""


# ─── 2. Lensa baru terdaftar di planner ────────────────────────

def test_available_lenses_includes_self_knowledge_and_business():
    assert "self_knowledge" in AVAILABLE_LENSES
    assert "business" in AVAILABLE_LENSES


# ─── 3. reasoning_agent: lensa self_knowledge / business ───────

def test_run_lens_self_knowledge_skips_when_no_context():
    agent = ReasoningAgent(api_key="test-key")
    ctx = {"user_message": "Apa bedanya paket Pro dan Business?", "self_knowledge_context": ""}
    result = asyncio.run(agent.run_lens("self_knowledge", ctx))

    assert result.success
    assert result.output.get("skipped") is True
    assert result.output["reason"] == "no_data_available"


def test_run_lens_self_knowledge_runs_with_context(monkeypatch):
    captured = {}

    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=400, default=None):
        captured["messages"] = messages
        return {
            "analysis": "Paket Pro mencakup 1000 percakapan/bulan dan 3 AI Agent.",
            "conclusion": "Business memberikan limit lebih tinggi & API access dibanding Pro.",
            "confidence": 80,
            "limitations": "Perbandingan hanya berdasarkan tabel paket saat ini.",
            "suggested_next_action": "Upgrade ke Business jika butuh API access.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = ReasoningAgent(api_key="test-key")
    ctx = {
        "user_message": "Apa bedanya paket Pro dan Business?",
        "self_knowledge_context": "## Perbandingan Paket\n- Pro: 1000 percakapan\n- Business: 5000 percakapan",
    }
    result = asyncio.run(agent.run_lens("self_knowledge", ctx))

    assert not result.output.get("skipped")
    assert result.output["conclusion"] == "Business memberikan limit lebih tinggi & API access dibanding Pro."
    assert result.output["limitations"]
    assert result.output["suggested_next_action"]
    assert "Perbandingan Paket" in captured["messages"][-1]["content"]


def test_run_lens_business_skips_when_no_context():
    agent = ReasoningAgent(api_key="test-key")
    ctx = {"user_message": "Apa kelemahan bisnis saya?", "business_context": ""}
    result = asyncio.run(agent.run_lens("business", ctx))

    assert result.success
    assert result.output.get("skipped") is True
    assert result.output["reason"] == "no_data_available"


def test_run_lens_business_runs_with_context(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.3, max_tokens=400, default=None):
        return {
            "analysis": "Banyak pelanggan komplain soal respon lambat dalam 30 hari terakhir.",
            "conclusion": "Perbaiki SLA respon untuk menaikkan kepuasan & penjualan.",
            "confidence": 75,
            "limitations": "Data hanya mencakup 30 hari terakhir.",
            "suggested_next_action": "Tambahkan FAQ otomatis untuk pertanyaan pengiriman.",
        }

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)

    agent = ReasoningAgent(api_key="test-key")
    ctx = {
        "user_message": "Apa kelemahan bisnis saya dan bagaimana cara meningkatkan penjualan?",
        "business_context": "## Ringkasan Performa Bisnis (30 hari terakhir)\n- Total percakapan: 42",
    }
    result = asyncio.run(agent.run_lens("business", ctx))

    assert not result.output.get("skipped")
    assert "SLA" in result.output["conclusion"]
    assert result.output["suggested_next_action"]


# ─── 4. AnswerQualityScorer threshold (>=80) di supervisor ─────

_SK_CONTEXT = {
    "bot_id": "bot-1",
    "org_id": "org-1",
    "conversation_id": "conv-1",
    "user_message": "Apa bedanya paket Pro dan Business?",
    "messages": [],
    "knowledge_base_context": "",
    "reasoning_mode": "pro",
    "self_knowledge_context": "## Perbandingan Paket\n- Pro: 1000 percakapan\n- Business: 5000 percakapan",
}


async def _fake_call_llm_dispatch_async(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
    system = messages[0]["content"] if messages else ""
    if "asisten AI bisnis BotNesia" in system:
        return "Jawaban CS langsung."
    return '{"facts_to_store": [], "summary": "", "forget_keys": []}'


def _dispatch_factory(quality_response, synth_calls=None, verify_calls=None):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        system = messages[0]["content"] if messages else ""
        if "perencana tim analis" in system:
            return {
                "agents_to_invoke": ["self_knowledge"],
                "execution_strategy": "parallel",
                "synthesis_focus": "fokus perbandingan paket",
            }
        if "asisten dukungan BotNesia" in system:
            return {
                "analysis": "Pro memberi 1000 percakapan/bulan, Business 5000.",
                "conclusion": "Business lebih cocok untuk bisnis yang sedang scaling.",
                "confidence": 70,
                "limitations": "",
                "suggested_next_action": "",
            }
        if "konsultan ahli" in system:
            if synth_calls is not None:
                synth_calls["n"] += 1
            return {
                "answer": f"Jawaban perbandingan paket versi {synth_calls['n'] if synth_calls else 1}.",
                "confidence_score": 70,
                "topics": [], "suggested_followup": None, "reasoning_summary": "",
            }
        if "quality checker" in system:
            if verify_calls is not None:
                verify_calls["n"] += 1
            return quality_response
        return default or {}

    return fake_call_llm_json


def test_verification_below_threshold_triggers_retry(monkeypatch):
    from supervisor import SupervisorAgent, MAX_RETRIES

    synth_calls, verify_calls = {"n": 0}, {"n": 0}
    fake = _dispatch_factory(
        {"verified": True, "confidence_score": 70, "issues": ["Kurang spesifik."]},
        synth_calls, verify_calls,
    )
    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_SK_CONTEXT)))

    assert result.verification_passed is False
    assert result.retry_count == MAX_RETRIES
    assert verify_calls["n"] == MAX_RETRIES + 1


def test_verification_at_threshold_passes_immediately(monkeypatch):
    from supervisor import SupervisorAgent

    synth_calls, verify_calls = {"n": 0}, {"n": 0}
    fake = _dispatch_factory(
        {"verified": True, "confidence_score": 85, "issues": []},
        synth_calls, verify_calls,
    )
    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_SK_CONTEXT)))

    assert result.verification_passed is True
    assert result.retry_count == 0
    assert verify_calls["n"] == 1


def test_verification_llm_unavailable_short_circuits(monkeypatch):
    from supervisor import SupervisorAgent

    verify_calls = {"n": 0}
    fake = _dispatch_factory(
        {"verified": True, "confidence_score": 100, "issues": [], "_llm_unavailable": True},
        None, verify_calls,
    )
    monkeypatch.setattr(BaseAgent, "_call_llm", _fake_call_llm_dispatch_async)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake)

    supervisor = SupervisorAgent(api_key="test-key")
    result = asyncio.run(supervisor.process(dict(_SK_CONTEXT)))

    assert result.verification_passed is True
    assert result.retry_count == 0
    assert verify_calls["n"] == 1


# ─── 5. Context memory: ringkasan percakapan kumulatif ─────────

def test_conversation_summary_round_trip(tmp_path):
    persist_path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(persist_path))
    store.set_conversation_summary("conv-42", "User menanyakan harga paket Pro dan Business.")

    store2 = MemoryStore(persist_path=str(persist_path))
    assert store2.get_conversation_summary("conv-42") == "User menanyakan harga paket Pro dan Business."


def test_enrich_context_injects_conversation_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_agent_module, "_global_store", None)

    agent = MemoryAgent(api_key="test-key", persist_path=str(tmp_path / "memory.json"))
    agent.store.set_conversation_summary("conv-99", "Diskusi sebelumnya membahas paket Pro.")

    ctx = {
        "conversation_id": "conv-99",
        "user_message": "Kalau yang Business gimana?",
        "knowledge_base_context": "",
    }
    enriched = agent.enrich_context(ctx)

    assert "Ringkasan percakapan sejauh ini" in enriched["knowledge_base_context"]
    assert "Diskusi sebelumnya membahas paket Pro." in enriched["knowledge_base_context"]


def test_memory_run_stores_cumulative_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_agent_module, "_global_store", None)

    async def fake_call_llm(self, messages, temperature=0.1, max_tokens=1024, response_format=None):
        return '{"facts_to_store": [], "summary": "User tertarik paket Pro, lalu menanyakan paket Business.", "forget_keys": []}'

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)

    agent = MemoryAgent(api_key="test-key", persist_path=str(tmp_path / "memory.json"))
    ctx = {
        "user_message": "Kalau yang Business gimana?",
        "bot_response": "Paket Business mencakup 5000 percakapan/bulan dan API access.",
        "messages": [],
        "org_id": "org-1",
        "bot_id": "bot-1",
        "conversation_id": "conv-99",
        "_memory_user_id": "user-1",
    }
    asyncio.run(agent.run(ctx))

    assert agent.store.get_conversation_summary("conv-99") == (
        "User tertarik paket Pro, lalu menanyakan paket Business."
    )


# ─── 6. Routing heuristik untuk 10 pertanyaan wajib ────────────

def test_heuristic_routing_for_mandatory_questions():
    # Q1, Q3, Q10: pertanyaan kausal "kenapa" -> complex (Pro pipeline)
    assert heuristic_complexity("Kenapa BTC turun dari 70k ke 59k, dan apa rekomendasi untuk trader?") == "complex"
    assert heuristic_complexity("Kenapa channel Instagram saya disconnect terus?") == "complex"
    assert heuristic_complexity("Kenapa AI saya cuma jawab harga doang, gak bisa diskusi lebih dalam?") == "complex"

    # Q2: perbandingan paket -> complex
    assert heuristic_complexity("Apa bedanya paket Pro dan Business?") == "complex"

    # Q4, Q5: pertanyaan strategi bisnis -> complex
    assert heuristic_complexity("Bagaimana cara meningkatkan penjualan toko saya?") == "complex"
    assert heuristic_complexity("Apa kelemahan bisnis saya berdasarkan percakapan pelanggan?") == "complex"

    # Q6, Q7, Q8: pertanyaan faktual singkat -> simple (jalur cepat, self-knowledge di knowledge_base_context)
    assert heuristic_complexity("Paket saya apa sekarang?") == "simple"
    assert heuristic_complexity("Sisa percakapan saya berapa bulan ini?") == "simple"
    assert heuristic_complexity("Menu apa untuk hubungkan Instagram?") == "simple"

    # Q9: follow-up singkat -> simple, konteks diisi oleh riwayat percakapan/ringkasan memori
    assert heuristic_complexity("Kalau yang Pro gimana?") == "simple"
