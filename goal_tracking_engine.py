"""
goal_tracking_engine.py — Goal Tracking Engine untuk BotNesia.

Modul ini TIDAK memanggil LLM. Seperti `business_consultant_engine.py`, modul
ini hanya mendeteksi (heuristik/regex) apakah user menyatakan target/tujuan
bisnis pada pesan ini, atau apakah profil user (lewat `memory_agent`) sudah
menyimpan target bisnis ("business_goal") dari percakapan sebelumnya — lalu
menyediakan blok instruksi ("style guidance") yang digabungkan ke
`knowledge_base_context` oleh `reasoning_controller.ReasoningController.analyze()`.

Tujuan: BotNesia mengingat target bisnis user (mis. "naikkan omzet 20% dalam 3
bulan") dan mengaitkan jawaban-jawaban berikutnya dengan target itu — bukan
hanya menjawab pertanyaan yang berdiri sendiri.
"""
from __future__ import annotations

import re


GOAL_STATEMENT_PATTERN = re.compile(
    r"target\s+(saya|kami|bisnis|kita)|"
    r"tujuan\s+(saya|kami|bisnis|kita)|"
    r"goal\s+(saya|kami)|"
    r"(ingin|mau|pengen)\s+"
    r"(mencapai|menaikkan|menambah|meningkatkan|menggandakan|menggenjot|mendongkrak)"
    r"\b.*(bulan|minggu|tahun|persen|%|omzet|omset|revenue|pelanggan|customer)",
    re.IGNORECASE,
)

# Key fakta yang dipakai memory_agent untuk menyimpan target bisnis user
# (lihat memory_agent.MemoryAgent.system_prompt).
BUSINESS_GOAL_FACT_KEY = "business_goal"


def is_goal_statement(text: str) -> bool:
    """True jika pesan ini menyatakan target/tujuan bisnis user."""
    return bool(GOAL_STATEMENT_PATTERN.search(text or ""))


def has_tracked_goal(knowledge_base_context: str) -> bool:
    """True jika profil user menyimpan target bisnis dari sesi sebelumnya.

    `memory_agent.UserProfile.to_context_string()` menyisipkan setiap fact
    sebagai baris "- <key>: <value> (confidence: ...)" ke
    `knowledge_base_context` — cek kemunculan key `business_goal` di sana.
    """
    return BUSINESS_GOAL_FACT_KEY in (knowledge_base_context or "")


# ============================================================
# STYLE GUIDANCE
# ============================================================

GOAL_TRACKING_BLOCK = """## Goal Tracking
User menyatakan target/tujuan bisnis pada pesan ini. Akui target tersebut secara
eksplisit dalam jawaban, dan kaitkan rekomendasi/jawaban dengan target itu —
apakah langkah yang dibahas mendukung pencapaian target tersebut, dan dalam
timeframe apa. Jika relevan, sebutkan metrik yang bisa dipakai user untuk
memantau progres ke arah target tersebut."""

TRACKED_GOAL_BLOCK = """## Goal Tracking (target tersimpan)
Profil user menyimpan target/tujuan bisnis dari percakapan sebelumnya (lihat
fakta "business_goal" di konteks "Informasi yang diketahui tentang user ini").
Jika relevan dengan pertanyaan saat ini, kaitkan jawaban dengan target tersebut
— misalnya apakah langkah yang dibahas mendukung atau berisiko mengganggu
pencapaian target itu."""
