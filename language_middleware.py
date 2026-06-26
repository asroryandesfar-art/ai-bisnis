"""
Language Middleware — enforces agent language policy at every LLM call.

Priority order (highest first):
1. Explicit user instruction in current message ("answer in English", "jawab dalam bahasa Indonesia")
2. Agent language setting (bot.language)
3. Conversation-level detected language (passed from caller across turns)
4. Auto-detect from current message word set

Entry points
------------
resolve_language(user_message, agent_language, conversation_language) -> LangCode
    Returns the effective language code for this turn.

build_system_prompt(custom_prompt, chunks, language) -> str
    Returns a fully language-consistent system prompt with the enforcement
    directive at the top (high LLM weight) followed by the base persona,
    style guide, and KB context — all in the target language.

validate_output_language(text, expected, min_words) -> bool
    Heuristic check: returns True if text appears to be in the expected language.

language_enforcement_suffix(language) -> str
    Short appendix to add to the system prompt on a retry call when the first
    response was in the wrong language.
"""

from __future__ import annotations

import re
from typing import Literal

LangCode = Literal["en", "id"]

# ---------------------------------------------------------------------------
# Explicit-override patterns (matched against lowercased user message)
# ---------------------------------------------------------------------------
_OVERRIDE_PATTERNS: dict[str, list[str]] = {
    "en": [
        r"\banswer\s+in\s+english\b",
        r"\breply\s+in\s+english\b",
        r"\brespond\s+in\s+english\b",
        r"\bplease\s+(use|speak|write)\s+english\b",
        r"\bswitch\s+to\s+english\b",
        r"\buse\s+english\b",
        r"\benglish\s+(only|please)?\b",
        r"\bin\s+english\b",
    ],
    "id": [
        r"\bjawab\s+(dalam\s+)?bahasa\s+indonesia\b",
        r"\bgunakan\s+bahasa\s+indonesia\b",
        r"\bpakai\s+bahasa\s+indonesia\b",
        r"\bbahasa\s+indonesia\s+saja\b",
        r"\bganti\s+(ke\s+)?bahasa\s+indonesia\b",
        r"\bdalam\s+bahasa\s+indonesia\b",
    ],
}

# ---------------------------------------------------------------------------
# Language-indicator word sets (used for auto-detect and output validation)
# ---------------------------------------------------------------------------
_ID_WORDS: frozenset[str] = frozenset([
    "apa", "bagaimana", "kenapa", "mengapa", "saya", "kamu", "anda",
    "tidak", "bukan", "dan", "yang", "ini", "itu", "bisa", "ada",
    "untuk", "dengan", "atau", "ke", "di", "dari", "kami", "ya",
    "tolong", "mohon", "halo", "selamat", "terima", "kasih", "nama",
    "adalah", "akan", "sudah", "belum", "juga", "karena", "tapi",
    "kalau", "jika", "apakah", "boleh", "minta", "bantu", "jelaskan",
    "berikan", "ceritakan", "kira", "sekitar", "tentang", "bahwa",
    "namun", "tetapi", "sedangkan", "kemudian", "selain", "setelah",
    "sebelum", "antara", "setiap", "tersebut", "mereka", "kami",
    "sehingga", "seperti", "lebih", "sangat", "juga", "serta",
])
_EN_WORDS: frozenset[str] = frozenset([
    "what", "how", "why", "the", "is", "are", "can", "you", "and",
    "or", "to", "in", "with", "do", "does", "please", "help", "tell",
    "me", "my", "we", "your", "our", "have", "has", "been", "will",
    "would", "could", "should", "it", "that", "this", "a", "an",
    "of", "for", "be", "was", "were", "if", "when", "where", "who",
    "which", "give", "explain", "provide", "describe", "show", "find",
    "want", "need", "get", "use", "make", "see", "know", "go",
    "about", "just", "also", "more", "than", "then", "there", "here",
    "so", "but", "however", "therefore", "because", "since", "while",
    "after", "before", "between", "every", "some", "any", "all",
])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_language(
    user_message: str,
    agent_language: str | None = None,
    conversation_language: str | None = None,
) -> LangCode:
    """
    Return the effective language code for this turn.

    Falls back through:
      explicit override in message → agent setting → conversation memory → auto-detect
    """
    text = (user_message or "").lower()

    # Priority 1: explicit override
    for lang, patterns in _OVERRIDE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                return lang  # type: ignore[return-value]

    # Priority 2: agent language setting
    if agent_language in ("en", "id"):
        return agent_language  # type: ignore[return-value]

    # Priority 3: conversation memory
    if conversation_language in ("en", "id"):
        return conversation_language  # type: ignore[return-value]

    # Priority 4: auto-detect
    return detect_language(text)


def detect_language(text: str) -> LangCode:
    """Heuristic: compare hit count on Indonesian vs English word sets."""
    words = set(re.findall(r"\b[a-z]{2,}\b", text.lower()))
    id_score = len(words & _ID_WORDS)
    en_score = len(words & _EN_WORDS)
    # Lean toward Indonesian when tied (default locale assumption)
    return "en" if en_score > id_score else "id"


def validate_output_language(
    text: str,
    expected: LangCode,
    min_words: int = 8,
) -> bool:
    """
    Return True if *text* appears to be in *expected* language.
    Short responses (< min_words) are always considered valid to avoid
    false-positive retries on brief acknowledgements.
    """
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    if len(words) < min_words:
        return True  # too short to classify confidently
    return detect_language(text) == expected


