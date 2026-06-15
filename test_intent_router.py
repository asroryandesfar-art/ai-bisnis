"""
Unit tests for supervisor.py::route_intent() — 8-class Intent Router.

Verifikasi 6 pesan dari spesifikasi arsitektur plus kasus edge:
  - Permintaan eksplisit ke manusia (admin)  → human_handoff / allow_human_handoff=True
  - Permintaan refund                         → customer_service / allow_human_handoff=True
  - Pertanyaan harga                          → sales / allow_human_handoff=False
  - Pertanyaan how-to produk                  → knowledge / allow_human_handoff=False
  - Pertanyaan umum off-topic                 → general / allow_human_handoff=False
  - Pertanyaan umum "apa itu Bitcoin"         → general / allow_human_handoff=False
  - LLM unavailable flag di-propagate ke confidence
"""
import sys
import os

# Tambahkan direktori project ke sys.path
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from supervisor import route_intent


# ── Fixture defaults ────────────────────────────────────────────────────────

def _esc_out(**kwargs) -> dict:
    base = {"trigger_factors": [], "should_escalate": False, "urgency": "low", "reason": None}
    base.update(kwargs)
    return base

def _brief(**kwargs) -> dict:
    base = {"intent_type": "general", "is_business_strategy": False, "needs_prioritization": False}
    base.update(kwargs)
    return base

EMPTY_FAQ  = {"matched": False}
EMPTY_SALES = {"signals": [], "has_objection": False}
EMPTY_KG   = {"product_mentions": []}


# ── Test cases ──────────────────────────────────────────────────────────────

def test_explicit_human_request_via_trigger_factors():
    """'Saya mau bicara dengan admin' → EscalationAgent sets request_human → human_handoff."""
    result = route_intent(
        user_message="Saya mau bicara dengan admin",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["request_human"]),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "human_handoff"
    assert result["selected_agent"] == "Human Handoff Agent"
    assert result["allow_human_handoff"] is True
    assert result["confidence"] == pytest.approx(0.95)


def test_explicit_human_request_via_keyword():
    """'Tolong hubungkan ke manusia' → keyword match → human_handoff."""
    result = route_intent(
        user_message="Tolong hubungkan ke manusia",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "human_handoff"
    assert result["allow_human_handoff"] is True


def test_refund_request():
    """'Saya mau refund' → EscalationAgent sets refund trigger → customer_service / allow_human_handoff=True."""
    result = route_intent(
        user_message="Saya mau refund",
        reasoning_brief=_brief(),
        text_intent="complaint_refund",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["refund"]),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "customer_service"
    assert result["selected_agent"] == "Customer Service Agent"
    assert result["allow_human_handoff"] is True


def test_pricing_question():
    """'Harga paket BotNesia berapa?' → text_intent pricing_question → sales / no handoff."""
    result = route_intent(
        user_message="Harga paket BotNesia berapa?",
        reasoning_brief=_brief(),
        text_intent="pricing_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "sales"
    assert result["selected_agent"] == "Sales Agent"
    assert result["allow_human_handoff"] is False


def test_how_to_question():
    """'Cara hubungkan WhatsApp?' → keyword 'cara' → knowledge / no handoff."""
    result = route_intent(
        user_message="Cara hubungkan WhatsApp?",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "knowledge"
    assert result["selected_agent"] == "Knowledge Agent"
    assert result["allow_human_handoff"] is False


def test_off_topic_general():
    """'Carikan hotel terbaik di Gresik' → off-topic general carve-out → general / no handoff."""
    result = route_intent(
        user_message="Carikan hotel terbaik di Gresik",
        reasoning_brief=_brief(intent_type="general"),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.6,
        llm_unavailable=False,
    )
    assert result["intent"] == "general"
    assert result["selected_agent"] == "General AI Agent"
    assert result["allow_human_handoff"] is False


def test_general_bitcoin():
    """'Apa itu Bitcoin?' → falls through to default general."""
    result = route_intent(
        user_message="Apa itu Bitcoin?",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.65,
        llm_unavailable=False,
    )
    assert result["intent"] == "general"
    assert result["allow_human_handoff"] is False


def test_faq_match():
    """FAQ match → intent='faq' / no handoff."""
    result = route_intent(
        user_message="Bagaimana cara reset password?",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out={"matched": True, "similarity": 0.92, "faq_id": "1", "question": "Reset password"},
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.8,
        llm_unavailable=False,
    )
    assert result["intent"] == "faq"
    assert result["selected_agent"] == "FAQ Agent"
    assert result["allow_human_handoff"] is False
    assert result["confidence"] == pytest.approx(0.92)


def test_llm_unavailable_floors_confidence():
    """During LLM outage, explicit human request still returns human_handoff but confidence floored at 0.5."""
    result = route_intent(
        user_message="minta manusia",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["request_human"]),
        cs_confidence=0.2,
        llm_unavailable=True,
    )
    assert result["intent"] == "human_handoff"
    assert result["allow_human_handoff"] is True
    assert result["confidence"] >= 0.5


def test_llm_unavailable_general_floored():
    """During LLM outage, normal question routes general and confidence is floored at >= 0.5."""
    result = route_intent(
        user_message="Halo",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.2,
        llm_unavailable=True,
    )
    assert result["intent"] == "general"
    assert result["allow_human_handoff"] is False
    assert result["confidence"] >= 0.5


def test_legal_threat():
    """Legal threat → human_handoff / allow_human_handoff=True."""
    result = route_intent(
        user_message="Saya akan lapor ke polisi",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["legal_threat"], urgency="high"),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == "human_handoff"
    assert result["allow_human_handoff"] is True


def test_result_schema():
    """Setiap hasil route_intent() wajib punya 6 kunci sesuai spesifikasi."""
    result = route_intent(
        user_message="Test",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    required_keys = {"intent", "confidence", "selected_agent", "reason", "needs_clarification", "allow_human_handoff"}
    assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - result.keys()}"
    assert result["intent"] in ("general", "business", "faq", "sales", "customer_service", "knowledge", "analytics", "human_handoff")
    assert isinstance(result["allow_human_handoff"], bool)
    assert isinstance(result["needs_clarification"], bool)
    assert isinstance(result["confidence"], float)
