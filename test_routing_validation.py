"""
Validasi Supervisor Routing — pemetaan 1:1 ke 6 skenario di spesifikasi
"Production Readiness Phase":

  "Apa itu Bitcoin?"              -> General AI Agent
  "Harga paket BotNesia?"         -> Sales Agent
  "Cara konek WhatsApp?"          -> Knowledge Agent
  "Saya mau refund"               -> Customer Service Agent
  "Saya mau bicara dengan admin"  -> Human Handoff Agent
  "Carikan hotel terbaik di Gresik" -> divalidasi di tests/e2e/test_marketplace_flow.py
      (bot ber-template marketplace "Travel Agent"), BUKAN di sini — arsitektur
      BotNesia merutekan ke spesialis Travel lewat instalasi template per-bot,
      bukan lewat kelas intent baru di route_intent()'s 8-class taxonomy
      (lihat test_off_topic_general di test_intent_router.py untuk perilaku
      route_intent() generik terhadap query ini).

Setiap skenario juga wajib menampilkan confidence routing (non-null), sesuai
requirement "Confidence routing wajib tampil".
"""
import pytest

from supervisor import route_intent


def _esc_out(**kwargs) -> dict:
    base = {"trigger_factors": [], "should_escalate": False, "urgency": "low", "reason": None}
    base.update(kwargs)
    return base


def _brief(**kwargs) -> dict:
    base = {"intent_type": "general", "is_business_strategy": False, "needs_prioritization": False}
    base.update(kwargs)
    return base


EMPTY_FAQ = {"matched": False}
EMPTY_SALES = {"signals": [], "has_objection": False}
EMPTY_KG = {"product_mentions": []}


@pytest.mark.parametrize(
    ("message", "text_intent", "esc_kwargs", "expected_intent", "expected_agent"),
    [
        ("Apa itu Bitcoin?", "general_question", {}, "general", "General AI Agent"),
        ("Harga paket BotNesia?", "pricing_question", {}, "sales", "Sales Agent"),
        ("Cara konek WhatsApp?", "general_question", {}, "knowledge", "Knowledge Agent"),
        ("Saya mau refund", "complaint_refund", {"trigger_factors": ["refund"]},
         "customer_service", "Customer Service Agent"),
        ("Saya mau bicara dengan admin", "general_question", {"trigger_factors": ["request_human"]},
         "human_handoff", "Human Handoff Agent"),
    ],
)
def test_routing_spec_scenarios(message, text_intent, esc_kwargs, expected_intent, expected_agent):
    result = route_intent(
        user_message=message,
        reasoning_brief=_brief(),
        text_intent=text_intent,
        faq_out=EMPTY_FAQ,
        sales_out=EMPTY_SALES,
        kg_out=EMPTY_KG,
        esc_out=_esc_out(**esc_kwargs),
        cs_confidence=0.7,
        llm_unavailable=False,
    )
    assert result["intent"] == expected_intent
    assert result["selected_agent"] == expected_agent
    # "Confidence routing wajib tampil" — harus selalu ada & bukan None.
    assert result["confidence"] is not None
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0


def test_refund_allows_handoff_per_strict_policy():
    """Refund ada di daftar 5 kategori yang diizinkan handoff_guard.py."""
    result = route_intent(
        user_message="Saya mau refund",
        reasoning_brief=_brief(),
        text_intent="complaint_refund",
        faq_out=EMPTY_FAQ, sales_out=EMPTY_SALES, kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["refund"]),
        cs_confidence=0.7, llm_unavailable=False,
    )
    assert result["allow_human_handoff"] is True


def test_admin_request_allows_handoff_per_strict_policy():
    result = route_intent(
        user_message="Saya mau bicara dengan admin",
        reasoning_brief=_brief(),
        text_intent="general_question",
        faq_out=EMPTY_FAQ, sales_out=EMPTY_SALES, kg_out=EMPTY_KG,
        esc_out=_esc_out(trigger_factors=["request_human"]),
        cs_confidence=0.7, llm_unavailable=False,
    )
    assert result["allow_human_handoff"] is True


def test_bitcoin_and_whatsapp_questions_do_not_allow_handoff():
    """General/knowledge questions are not in the 5 allowed handoff categories."""
    for message, text_intent in (
        ("Apa itu Bitcoin?", "general_question"),
        ("Cara konek WhatsApp?", "general_question"),
        ("Harga paket BotNesia?", "pricing_question"),
    ):
        result = route_intent(
            user_message=message,
            reasoning_brief=_brief(),
            text_intent=text_intent,
            faq_out=EMPTY_FAQ, sales_out=EMPTY_SALES, kg_out=EMPTY_KG,
            esc_out=_esc_out(),
            cs_confidence=0.7, llm_unavailable=False,
        )
        assert result["allow_human_handoff"] is False, f"{message!r} should not allow handoff"