def build_system_prompt(
    custom_prompt: str | None,
    chunks: list[dict],
    language: LangCode,
) -> str:
    """
    Build a fully language-consistent system prompt.

    The language-enforcement directive appears at the VERY TOP so it has
    maximum weight in the LLM's context window, followed by the tenant's
    base persona, the style guide, and the KB context — all in the target
    language.
    """
    if language == "en":
        lang_directive = (
            "LANGUAGE RULE: You MUST respond in English only, regardless of what language "
            "the user writes in. Never switch to Indonesian or any other language. "
            "Every word of your response must be in English."
        )
        base_default = (
            "You are a helpful, polite, and professional AI assistant. "
            "Prioritize the tenant's knowledge base. If context is incomplete, "
            "answer to the best of your ability, ask for clarification if needed, "
            "and only offer human handoff for cases that truly require the human team."
        )
        style_guide = (
            "## Response style\n"
            "Write answers like a modern AI assistant (similar to Claude/ChatGPT): "
            "clear, concise, and direct, but friendly and natural — not robotic.\n"
            "- Lead with the answer or key information, then add supporting details.\n"
            "- Use short paragraphs (1–3 sentences). Separate different ideas with a new line.\n"
            "- For multiple points, steps, or options, use a numbered list or bullet (`-`), "
            "not one long paragraph.\n"
            "- Use **bold text** to highlight terms, product names, prices, or important items.\n"
            "- Avoid excessive filler, repetition, or generic openers like "
            '"Sure, I will help you...". A brief greeting at the start of a conversation is enough.\n'
            "- Match answer length to question complexity: brief for simple questions, "
            "fuller explanation with clear structure for complex ones."
        )
        if chunks:
            kb_header = "\n\n## Context from knowledge base:\n"
            kb_footer = (
                "\n\nKnowledge-first instruction: use the knowledge sources above as your primary basis. "
                "If sources are insufficient, answer best-effort and distinguish knowledge-base "
                "information from general assumptions. Do not immediately offer human handoff just "
                "because sources are incomplete; ask for clarification if needed."
            )
        else:
            kb_header = kb_footer = ""
    else:  # "id"
        lang_directive = (
            "ATURAN BAHASA: Kamu HARUS menjawab dalam Bahasa Indonesia saja, apa pun bahasa yang "
            "digunakan pengguna. Jangan beralih ke bahasa Inggris atau bahasa lain. "
            "Setiap kata dalam jawabanmu harus dalam Bahasa Indonesia."
        )
        base_default = (
            "Kamu adalah asisten AI yang helpful, sopan, dan profesional. "
            "Prioritaskan knowledge base tenant dan agent ini. Kalau konteks kurang lengkap, "
            "jawab best effort, minta klarifikasi bila perlu, dan baru tawarkan human handoff "
            "untuk kasus yang memang butuh tim manusia."
        )
        style_guide = (
            "## Gaya jawaban\n"
            "Tulis jawaban dengan gaya seperti asisten AI modern (mirip Claude/ChatGPT): jelas, "
            "ringkas, dan langsung ke inti, tapi tetap ramah dan natural — bukan kaku seperti robot.\n"
            "- Buka dengan jawaban atau inti informasi yang dicari user, baru tambahkan detail pendukung.\n"
            "- Gunakan paragraf pendek (1–3 kalimat). Pisahkan ide berbeda dengan baris baru.\n"
            "- Kalau menjelaskan beberapa poin, langkah, atau opsi, gunakan daftar bernomor atau "
            "bullet (`-`), jangan digabung jadi satu paragraf panjang.\n"
            "- Gunakan **teks tebal** untuk menyorot istilah, nama produk, harga, atau hal penting.\n"
            "- Hindari basa-basi berlebihan, pengulangan, dan kalimat pembuka generik seperti "
            '"Tentu, saya akan membantu...". Sapaan singkat di awal percakapan sudah cukup.\n'
            "- Sesuaikan panjang jawaban: pertanyaan sederhana dijawab singkat, pertanyaan kompleks "
            "dijelaskan lebih lengkap dengan struktur yang rapi."
        )
        if chunks:
            kb_header = "\n\n## Konteks dari knowledge base:\n"
            kb_footer = (
                "\n\nInstruksi knowledge-first: gunakan sumber knowledge di atas sebagai dasar utama. "
                "Jika sumber belum cukup, jawab best effort dan bedakan informasi dari knowledge dengan "
                "asumsi umum. Jangan langsung human handoff hanya karena sumber tidak lengkap; "
                "tanyakan klarifikasi jika perlu."
            )
        else:
            kb_header = kb_footer = ""

    base = custom_prompt or base_default

    context = ""
    if chunks:
        context = kb_header
        context += "\n---\n".join(c["content"][:800] for c in chunks)
        context += kb_footer

    return f"{lang_directive}\n\n{base}\n\n{style_guide}{context}"


def language_enforcement_suffix(language: LangCode) -> str:
    """
    Suffix appended to the system prompt on a retry when the first response
    was detected to be in the wrong language.
    """
    if language == "en":
        return (
            "\n\n[CRITICAL REMINDER: Your previous response was not in English. "
            "You MUST respond entirely in English. Do not use any Indonesian words.]"
        )
    return (
        "\n\n[PENGINGAT KRITIS: Jawaban sebelumnya bukan dalam Bahasa Indonesia. "
        "Kamu HARUS menjawab sepenuhnya dalam Bahasa Indonesia. Jangan gunakan kata-kata bahasa Inggris.]"
    )
