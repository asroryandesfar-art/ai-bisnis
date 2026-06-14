"""
test_multi_step_thinking_engine.py — Tes untuk Multi-Step Thinking Engine.
"""
from multi_step_thinking_engine import (
    MULTI_STEP_THINKING_BLOCK,
    count_sub_questions,
    is_multi_step_question,
)
from reasoning_controller import ReasoningController


MULTI_STEP_MESSAGES = [
    "Apa itu BotNesia dan bagaimana cara daftarnya?",
    "Berapa biaya per bulan, dan apakah ada paket gratis?",
    "Bagaimana cara setup WhatsApp, lalu bagaimana cara menambah agent?",
]

SINGLE_STEP_MESSAGES = [
    "Bagaimana cara menghubungkan WhatsApp?",
    "Apa itu BotNesia?",
]


def test_multi_step_messages_are_detected():
    for q in MULTI_STEP_MESSAGES:
        assert is_multi_step_question(q), q


def test_single_step_messages_are_not_multi_step():
    for q in SINGLE_STEP_MESSAGES:
        assert is_multi_step_question(q) is False, q


def test_count_sub_questions_matches_question_marks():
    assert count_sub_questions("Apa itu BotNesia dan bagaimana cara daftarnya?") >= 2
    assert count_sub_questions("Bagaimana cara menghubungkan WhatsApp?") == 1


def test_reasoning_controller_adds_multi_step_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": MULTI_STEP_MESSAGES[0], "messages": []})

    assert brief["is_multi_step"] is True
    assert brief["multi_step_count"] >= 2
    assert MULTI_STEP_THINKING_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_no_multi_step_block_for_single_question():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert brief["is_multi_step"] is False
    assert "Multi-Step Thinking" not in brief["style_guidance"]
