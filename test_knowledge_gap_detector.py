"""
test_knowledge_gap_detector.py — Tes untuk Knowledge Gap Detector.
"""
from knowledge_gap_detector import KNOWLEDGE_GAP_BLOCK, detect_knowledge_gap
from reasoning_controller import ReasoningController


def test_gap_detected_when_kb_empty_for_specific_question():
    result = detect_knowledge_gap("Apa kebijakan retur produk di toko saya?", 0, {})
    assert result["knowledge_gap_detected"] is True


def test_no_gap_when_kb_has_chunks():
    result = detect_knowledge_gap("Apa kebijakan retur produk di toko saya?", 3, {})
    assert result["knowledge_gap_detected"] is False


def test_no_gap_for_greeting():
    result = detect_knowledge_gap("Terima kasih", 0, {})
    assert result["knowledge_gap_detected"] is False


def test_no_gap_for_meta_question():
    result = detect_knowledge_gap("Apa kelemahanmu?", 0, {})
    assert result["knowledge_gap_detected"] is False


def test_no_gap_for_freshness_question():
    result = detect_knowledge_gap("Apa berita terbaru hari ini?", 0, {"needs_fresh_data": True})
    assert result["knowledge_gap_detected"] is False


def test_no_gap_for_self_knowledge_routing():
    result = detect_knowledge_gap(
        "Apa saja fitur BotNesia?", 0, {"reasons": {"self_knowledge": "..."}}
    )
    assert result["knowledge_gap_detected"] is False


def test_no_gap_for_very_short_message():
    result = detect_knowledge_gap("ok", 0, {})
    assert result["knowledge_gap_detected"] is False


def test_reasoning_controller_adds_knowledge_gap_block():
    rc = ReasoningController()
    brief = rc.analyze({
        "user_message": "Apa kebijakan retur produk di toko saya?",
        "messages": [],
        "kb_chunks_count": 0,
    })

    assert brief["knowledge_gap_detected"] is True
    assert KNOWLEDGE_GAP_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_reasoning_controller_no_gap_block_when_kb_has_chunks():
    rc = ReasoningController()
    brief = rc.analyze({
        "user_message": "Apa kebijakan retur produk di toko saya?",
        "messages": [],
        "kb_chunks_count": 2,
    })

    assert brief["knowledge_gap_detected"] is False
    assert "Knowledge Gap" not in brief["style_guidance"]
