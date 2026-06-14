"""
long_term_planner_engine.py — Long-Term Planner untuk BotNesia.

Modul ini TIDAK memanggil LLM. Mendeteksi (heuristik/regex) pertanyaan tentang
rencana/roadmap bisnis jangka panjang dan menyediakan blok instruksi ("style
guidance") yang digabungkan ke `knowledge_base_context` oleh
`reasoning_controller.ReasoningController.analyze()`. Melengkapi (bukan
menggantikan) bullet jangka pendek/panjang yang sudah ada di
`business_consultant_engine.STRATEGIC_THINKING_BLOCK` dengan struktur milestone
yang lebih rinci.
"""
from __future__ import annotations

import re


LONG_TERM_PLANNING_PATTERN = re.compile(
    r"rencana\s+(jangka\s+panjang|bisnis|pengembangan|ekspansi|pertumbuhan|ke\s*depan)|"
    r"roadmap|"
    r"growth\s*plan|"
    r"rencana\s+\d+\s*(bulan|tahun)|"
    r"target\s+\d+\s*(bulan|tahun)|"
    r"(scaling|skalakan|skala\s*bisnis)",
    re.IGNORECASE,
)


def is_long_term_planning_question(text: str) -> bool:
    """True jika pesan menanyakan rencana/roadmap bisnis jangka panjang."""
    return bool(LONG_TERM_PLANNING_PATTERN.search(text or ""))


# ============================================================
# STYLE GUIDANCE
# ============================================================

LONG_TERM_PLANNER_BLOCK = """## Long-Term Planner
Susun jawaban sebagai rencana bertahap dengan milestone:
- Jangka Pendek (0-1 bulan): langkah cepat yang bisa segera dijalankan.
- Jangka Menengah (1-3 bulan): langkah yang butuh persiapan/pengujian.
- Jangka Panjang (3-12 bulan): langkah strategis/struktural.
Untuk setiap fase, sebutkan dependensi (apa yang harus selesai dulu sebelum
fase ini bisa berjalan) dan metrik keberhasilan yang bisa dipakai user untuk
mengukur progres."""
