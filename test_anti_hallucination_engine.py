"""
test_anti_hallucination_engine.py — Tes untuk Anti-Hallucination Engine.

Mencakup:
  - `score_hallucination_risk()` mendeteksi klaim angka yang tidak ada di
    konteks dan bahasa "pasti"/"dijamin" tanpa kualifikasi.
  - `ANTI_HALLUCINATION_BLOCK` selalu ada di style_guidance (always-on).
  - `VerificationAgent.score_hallucination_risk()` mendelegasikan ke modul ini.
"""
from anti_hallucination_engine import ANTI_HALLUCINATION_BLOCK, score_hallucination_risk
from reasoning_controller import ReasoningController
from verification_agent import VerificationAgent


def test_no_risk_for_grounded_answer():
    context = "Paket Pro BotNesia harganya Rp500.000 per bulan."
    answer = "Paket Pro BotNesia harganya Rp500.000 per bulan."
    result = score_hallucination_risk(answer, context)

    assert result["needs_rewrite"] is False
    assert result["unsupported_claims"] == []


def test_unsupported_numeric_claims_detected():
    context = "BotNesia adalah platform chatbot AI multi-tenant."
    answer = "Dengan BotNesia, omzet Anda pasti naik 35% dan revenue bertambah Rp10.000.000 per bulan."
    result = score_hallucination_risk(answer, context)

    assert len(result["unsupported_claims"]) >= 2
    assert result["needs_rewrite"] is True
    assert result["risk_score"] > 0


def test_overconfidence_without_hedge_triggers_rewrite():
    answer = "BotNesia pasti akan menyelesaikan semua masalah bisnis Anda, dijamin 100% berhasil."
    result = score_hallucination_risk(answer, "")

    assert result["overconfidence_hits"] >= 1
    assert result["needs_rewrite"] is True


def test_hedged_claims_do_not_trigger_overconfidence_rewrite():
    answer = "Kemungkinan omzet Anda bisa naik, tapi ini hanya perkiraan dan tergantung banyak faktor."
    result = score_hallucination_risk(answer, "")

    assert result["overconfidence_hits"] == 0


def test_anti_hallucination_block_always_present_in_style_guidance():
    rc = ReasoningController()
    brief = rc.analyze({"user_message": "Bagaimana cara menghubungkan WhatsApp?", "messages": []})

    assert ANTI_HALLUCINATION_BLOCK.splitlines()[0] in brief["style_guidance"]


def test_verification_agent_delegates_to_module_function():
    agent = VerificationAgent(api_key="test-key")
    context = "BotNesia adalah platform chatbot AI multi-tenant."
    answer = "Omzet Anda dijamin naik 50% dalam sebulan."
    result = agent.score_hallucination_risk(answer, context)

    assert result["needs_rewrite"] is True
    assert "50%" in " ".join(result["unsupported_claims"])
