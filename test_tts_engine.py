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
