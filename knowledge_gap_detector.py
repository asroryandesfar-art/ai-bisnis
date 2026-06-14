"""
knowledge_gap_detector.py — Knowledge Gap Detector untuk BotNesia.

Modul ini TIDAK memanggil LLM. Mendeteksi (heuristik) apakah hybrid search
knowledge base tenant (`main._retrieve_chunks`, dilaporkan via
`context["kb_chunks_count"]`) tidak menemukan apa pun untuk pertanyaan yang
tampaknya butuh info spesifik tenant (bukan pertanyaan meta/identitas BotNesia,
bukan pertanyaan akun/billing, dan bukan pertanyaan freshness yang sudah
ditangani Real-Time Knowledge Layer) — lalu menyediakan blok instruksi ("style
guidance") yang mendorong CSAgent jujur soal keterbatasan data dan menyarankan
tenant melengkapi knowledge base via Knowledge Builder.
"""
from __future__ import annotations

import re

from identity_agent import is_meta_question


_GREETING_PATTERN = re.compile(
    r"^\s*(hai+|halo+|hello|hi+|p(agi|siang|sore)|malam|"
    r"terima\s*kasih|thanks|makasih|thx|ok(e|ay)?|baik|sip|siap|tes|test)\W*$",
    re.IGNORECASE,
)

# Pesan yang sangat singkat tidak dianggap "butuh info spesifik tenant".
_MIN_LEN_FOR_GAP = 8


def detect_knowledge_gap(text: str, kb_chunks_count: int, knowledge_routing: dict | None = None) -> dict:
    """Deteksi apakah knowledge base tenant kosong untuk pertanyaan ini.

    Returns: {"knowledge_gap_detected": bool}
    """
    routing = knowledge_routing or {}
    reasons = routing.get("reasons", {})
    raw = (text or "").strip()

    gap = (
        int(kb_chunks_count or 0) == 0
        and len(raw) >= _MIN_LEN_FOR_GAP
        and not _GREETING_PATTERN.match(raw)
        and not is_meta_question(raw)
        and not routing.get("needs_fresh_data")
        and "self_knowledge" not in reasons
    )
    return {"knowledge_gap_detected": gap}


# ============================================================
# STYLE GUIDANCE
# ============================================================

KNOWLEDGE_GAP_BLOCK = """## Knowledge Gap Terdeteksi
Tidak ditemukan dokumen/FAQ/SOP spesifik tenant di knowledge base untuk
pertanyaan ini. Sesuai Truthfulness Policy:
- Katakan bahwa ini jawaban umum/berdasarkan pengetahuan umum, bukan dari
  dokumen spesifik bisnis ini.
- Jangan mengarang detail seolah berasal dari data/dokumen tenant (nama
  produk, harga, kebijakan, dll. yang tidak ada di konteks).
- Jika relevan, sarankan tenant melengkapi knowledge base (upload
  dokumen/FAQ/SOP via Knowledge Builder) agar jawaban berikutnya lebih akurat
  untuk bisnis ini."""
