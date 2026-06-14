"""
anti_hallucination_engine.py — Anti-Hallucination Engine untuk BotNesia.

Modul ini TIDAK memanggil LLM. Dua kontribusi:
1. `ANTI_HALLUCINATION_BLOCK` — blok instruksi "always-on" (seperti
   `knowledge_access_engine.SOURCE_VERIFICATION_BLOCK`) yang mengingatkan
   CSAgent untuk tidak mengarang angka/tanggal/fakta dan menghindari kata-kata
   mutlak tanpa dasar.
2. `score_hallucination_risk()` — pemeriksaan heuristik PASCA-jawaban (mirip
   `verification_agent.score_meta_answer`, tapi untuk SEMUA jawaban bukan
   hanya pertanyaan meta): mendeteksi klaim angka/statistik yang tidak muncul
   di `knowledge_base_context`/hasil spesialis, dan bahasa "pasti"/"dijamin"
   tanpa kualifikasi. Dipakai oleh `verification_agent.VerificationAgent` untuk
   memicu satu kali penulisan ulang jawaban (mekanisme retry yang sudah ada).
"""
from __future__ import annotations

import re


# Frasa kepastian absolut tanpa kualifikasi — risiko overconfidence/hallucination.
ABSOLUTE_CERTAINTY_PHRASES = (
    "pasti",
    "dijamin",
    "100%",
    "selalu",
    "tidak pernah",
    "tanpa kecuali",
    "tidak mungkin salah",
    "dapat dipastikan",
)

# Kata-kata kualifikasi/kehati-hatian — kehadirannya menurunkan risiko
# overconfidence (jawaban tidak menyatakan sesuatu sebagai fakta mutlak).
HEDGE_PHRASES = (
    "kemungkinan",
    "mungkin",
    "tergantung",
    "belum yakin",
    "belum tentu",
    "saat ini",
    "untuk saat ini",
    "bisa jadi",
    "relatif",
    "perkiraan",
    "estimasi",
)

# Klaim angka/statistik/finansial yang spesifik — pola yang "berbahaya" jika
# dikarang (persentase, nominal rupiah, "X juta/ribu/persen").
_CLAIM_NUMBER_PATTERN = re.compile(
    r"(?:rp\s?[\d.,]+|\d+(?:[.,]\d+)?\s?%|\d+(?:[.,]\d+)?\s?"
    r"(?:persen|juta|ribu|miliar|milyar))",
    re.IGNORECASE,
)


def score_hallucination_risk(
    answer: str, knowledge_base_context: str = "", specialist_results: dict | None = None
) -> dict:
    """Heuristik risiko hallucination untuk SEMUA jawaban (bukan hanya meta).

    Returns: {
        "risk_score": 0-100,
        "unsupported_claims": [...],
        "overconfidence_hits": int,
        "needs_rewrite": bool,
    }
    """
    text = answer or ""
    lower = text.lower()

    context_text = knowledge_base_context or ""
    specialist_blocks: list[str] = []
    for out in (specialist_results or {}).values():
        if isinstance(out, dict):
            conclusion = out.get("conclusion")
            if conclusion:
                specialist_blocks.append(str(conclusion))
    combined_context = (context_text + "\n" + "\n".join(specialist_blocks)).lower()

    overconfidence_hits = sum(1 for p in ABSOLUTE_CERTAINTY_PHRASES if p in lower)
    hedge_hits = sum(1 for p in HEDGE_PHRASES if p in lower)

    unsupported_claims: list[str] = []
    for match in _CLAIM_NUMBER_PATTERN.finditer(text):
        token = match.group(0)
        normalized = re.sub(r"\s+", " ", token.strip().lower())
        if normalized and normalized not in combined_context:
            unsupported_claims.append(token.strip())

    risk_score = 0
    if overconfidence_hits and not hedge_hits:
        risk_score += overconfidence_hits * 30
    risk_score += min(40, len(unsupported_claims) * 20)
    risk_score = max(0, min(100, risk_score))

    needs_rewrite = (overconfidence_hits >= 1 and hedge_hits == 0) or len(unsupported_claims) >= 2

    return {
        "risk_score": risk_score,
        "unsupported_claims": unsupported_claims[:5],
        "overconfidence_hits": overconfidence_hits,
        "needs_rewrite": needs_rewrite,
    }


# ============================================================
# STYLE GUIDANCE — always-on
# ============================================================

ANTI_HALLUCINATION_BLOCK = """## Anti-Hallucination
Jangan mengarang angka, tanggal, nama produk/fitur, atau statistik yang tidak
ada di konteks (knowledge base, hasil analisis spesialis, atau data yang
diberikan). Jika perlu menyebut angka/statistik yang tidak ada di konteks,
katakan itu perkiraan/ilustrasi, bukan data pasti. Hindari kata-kata mutlak
("pasti", "dijamin", "100%", "selalu", "tidak pernah", "tanpa kecuali") kecuali
benar-benar didukung oleh data di konteks — gunakan kualifikasi yang jujur
("kemungkinan", "berdasarkan data saat ini", "perkiraan")."""
