from tts_engine import normalize_tts_text


def test_normalize_tts_text_merges_layout_noise():
    text = "Halo,\n\n\n  ini   jawaban.\nLanjut tanpa jeda acak."
    assert normalize_tts_text(text) == "Halo, ini jawaban. Lanjut tanpa jeda acak."


def test_normalize_tts_text_cleans_bullets_and_markdown():
    text = "## Ringkasan\n\n- Harga **lebih murah**\n- Proses lebih cepat"
    assert normalize_tts_text(text) == "Ringkasan Harga lebih murah Proses lebih cepat"


def test_normalize_tts_text_replaces_urls_and_numbered_items():
    text = "1. Buka https://botnesia.id\n2. Masuk ke dashboard"
    assert normalize_tts_text(text) == "Pertama, Buka tautan Kedua, Masuk ke dashboard"



def test_normalize_tts_text_reads_indonesian_grouped_numbers():
    text = "Biaya Rp100.000, omzet 1.500.000, target 2 miliar, valuasi 3 triliun."
    assert normalize_tts_text(text) == (
        "Biaya seratus ribu rupiah, omzet satu juta lima ratus ribu, "
        "target dua miliar, valuasi tiga triliun."
    )


def test_normalize_tts_text_reads_large_plain_numbers():
    text = "Pendapatan 1000000 dan modal 1000000000000."
    assert normalize_tts_text(text) == "Pendapatan satu juta dan modal satu triliun."


def test_normalize_tts_text_accepts_scale_spelling_variants():
    assert normalize_tts_text("Nilai 5 miliyar dan 7 teriliun.") == "Nilai lima miliar dan tujuh triliun."


def test_normalize_tts_text_reads_scaled_ranges():
    assert normalize_tts_text("Budget 100-500 juta.") == "Budget seratus hingga lima ratus juta."
    assert normalize_tts_text("Target 1,5-2 miliar.") == "Target satu koma lima hingga dua miliar."
    assert normalize_tts_text("Nilai 1 juta - 2 miliar.") == "Nilai satu juta hingga dua miliar."


def test_normalize_tts_text_reads_currency_percent_and_unit_ranges():
    assert normalize_tts_text("Biaya Rp100.000-Rp500.000.") == "Biaya seratus ribu rupiah hingga lima ratus ribu rupiah."
    assert normalize_tts_text("Diskon 10-20% selama 3-5 hari.") == "Diskon sepuluh hingga dua puluh persen selama tiga hingga lima hari."
