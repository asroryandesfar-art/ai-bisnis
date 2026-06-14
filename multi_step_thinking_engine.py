"""
multi_step_thinking_engine.py — Multi-Step Thinking Engine untuk BotNesia.

Modul ini TIDAK memanggil LLM. Mendeteksi (heuristik) apakah pesan user berisi
beberapa sub-pertanyaan/topik sekaligus, dan menyediakan blok instruksi ("style
guidance") yang mendorong CSAgent (jalur Standard) menjawab tiap sub-pertanyaan
secara terpisah lalu menutup dengan kesimpulan — bukan menjawab semuanya
sebagai satu blok yang menyatu. Mode Pro sudah punya planner/lenses untuk
dekomposisi; blok ini melengkapi jalur Standard.
"""
from __future__ import annotations

import re


_QUESTION_WORD_PATTERN = re.compile(
    r"\b(apa|apakah|bagaimana|gimana|kapan|berapa|kenapa|mengapa|siapa|"
    r"dimana|di\s*mana|mana)\b",
    re.IGNORECASE,
)

_SEGMENT_SPLIT_PATTERN = re.compile(
    r",|;|\bdan\b|\bjuga\b|\bselain\s+itu\b|\blalu\b|\bserta\b",
    re.IGNORECASE,
)


def count_sub_questions(text: str) -> int:
    """Perkiraan jumlah sub-pertanyaan dalam pesan (untuk Reflection Engine)."""
    raw = text or ""
    question_marks = raw.count("?")
    segments = [s for s in _SEGMENT_SPLIT_PATTERN.split(raw) if s.strip()]
    question_segments = sum(1 for s in segments if _QUESTION_WORD_PATTERN.search(s))
    return max(question_marks, question_segments)


def is_multi_step_question(text: str) -> bool:
    """True jika pesan berisi >=2 sub-pertanyaan/topik sekaligus."""
    return count_sub_questions(text) >= 2


# ============================================================
# STYLE GUIDANCE
# ============================================================

MULTI_STEP_THINKING_BLOCK = """## Multi-Step Thinking
Pertanyaan ini berisi beberapa sub-pertanyaan/topik sekaligus. Jangan
menjawabnya sebagai satu blok jawaban yang menyatu:
- Identifikasi setiap sub-pertanyaan secara terpisah.
- Jawab masing-masing sub-pertanyaan secara ringkas dan jelas (boleh berupa
  poin/daftar bernomor).
- Tutup dengan kesimpulan singkat yang menghubungkan jawaban-jawaban tersebut,
  jika relevan."""
