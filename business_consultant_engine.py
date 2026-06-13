"""
business_consultant_engine.py — Strategic Thinking, Business Consultant Mode,
dan Prioritization untuk BotNesia.

Modul ini TIDAK memanggil LLM. Sama seperti `identity_agent.py`, modul ini hanya
mendeteksi jenis pertanyaan (heuristik/regex) dan menyediakan blok instruksi
("style guidance") yang digabungkan ke `knowledge_base_context` oleh
`reasoning_controller.ReasoningController.analyze()`.

Tujuan: untuk pertanyaan strategi/keputusan bisnis ("haruskah saya...",
"kenapa bisnis saya sepi?", "apa prioritas saya?", dst.), BotNesia tidak hanya
menjawab ya/tidak, tetapi berpikir seperti konsultan bisnis (CEO/COO/CTO/CMO/
Customer Success): dampak jangka pendek & panjang, peluang, risiko, alternatif,
dan — bila user menyebut beberapa masalah sekaligus — urutan prioritas dengan
alasan.
"""
from __future__ import annotations

import re


# ============================================================
# DETEKSI — pertanyaan strategi/keputusan bisnis
# ============================================================

BUSINESS_STRATEGY_PATTERN = re.compile(
    r"haruskah\s+(saya|kami)|"
    r"sebaiknya\s+(saya|kami)|"
    r"apakah\s+(saya|kami)\s+(perlu|harus|sebaiknya)|"
    r"perlu(kah)?\s+(saya|kami)|"
    r"(kenapa|mengapa)\s+.*(bisnis|usaha|toko|penjualan|omzet|omset)\s+.*"
    r"(sepi|turun|menurun|lambat|stagnan|anjlok)|"
    r"(bisnis|usaha|toko|penjualan|omzet|omset)\s+(saya|kami)\s+"
    r"(sepi|turun|menurun|lambat|stagnan|anjlok)|"
    r"apa\s+prioritas|prioritas\s+(saya|kami|utama|tertinggi|bisnis)|"
    r"strategi\s+(apa|untuk|bisnis|terbaik)|"
    r"(menaikkan|menurunkan|naikkan|turunkan)\s+harga|"
    r"(merekrut|rekrut|hire|pecat|phk|tambah)\s+(karyawan|staf|pegawai|tim)|"
    r"(meningkatkan|menambah|menaikkan|mendongkrak)\s+"
    r"(penjualan|omzet|omset|revenue|profit|keuntungan|customer|pelanggan)|"
    r"cara\s+(meningkatkan|menaikkan|mengatasi|memperbaiki|mendongkrak)",
    re.IGNORECASE,
)

# Kata yang menandakan user menyebut "masalah/kendala" (untuk Prioritization).
_PROBLEM_WORD_PATTERN = re.compile(r"masalah|kendala|isu|problem", re.IGNORECASE)

# Baris berformat daftar: "- ...", "* ...", "1. ...", "1) ...", "• ...".
_LIST_ITEM_PATTERN = re.compile(r"^\s*([-*•]|\d+[.\)])\s+")


def is_business_strategy_question(text: str) -> bool:
    """True jika pesan meminta keputusan/strategi bisnis (bukan tentang BotNesia)."""
    return bool(BUSINESS_STRATEGY_PATTERN.search(text or ""))


def has_multiple_problems(text: str) -> bool:
    """True jika user menyebut beberapa masalah/kendala sekaligus.

    Dipakai untuk memutuskan apakah jawaban perlu Prioritization
    (Prioritas #1/#2/#3 + alasan), bukan menjawab semua hal setara.
    """
    raw = text or ""
    lines = [line for line in raw.splitlines() if line.strip()]
    list_items = [line for line in lines if _LIST_ITEM_PATTERN.match(line)]
    if len(list_items) >= 2:
        return True

    if _PROBLEM_WORD_PATTERN.search(raw):
        segments = [s.strip() for s in re.split(r",|;|\n|\bdan\b", raw, flags=re.IGNORECASE) if s.strip()]
        if len(segments) >= 3:
            return True

    return False


# ============================================================
# STYLE GUIDANCE — blok instruksi untuk system prompt
# ============================================================

STRATEGIC_THINKING_BLOCK = """## Strategic Thinking
Untuk pertanyaan keputusan/strategi bisnis (mis. "haruskah saya...", "sebaiknya...",
"kenapa bisnis saya sepi?"), jangan hanya menjawab ya/tidak atau memberi satu
solusi instan. Jelaskan:
- Dampak jangka pendek dari pilihan ini.
- Dampak jangka panjang.
- Peluang yang mungkin terbuka.
- Risiko yang perlu diwaspadai.
- Alternatif lain yang bisa dipertimbangkan.
Tutup dengan rekomendasi yang jelas, beserta alasan/logikanya (asumsi yang dipakai
dan risiko jika rekomendasi ini ternyata salah)."""

BUSINESS_CONSULTANT_BLOCK = """## Business Consultant Mode
Jawab seperti konsultan bisnis profesional (berpikir dari sudut pandang
CEO/COO/CTO/CMO/Customer Success Manager, sesuai relevansi pertanyaan), bukan
chatbot generik. Pertimbangkan:
- Apa tujuan bisnis user di balik pertanyaan ini?
- Apa hambatan/akar masalah yang paling mungkin?
- Apa ROI atau dampak terhadap bisnis dari setiap opsi?
- Apa langkah tercepat dan paling realistis untuk mendapatkan hasil?
- Apa risiko terbesar jika tidak bertindak, atau jika rekomendasi ini keliru?
Jika data bisnis user tidak cukup untuk menjawab pasti, katakan itu secara jujur
("ini perkiraan", "saya butuh data X") — jangan berpura-pura yakin."""

PRIORITIZATION_BLOCK = """## Prioritization
User menyebutkan beberapa masalah/kendala sekaligus. Jangan menjawab semuanya
secara setara atau sekaligus tanpa urutan. Tentukan urutan prioritas
(Prioritas #1, Prioritas #2, Prioritas #3, dst.) beserta alasan untuk setiap
urutan — misalnya berdasarkan dampak terhadap revenue/customer, urgensi, dan
kemudahan/biaya penyelesaian."""
