"""
reasoning_controller.py — Reasoning Engine & Context-Aware Follow Up untuk BotNesia.

`ReasoningController.analyze()` adalah pemeriksaan ringan (tanpa LLM, jadi tidak
menambah latensi/biaya) yang dijalankan di awal `SupervisorAgent._process()`
untuk setiap pesan. Tujuannya menjawab pertanyaan internal sebelum CSAgent
menulis jawaban:

1. Apa intent utama user? (umum / perbandingan / self-awareness / follow-up /
   strategi bisnis)
2. Apakah ini follow-up singkat ("kenapa?", "maksudnya?") yang harus dijawab
   dengan melanjutkan konteks sebelumnya, bukan topik baru?
3. Apakah pertanyaan ini menyentuh identitas/posisi BotNesia (perlu Self
   Identity Engine + Comparison Engine + Truthfulness/Sales Control Policy)?
4. Apakah ada risiko overclaim (mis. "lebih pintar dari Claude")?
5. Apakah ini pertanyaan keputusan/strategi bisnis user (mis. "haruskah saya
   menurunkan harga?", "kenapa bisnis saya sepi?") yang perlu Strategic
   Thinking + Business Consultant Mode, dan jika user menyebut beberapa
   masalah sekaligus, Prioritization?

Hasilnya berupa `reasoning_brief` dict yang disimpan di
`context["_reasoning_brief"]`, dan `style_guidance` (teks instruksi tambahan)
yang digabungkan ke `knowledge_base_context` sehingga CSAgent (Standard & Pro)
otomatis mengikuti Truthfulness Policy, Sales Control Policy, Comparison Engine,
Self Identity Engine, Strategic Thinking, dan Business Consultant Mode tanpa
mengubah arsitektur pipeline.
"""
from __future__ import annotations

import re

from business_consultant_engine import (
    BUSINESS_CONSULTANT_BLOCK,
    PRIORITIZATION_BLOCK,
    STRATEGIC_THINKING_BLOCK,
    has_multiple_problems,
    is_business_strategy_question,
)
from identity_agent import (
    CORE_POLICY_BLOCK,
    FOLLOWUP_CONTEXT_NOTE,
    IdentityAgent,
    is_comparison_question,
    is_self_awareness_question,
)
from knowledge_access_engine import (
    REALTIME_KNOWLEDGE_BLOCK,
    SOURCE_VERIFICATION_BLOCK,
    select_knowledge_sources,
)


# Pesan follow-up singkat yang harus dijawab dengan melanjutkan konteks
# sebelumnya, bukan dianggap sebagai topik baru.
FOLLOWUP_PATTERN = re.compile(
    r"^(kenapa|mengapa|maksudnya|maksud(nya)?|gimana|bagaimana|bedanya|terus|trus|"
    r"lalu|lanjut|terus\s*gimana|lalu\s*gimana|kok\s*bisa|kenapa\s*begitu|kenapa\s*gitu)"
    r"(\s+(sih|dong|ya|nya|begitu|gitu|tuh))?[\?\!\.\s]*$",
    re.IGNORECASE,
)

# Batas panjang pesan agar dianggap follow-up singkat (mencegah pertanyaan
# baru yang kebetulan diawali "kenapa" ikut dianggap follow-up).
MAX_FOLLOWUP_LEN = 30

# Frasa yang menandakan risiko overclaim ("lebih pintar dari ...").
_OVERCLAIM_HINTS = (
    "lebih pintar",
    "lebih hebat",
    "lebih canggih",
    "lebih unggul",
    "lebih baik dari",
    "lebih kuat dari",
)


class ReasoningController:
    """Reasoning Engine ringan (heuristik, tanpa LLM tambahan).

    Dipanggil sekali di awal pipeline (`SupervisorAgent._process()`, setelah
    `MemoryAgent.enrich_context`). Tidak memanggil LLM sehingga tidak
    menambah latensi/biaya — cukup untuk memutuskan gaya jawaban dan blok
    kebijakan apa yang perlu disisipkan ke `knowledge_base_context`.
    """

    name = "reasoning_controller"

    def __init__(self, identity_agent: IdentityAgent | None = None):
        self.identity_agent = identity_agent or IdentityAgent()

    def analyze(self, context: dict) -> dict:
        text = (context.get("user_message") or "").strip()
        lower = text.lower()
        history = context.get("messages") or []
        has_history = bool(history)
        knowledge_routing = select_knowledge_sources(text, history)

        is_comparison = is_comparison_question(lower)
        is_self_awareness = is_self_awareness_question(lower)
        is_meta = is_comparison or is_self_awareness

        normalized = lower.strip("?!. \t")
        is_followup = (
            has_history
            and len(lower) <= MAX_FOLLOWUP_LEN
            and bool(FOLLOWUP_PATTERN.match(normalized))
        )

        multiple_problems = has_multiple_problems(text)
        is_business_strategy = (not is_meta) and (
            is_business_strategy_question(lower) or multiple_problems
        )
        needs_prioritization = is_business_strategy and multiple_problems

        if is_comparison:
            intent_type = "comparison"
        elif is_self_awareness:
            intent_type = "self_awareness"
        elif is_followup:
            intent_type = "followup"
        elif is_business_strategy:
            intent_type = "business_strategy"
        else:
            intent_type = "general"

        overclaim_risk = is_comparison or any(hint in lower for hint in _OVERCLAIM_HINTS)
        needs_honesty_emphasis = is_meta

        blocks = [CORE_POLICY_BLOCK, SOURCE_VERIFICATION_BLOCK]
        if is_meta:
            blocks.append(self.identity_agent.identity_block())
            blocks.append(self.identity_agent.truthfulness_policy())
            blocks.append(self.identity_agent.sales_control_policy())
            blocks.append(self.identity_agent.comparison_format())
        if is_followup:
            blocks.append(FOLLOWUP_CONTEXT_NOTE)
        if is_business_strategy:
            blocks.append(STRATEGIC_THINKING_BLOCK)
            blocks.append(BUSINESS_CONSULTANT_BLOCK)
            if needs_prioritization:
                blocks.append(PRIORITIZATION_BLOCK)
        if knowledge_routing.get("needs_fresh_data"):
            blocks.append(REALTIME_KNOWLEDGE_BLOCK)

        return {
            "intent_type": intent_type,
            "is_meta": is_meta,
            "is_comparison": is_comparison,
            "is_self_awareness": is_self_awareness,
            "is_followup": is_followup,
            "is_business_strategy": is_business_strategy,
            "needs_prioritization": needs_prioritization,
            "needs_honesty_emphasis": needs_honesty_emphasis,
            "overclaim_risk": overclaim_risk,
            "knowledge_routing": knowledge_routing,
            "style_guidance": "\n\n".join(blocks),
        }
