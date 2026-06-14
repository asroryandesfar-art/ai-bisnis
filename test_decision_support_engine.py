"""
test_decision_support_engine.py — Tes untuk Root Cause Analysis Engine,
Trade-Off Engine, dan Risk Assessment Agent.
"""
from decision_support_engine import (
    RISK_ASSESSMENT_BLOCK,
    ROOT_CAUSE_BLOCK,
    TRADE_OFF_BLOCK,
    is_root_cause_question,
    is_trade_off_question,
    needs_risk_assessment,
)
from reasoning_controller import ReasoningController


# ─────────────────────────────────────────────────────────────────
# 1) Root Cause Analysis
# ─────────────────────────────────────────────────────────────────

ROOT_CAUSE_QUESTIONS = [
    "Kenapa penjualan saya selalu turun setiap akhir bulan?",
    "Apa akar masalah kenapa pelanggan banyak komplain?",
    "Apa penyebab utama website saya sering error?",
]


def test_root_cause_questions_are_detected():
    for q in ROOT_CAUSE_QUESTIONS:
        assert is_root_cause_question(q), q


def test_general_question_is_not_root_cause():
    assert is_root_cause_question("Bagaimana cara menghubungkan WhatsApp?") is False


def test_reasoning_controller_adds_root_cause_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": ROOT_CAUSE_QUESTIONS[0], "messages": []})

    assert brief["is_root_cause"] is True
    assert ROOT_CAUSE_BLOCK.splitlines()[0] in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 2) Trade-Off Engine
# ─────────────────────────────────────────────────────────────────

TRADE_OFF_QUESTIONS = [
    "Saya mending pilih supplier A atau supplier B?",
    "Lebih baik buka cabang baru atau menambah stok di toko utama?",
    "Lebih cocok pakai sistem otomatis atau tetap manual untuk bisnis saya?",
]


def test_trade_off_questions_are_detected():
    for q in TRADE_OFF_QUESTIONS:
        assert is_trade_off_question(q), q


def test_ai_comparison_is_not_trade_off():
    # Perbandingan BotNesia vs AI lain ditangani Comparison Engine, bukan
    # Trade-Off Engine (bisnis vs bisnis).
    assert is_trade_off_question("BotNesia lebih baik dari ChatGPT atau tidak?") is False


def test_reasoning_controller_adds_trade_off_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": TRADE_OFF_QUESTIONS[0], "messages": []})

    assert brief["is_trade_off"] is True
    assert TRADE_OFF_BLOCK.splitlines()[0] in brief["style_guidance"]


# ─────────────────────────────────────────────────────────────────
# 3) Risk Assessment Agent
# ─────────────────────────────────────────────────────────────────

def test_needs_risk_assessment_for_business_strategy():
    assert needs_risk_assessment("pertanyaan apa saja", is_business_strategy=True) is True


def test_needs_risk_assessment_for_explicit_risk_keyword():
    assert needs_risk_assessment("Apa risiko jika saya menaikkan harga sekarang?") is True


def test_needs_risk_assessment_false_for_unrelated_question():
    assert needs_risk_assessment("Bagaimana cara menghubungkan WhatsApp?") is False


def test_reasoning_controller_adds_risk_assessment_block_for_business_strategy():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Haruskah saya menurunkan harga?", "messages": []})

    assert brief["needs_risk_assessment"] is True
    assert RISK_ASSESSMENT_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_no_risk_block_for_unrelated_message():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert brief["needs_risk_assessment"] is False
    assert "Risk Assessment" not in brief["style_guidance"]
