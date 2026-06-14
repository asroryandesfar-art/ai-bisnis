"""
test_goal_tracking_engine.py — Tes untuk Goal Tracking Engine.

Mencakup:
  - Deteksi pernyataan target/tujuan bisnis ("target saya...", "ingin menaikkan
    omzet 20% dalam 3 bulan", dst.).
  - Deteksi target bisnis yang sudah tersimpan di profil user (`business_goal`
    fact via MemoryAgent).
  - Wiring ke ReasoningController: blok Goal Tracking muncul di style_guidance.
"""
from goal_tracking_engine import (
    GOAL_TRACKING_BLOCK,
    TRACKED_GOAL_BLOCK,
    has_tracked_goal,
    is_goal_statement,
)
from reasoning_controller import ReasoningController


GOAL_STATEMENTS = [
    "Target saya naikkan omzet 20% dalam 3 bulan.",
    "Tujuan kami tahun ini menggandakan jumlah pelanggan.",
    "Saya ingin meningkatkan penjualan 30 persen bulan ini.",
    "Goal saya adalah mendongkrak revenue dalam 6 bulan ke depan.",
]

NON_GOAL_MESSAGES = [
    "Bagaimana cara menghubungkan WhatsApp?",
    "Apa itu BotNesia?",
    "Halo, selamat pagi.",
]


def test_goal_statements_are_detected():
    for q in GOAL_STATEMENTS:
        assert is_goal_statement(q), q


def test_non_goal_messages_are_not_detected():
    for q in NON_GOAL_MESSAGES:
        assert is_goal_statement(q) is False, q


def test_has_tracked_goal_detects_business_goal_fact():
    context = (
        "## Informasi yang diketahui tentang user ini:\n"
        "- business_goal: naikkan omzet 20% dalam 3 bulan (confidence: high)"
    )
    assert has_tracked_goal(context) is True


def test_has_tracked_goal_false_without_fact():
    assert has_tracked_goal("") is False
    assert has_tracked_goal("## Informasi yang diketahui tentang user ini:\n- nama: Budi") is False


def test_reasoning_controller_adds_goal_tracking_block_for_goal_statement():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": GOAL_STATEMENTS[0], "messages": []})

    assert brief["detected_goal"] is True
    assert GOAL_TRACKING_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_adds_tracked_goal_block_when_profile_has_goal():
    rc = ReasoningController()
    kb_context = (
        "## Informasi yang diketahui tentang user ini:\n"
        "- business_goal: naikkan omzet 20% dalam 3 bulan (confidence: high)"
    )
    brief = rc.analyze({
        "user_message": "Apa langkah selanjutnya untuk meningkatkan konversi?",
        "messages": [],
        "knowledge_base_context": kb_context,
    })

    assert brief["detected_goal"] is False
    assert brief["has_tracked_goal"] is True
    assert TRACKED_GOAL_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_no_goal_blocks_for_unrelated_message():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert brief["detected_goal"] is False
    assert brief["has_tracked_goal"] is False
    assert "Goal Tracking" not in brief["style_guidance"]
