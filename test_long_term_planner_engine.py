"""
test_long_term_planner_engine.py — Tes untuk Long-Term Planner Engine.
"""
from long_term_planner_engine import (
    LONG_TERM_PLANNER_BLOCK,
    is_long_term_planning_question,
)
from reasoning_controller import ReasoningController


LONG_TERM_QUESTIONS = [
    "Apa rencana jangka panjang untuk bisnis saya?",
    "Bagaimana roadmap pengembangan toko online saya 6 bulan ke depan?",
    "Bagaimana cara skalakan bisnis saya tahun ini?",
]


def test_long_term_planning_questions_are_detected():
    for q in LONG_TERM_QUESTIONS:
        assert is_long_term_planning_question(q), q


def test_general_question_is_not_long_term_planning():
    assert is_long_term_planning_question("Bagaimana cara menghubungkan WhatsApp?") is False


def test_reasoning_controller_adds_long_term_planner_block():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": LONG_TERM_QUESTIONS[0], "messages": []})

    assert brief["is_long_term_planning"] is True
    assert LONG_TERM_PLANNER_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_no_long_term_block_for_unrelated_message():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert brief["is_long_term_planning"] is False
    assert "Long-Term Planner" not in brief["style_guidance"]


def test_self_awareness_question_is_not_long_term_planning():
    # "kenapa BotNesia ..." tidak boleh ikut dianggap pertanyaan roadmap bisnis.
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Apa kelemahanmu?", "messages": []})

    assert brief["is_long_term_planning"] is False
