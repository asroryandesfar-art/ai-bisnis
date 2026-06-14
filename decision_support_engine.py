"""
decision_support_engine.py — Root Cause Analysis, Trade-Off Engine, dan Risk
Assessment Agent untuk BotNesia.

Modul ini TIDAK memanggil LLM. Seperti `business_consultant_engine.py`, modul
ini hanya mendeteksi (heuristik/regex) jenis pertanyaan dan menyediakan blok
instruksi ("style guidance") yang digabungkan ke `knowledge_base_context` oleh
`reasoning_controller.ReasoningController.analyze()`.
"""
from __future__ import annotations

import re

from identity_agent import COMPETITOR_PATTERN


# ============================================================
# DETEKSI
# ============================================================

ROOT_CAUSE_PATTERN = re.compile(
    r"(kenapa|mengapa)\s+.*(terjadi|bisa|sering|selalu|terus|gagal|error|rusak)|"
    r"apa\s+(akar\s+masalah|sebab|penyebab|root\s*cause)|"
    r"akar\s+masalah|"
    r"penyebab\s+(utama|sebenarnya|nya)",
    re.IGNORECASE,
)

# Perbandingan ANTAR OPSI BISNIS ("pilih A atau B"). Sengaja dipisah dari
# `identity_agent.COMPETITOR_PATTERN` (perbandingan BotNesia vs AI lain) —
# pertanyaan yang menyebut AI lain dikecualikan agar tidak tumpang tindih.
TRADE_OFF_PATTERN = re.compile(
    r"(pilih|memilih|milih)\s+.+\s+(atau|vs|versus)\s+|"
    r"mending\s+.+\s+(atau|apa)|"
    r"lebih\s+(baik|bagus|untung|cocok|worth\s*it)\s+.+\s+"
    r"(atau|dibandingkan|dibanding|daripada|ketimbang)|"
    r"(dibandingkan|dibanding|daripada|ketimbang)\s+",
    re.IGNORECASE,
)

RISK_KEYWORD_PATTERN = re.compile(
    r"risiko|risk|bahaya|downside|worst\s*case|kerugian\s+(jika|kalau)",
    re.IGNORECASE,
)


def is_root_cause_question(text: str) -> bool:
    """True jika pesan menanyakan SEBAB/akar masalah, bukan hanya gejalanya."""
    return bool(ROOT_CAUSE_PATTERN.search(text or ""))


def is_trade_off_question(text: str) -> bool:
    """True jika pesan membandingkan opsi/keputusan bisnis (bukan vs AI lain)."""
    raw = text or ""
    if COMPETITOR_PATTERN.search(raw):
        return False
    return bool(TRADE_OFF_PATTERN.search(raw))


def needs_risk_assessment(text: str, is_business_strategy: bool = False) -> bool:
    """True jika perlu Risk Assessment terstruktur (probability x impact)."""
    if is_business_strategy:
        return True
    return bool(RISK_KEYWORD_PATTERN.search(text or ""))


# ============================================================
# STYLE GUIDANCE
# ============================================================

ROOT_CAUSE_BLOCK = """## Root Cause Analysis
Pertanyaan ini menanyakan SEBAB/akar masalah, bukan hanya gejalanya. Sebelum
menjawab:
- Pisahkan gejala (symptom) dari kemungkinan akar masalah (root cause) — jangan
  menyamakan keduanya.
- Sebutkan 2-3 kandidat penyebab yang paling mungkin, urutkan dari yang paling
  mungkin ke yang kurang mungkin.
- Jika suatu kandidat hanya berkorelasi (bukan benar-benar menyebabkan),
  katakan itu secara jujur — jangan menyimpulkan kausalitas tanpa dasar.
- Sarankan cara memvalidasi tiap kandidat dengan data (mis. cek log, cek
  feedback pelanggan, A/B test) sebelum mengambil tindakan besar."""

TRADE_OFF_BLOCK = """## Trade-Off Analysis
User membandingkan beberapa opsi/keputusan. Untuk setiap opsi:
- Sebutkan kelebihan (pros) dan kekurangan (cons) secara seimbang.
- Beri rekomendasi yang jelas berdasarkan informasi yang tersedia, dengan
  alasan/asumsi yang dipakai.
- Sebutkan kondisi apa yang bisa MENGUBAH rekomendasi ini (mis. "jika budget
  terbatas, pilih X; jika prioritas growth, pilih Y")."""

RISK_ASSESSMENT_BLOCK = """## Risk Assessment
Sertakan penilaian risiko terstruktur untuk keputusan ini: untuk setiap risiko
utama, sebutkan perkiraan kemungkinan terjadi (Low/Medium/High) dan dampaknya
jika terjadi (Low/Medium/High), beserta langkah mitigasi yang realistis. Jangan
hanya menyebut "ada risiko" tanpa menjelaskan seberapa besar dan bagaimana
menanganinya."""
