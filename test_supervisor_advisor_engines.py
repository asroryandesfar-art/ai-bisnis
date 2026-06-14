"""
test_supervisor_advisor_engines.py — Tes end-to-end (mocked LLM) untuk
engine-engine advisor/reasoning Phase 2:

  - Anti-Hallucination Engine: jawaban dengan klaim angka yang tidak ada di
    konteks + bahasa "dijamin" memicu satu kali penulisan ulang (STEP 2.75).
  - Reflection Engine: jawaban yang tidak memberi urutan prioritas meski
    `needs_prioritization` True mendapat penalty di `reflection_review`,
    yang menurunkan `uncertainty_score`.
  - Goal Tracking Engine: pernyataan target bisnis memicu
    `GOAL_TRACKING_BLOCK` di `reasoning_brief.style_guidance`.
"""
import asyncio

from base import BaseAgent


async def _fake_call_llm_json_default(self, messages, temperature=0.2, max_tokens=512, default=None):
    return default or {}


def _build_supervisor():
    from supervisor import SupervisorAgent
    return SupervisorAgent(api_key="test-key")


def _base_context(**overrides):
    context = {
        "bot_id": "bot-1",
        "org_id": "org-1",
        "conversation_id": "conv-1",
        "user_message": "Bagaimana cara meningkatkan penjualan saya?",
        "messages": [],
        "knowledge_base_context": "",
        "reasoning_mode": "standard",
    }
    context.update(overrides)
    return context


# ─────────────────────────────────────────────────────────────────
# 1) Anti-Hallucination Engine — rewrite trigger
# ─────────────────────────────────────────────────────────────────

def test_anti_hallucination_triggers_rewrite_on_fabricated_claims(monkeypatch):
    calls = {"n": 0}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        calls["n"] += 1
        system = messages[0]["content"] if messages else ""
        if "Catatan perbaikan dari verifikasi" in system:
            return "Strategi ini bisa membantu meningkatkan penjualan, tergantung kondisi pasar Anda."
        return "Dengan strategi ini, omzet Anda dijamin naik 45% dan profit bertambah Rp20.000.000 per bulan."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    result = asyncio.run(supervisor.process(_base_context()))

    assert calls["n"] >= 2
    assert result.hallucination_scores.get("needs_rewrite") is False
    assert result.meta_rewrite_applied is True
    assert "dijamin" not in result.final_answer.lower()
    assert "45%" not in result.final_answer


def test_anti_hallucination_no_rewrite_for_grounded_answer(monkeypatch):
    calls = {"n": 0}

    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        calls["n"] += 1
        return "Anda bisa mencoba menambah promosi dan memperluas jangkauan pemasaran secara bertahap."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    result = asyncio.run(supervisor.process(_base_context()))

    assert calls["n"] == 1
    assert result.meta_rewrite_applied is False
    assert result.hallucination_scores.get("needs_rewrite") is False


# ─────────────────────────────────────────────────────────────────
# 2) Reflection Engine — prioritization penalty
# ─────────────────────────────────────────────────────────────────

MULTI_PROBLEM_MESSAGE = (
    "Masalah saya banyak:\n"
    "- website lambat\n"
    "- penjualan turun\n"
    "- biaya tinggi\n"
    "- customer komplain\n"
    "Apa yang harus saya lakukan dulu?"
)


def test_reflection_penalizes_missing_prioritization(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return (
            "Anda bisa memperbaiki website, menambah promosi, mengevaluasi biaya, "
            "dan menanggapi komplain pelanggan."
        )

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = _base_context(user_message=MULTI_PROBLEM_MESSAGE)
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_brief["needs_prioritization"] is True
    assert result.reflection_review["penalty"] > 0
    assert any("prioritas" in n.lower() for n in result.reflection_review["notes"])
    assert any(reason in result.uncertainty_reasons for reason in result.reflection_review["notes"])


# ─────────────────────────────────────────────────────────────────
# 3) Goal Tracking Engine — goal statement detected
# ─────────────────────────────────────────────────────────────────

def test_goal_tracking_block_appears_when_goal_stated(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        return "Baik, target tersebut akan saya jadikan acuan untuk rekomendasi berikutnya."

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    monkeypatch.setattr(BaseAgent, "_call_llm_json", _fake_call_llm_json_default)

    supervisor = _build_supervisor()
    context = _base_context(user_message="Target saya naikkan omzet 20% dalam 3 bulan.")
    result = asyncio.run(supervisor.process(context))

    assert result.reasoning_brief["detected_goal"] is True
    assert "Goal Tracking" in result.reasoning_brief["style_guidance"]
