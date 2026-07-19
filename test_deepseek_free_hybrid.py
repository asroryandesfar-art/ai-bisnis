"""Hybrid free-tier — pertanyaan kompleks pakai R1 (THINKING), simpel tetap FAST.

Menjawab "otak tolol": free tidak lagi selalu dapat model dangkal (deepseek-chat);
pertanyaan kompleks naik ke deepseek-reasoner (R1), pertanyaan simpel tetap murah.
"""
import deepseek_brain as db
from deepseek_brain import (
    Tier, apply_complexity_escalation, classify_tier, enforce_plan,
)


def test_free_simple_stays_fast():
    needed = Tier.FAST                          # pertanyaan simpel
    capped = enforce_plan(needed, "free")       # FAST
    assert apply_complexity_escalation(needed, capped, "free") == Tier.FAST


def test_free_complex_escalates_to_thinking():
    needed = Tier.THINKING                      # kompleks
    capped = enforce_plan(needed, "free")       # dulu ke-cap FAST
    assert capped == Tier.FAST
    assert apply_complexity_escalation(needed, capped, "free") == Tier.THINKING


def test_free_heavy_pro_escalates_to_thinking_not_pro():
    needed = Tier.PRO                           # berat (komplain/billing)
    capped = enforce_plan(needed, "free")       # FAST
    # free naik ke R1 (THINKING), TIDAK pernah PRO
    assert apply_complexity_escalation(needed, capped, "free") == Tier.THINKING


def test_paid_plan_unaffected():
    needed = Tier.THINKING
    capped = enforce_plan(needed, "starter")    # starter boleh THINKING
    assert apply_complexity_escalation(needed, capped, "starter") == Tier.THINKING
    # enterprise butuh PRO tetap PRO (bukan diturunkan)
    assert apply_complexity_escalation(Tier.PRO, enforce_plan(Tier.PRO, "enterprise"), "enterprise") == Tier.PRO


def test_free_analytical_intent_escalates_even_if_classifier_says_fast():
    """Pertanyaan advis bisnis yang LOLOS dari heuristic_complexity tetap naik R1."""
    q = "Bagaimana strategi menaikkan omzet warung kopi kecil yang sepi pelanggan?"
    needed = classify_tier(q)                    # sering FAST (heuristik konservatif)
    eff = apply_complexity_escalation(needed, enforce_plan(needed, "free"), "free", q)
    assert eff == Tier.THINKING                  # tetap naik ke R1 via intent analitis


def test_free_simple_price_question_stays_fast():
    q = "berapa harga kopi?"
    needed = classify_tier(q)
    eff = apply_complexity_escalation(needed, enforce_plan(needed, "free"), "free", q)
    assert eff == Tier.FAST                       # simpel → tetap murah


def test_analytical_intent_only_for_free():
    q = "Bagaimana strategi menaikkan omzet dan efisiensi biaya bisnis saya?"
    # plan berbayar tidak butuh eskalasi ini (sudah dapat THINKING dari cap-nya)
    needed = classify_tier(q)
    assert apply_complexity_escalation(needed, enforce_plan(needed, "pro"), "pro", q) >= enforce_plan(needed, "pro")


def test_can_be_disabled(monkeypatch):
    monkeypatch.setattr(db, "_FREE_COMPLEX_THINKING", False)
    assert apply_complexity_escalation(Tier.THINKING, Tier.FAST, "free") == Tier.FAST


def test_end_to_end_free_hybrid():
    # simpel → FAST (murah)
    simple = classify_tier("halo, terima kasih")
    assert apply_complexity_escalation(simple, enforce_plan(simple, "free"), "free") == Tier.FAST
    # kompleks analitis → escalate ke THINKING bila classifier menandai kompleks
    q = ("Tolong analisis mendalam dan bandingkan beberapa strategi untuk "
         "meningkatkan omzet dan efisiensi biaya bisnis warung kopi saya secara menyeluruh")
    needed = classify_tier(q)
    eff = apply_complexity_escalation(needed, enforce_plan(needed, "free"), "free")
    if needed >= Tier.THINKING:
        assert eff == Tier.THINKING
    assert eff >= enforce_plan(needed, "free")   # tak pernah menurunkan
