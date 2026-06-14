"""
reflection_engine.py — Reflection Engine untuk BotNesia.

Modul ini TIDAK memanggil LLM. Setelah `cs_answer` final tersedia (jalur
Standard maupun Pro), `reflect()` melakukan pemeriksaan "self-check" heuristik:
apakah jawaban benar-benar memenuhi instruksi style guidance yang sudah
dipicu oleh `reasoning_brief` (Prioritization, Risk Assessment, Root Cause,
Multi-Step Thinking). Hasilnya (`penalty`/`notes`) dibaca oleh
`uncertainty_engine.assess()` sebagai sinyal tambahan untuk confidence
banding — TIDAK memicu rewrite/retry LLM tambahan.
"""
from __future__ import annotations

import re

from verification_agent import REASONING_CONNECTORS


_PRIORITY_PATTERN = re.compile(r"prioritas\s*#?\s*\d|priority\s*#?\s*\d", re.IGNORECASE)

_RISK_WORD_PATTERN = re.compile(
    r"risiko|risk|alternatif|opsi\s+lain|pilihan\s+lain|downside|trade-?off",
    re.IGNORECASE,
)

_LIST_ITEM_PATTERN = re.compile(r"^\s*([-*•]|\d+[.\)])\s+", re.MULTILINE)


def _answer_structure_count(text: str) -> int:
    """Perkiraan jumlah "unit jawaban" (item daftar atau paragraf)."""
    items = len(_LIST_ITEM_PATTERN.findall(text))
    if items:
        return items
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return max(1, len(paragraphs))


def reflect(answer: str, reasoning_brief: dict | None = None, specialist_outputs: dict | None = None) -> dict:
    """Self-check heuristik atas `answer` terhadap `reasoning_brief`.

    Returns: {"self_check_passed": bool, "notes": [...], "penalty": int}
    """
    brief = reasoning_brief or {}
    text = answer or ""
    lower = text.lower()
    notes: list[str] = []
    penalty = 0

    if brief.get("needs_prioritization") and not _PRIORITY_PATTERN.search(lower):
        notes.append(
            "Pertanyaan menyebut beberapa masalah, tapi jawaban tidak memberi "
            "urutan prioritas (Prioritas #1/#2/...)."
        )
        penalty += 8

    if (brief.get("is_business_strategy") or brief.get("needs_risk_assessment")) and not _RISK_WORD_PATTERN.search(lower):
        notes.append("Jawaban strategi bisnis tidak membahas risiko/alternatif.")
        penalty += 6

    if brief.get("is_root_cause") and not any(c in lower for c in REASONING_CONNECTORS):
        notes.append(
            "Pertanyaan menanyakan akar masalah, tapi jawaban tidak punya alur "
            "sebab-akibat yang jelas."
        )
        penalty += 6

    multi_step_count = int(brief.get("multi_step_count") or 0)
    if brief.get("is_multi_step") and multi_step_count >= 2:
        structure_count = _answer_structure_count(text)
        if structure_count < multi_step_count:
            notes.append(
                "Pertanyaan berisi beberapa sub-pertanyaan, tapi jawaban tidak "
                "terstruktur per sub-pertanyaan."
            )
            penalty += 5

    return {
        "self_check_passed": penalty == 0,
        "notes": notes,
        "penalty": penalty,
    }
