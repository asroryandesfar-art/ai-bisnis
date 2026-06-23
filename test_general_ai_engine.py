"""
test_general_ai_engine.py — General AI Agent: deteksi pertanyaan umum di
luar topik bisnis tenant, dan wiring GENERAL_AI_BLOCK lewat
ReasoningController (jangan menimpa blok business_strategy/meta).
"""
from general_ai_engine import GENERAL_AI_BLOCK, is_general_ai_request
from reasoning_controller import ReasoningController


def test_is_general_ai_request_detects_general_knowledge_examples():
    assert is_general_ai_request("Siapa presiden Indonesia?")
    assert is_general_ai_request("Buatkan puisi tentang senja")
    assert is_general_ai_request("Terjemahkan kalimat ini ke bahasa Inggris")
    assert is_general_ai_request("Jelaskan hukum Newton")
    assert is_general_ai_request("Apa itu fotosintesis?")
    assert is_general_ai_request("Buatkan surat lamaran kerja untuk posisi admin")


def test_is_general_ai_request_false_for_business_question():
    assert not is_general_ai_request("Kenapa bisnis saya sepi pelanggan bulan ini?")
    assert not is_general_ai_request("Berapa harga paket Enterprise BotNesia?")


def test_reasoning_controller_adds_general_ai_block_for_general_question():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Buatkan puisi tentang senja", "messages": []})
    assert brief["is_general_ai"] is True
    assert GENERAL_AI_BLOCK in brief["style_guidance"]


def test_reasoning_controller_does_not_add_general_ai_block_for_business_strategy():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Kenapa bisnis saya sepi pelanggan?", "messages": []})
    assert brief["is_business_strategy"] is True
    assert brief["is_general_ai"] is False
    assert GENERAL_AI_BLOCK not in brief["style_guidance"]


def test_reasoning_controller_general_ai_can_coexist_with_officeholder_freshness():
    # "Siapa presiden Indonesia?" sekaligus general-knowledge DAN
    # officeholder/freshness question — kedua flag boleh sama-sama True.
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Siapa presiden Indonesia?", "messages": []})
    assert brief["is_general_ai"] is True
    assert brief["knowledge_routing"]["needs_fresh_data"] is True
