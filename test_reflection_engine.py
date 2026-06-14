"""
test_reflection_engine.py — Tes untuk Reflection Engine.

`reflect()` melakukan self-check heuristik terhadap jawaban final, berdasarkan
flag-flag dari `reasoning_brief` (needs_prioritization, is_business_strategy/
needs_risk_assessment, is_root_cause, is_multi_step).
"""
from reflection_engine import reflect


def test_passes_when_no_flags_set():
    review = reflect("Jawaban biasa tanpa instruksi khusus.", {}, {})

    assert review["self_check_passed"] is True
    assert review["notes"] == []
    assert review["penalty"] == 0


def test_penalizes_missing_prioritization():
    brief = {"needs_prioritization": True}
    review = reflect("Berikut beberapa hal yang bisa Anda lakukan untuk bisnis Anda.", brief, {})

    assert review["self_check_passed"] is False
    assert review["penalty"] > 0
    assert any("prioritas" in n.lower() for n in review["notes"])


def test_passes_prioritization_when_priority_pattern_present():
    brief = {"needs_prioritization": True}
    answer = "Prioritas #1: perbaiki website. Prioritas #2: tingkatkan layanan pelanggan."
    review = reflect(answer, brief, {})

    assert review["penalty"] == 0


def test_penalizes_business_strategy_without_risk_wording():
    brief = {"is_business_strategy": True}
    answer = "Sebaiknya Anda menaikkan harga produk sebesar 10% bulan depan."
    review = reflect(answer, brief, {})

    assert review["penalty"] > 0
    assert any("risiko" in n.lower() or "alternatif" in n.lower() for n in review["notes"])


def test_passes_business_strategy_with_risk_wording():
    brief = {"is_business_strategy": True}
    answer = "Sebaiknya naikkan harga 10%. Risikonya pelanggan bisa kabur; alternatifnya, naikkan bertahap."
    review = reflect(answer, brief, {})

    assert review["penalty"] == 0


def test_penalizes_root_cause_without_causal_connectors():
    brief = {"is_root_cause": True}
    answer = "Penjualan turun bulan ini. Coba evaluasi promosi Anda."
    review = reflect(answer, brief, {})

    assert review["penalty"] > 0
    assert any("akar masalah" in n.lower() for n in review["notes"])


def test_passes_root_cause_with_causal_connectors():
    brief = {"is_root_cause": True}
    answer = "Penjualan turun karena promosi berkurang, sehingga jumlah pengunjung toko menurun."
    review = reflect(answer, brief, {})

    assert review["penalty"] == 0


def test_penalizes_multi_step_when_answer_not_structured():
    brief = {"is_multi_step": True, "multi_step_count": 2}
    answer = "Ini adalah satu jawaban tunggal yang menggabungkan semuanya tanpa pemisahan apapun."
    review = reflect(answer, brief, {})

    assert review["penalty"] > 0
    assert any("sub-pertanyaan" in n.lower() for n in review["notes"])


def test_passes_multi_step_when_answer_has_list_items():
    brief = {"is_multi_step": True, "multi_step_count": 2}
    answer = "- Jawaban untuk pertanyaan pertama.\n- Jawaban untuk pertanyaan kedua."
    review = reflect(answer, brief, {})

    assert review["penalty"] == 0


def test_multiple_flags_accumulate_penalty():
    brief = {"needs_prioritization": True, "is_business_strategy": True}
    answer = "Berikut beberapa saran umum yang bisa langsung Anda terapkan untuk bisnis."
    review = reflect(answer, brief, {})

    assert review["penalty"] >= 14
    assert len(review["notes"]) >= 2
