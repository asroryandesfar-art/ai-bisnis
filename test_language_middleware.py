"""
Tests for language_middleware.

Covers:
- resolve_language: explicit override, agent setting, conversation memory, auto-detect
- detect_language: heuristic word-ratio
- validate_output_language: output language check
- build_system_prompt: language directive placement and content
- language_enforcement_suffix: suffix content

Required 4 scenarios from ticket:
  1. Language=en, Question=en → Expected=en
  2. Language=id, Question=id → Expected=id
  3. Language=en, Question=id → Expected=en (agent setting wins over message language)
  4. Language=id, Question=en → Expected=id (agent setting wins over message language)
"""

import pytest
from language_middleware import (
    resolve_language,
    detect_language,
    validate_output_language,
    build_system_prompt,
    language_enforcement_suffix,
)


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_english_text(self):
        assert detect_language("What is the best way to use this product?") == "en"

    def test_indonesian_text(self):
        assert detect_language("Apa cara terbaik menggunakan produk ini?") == "id"

    def test_english_longer(self):
        assert detect_language(
            "How do I reset my password and what are the security requirements for a new one?"
        ) == "en"

    def test_indonesian_longer(self):
        assert detect_language(
            "Bagaimana cara saya mereset password dan apa saja persyaratan keamanan untuk password baru?"
        ) == "id"

    def test_empty_defaults_id(self):
        assert detect_language("") == "id"


# ---------------------------------------------------------------------------
# resolve_language — Priority 1: explicit user override
# ---------------------------------------------------------------------------

class TestResolveLanguageExplicitOverride:
    def test_answer_in_english_overrides_agent_id(self):
        result = resolve_language(
            user_message="Please answer in English.",
            agent_language="id",
        )
        assert result == "en"

    def test_reply_in_english_overrides_agent_id(self):
        result = resolve_language(
            user_message="Can you reply in English?",
            agent_language="id",
        )
        assert result == "en"

    def test_use_english_overrides_agent_id(self):
        result = resolve_language(
            user_message="Use English from now on.",
            agent_language="id",
        )
        assert result == "en"

    def test_jawab_bahasa_indonesia_overrides_agent_en(self):
        result = resolve_language(
            user_message="Tolong jawab dalam bahasa Indonesia.",
            agent_language="en",
        )
        assert result == "id"

    def test_explicit_override_case_insensitive(self):
        result = resolve_language(
            user_message="ANSWER IN ENGLISH",
            agent_language="id",
        )
        assert result == "en"


# ---------------------------------------------------------------------------
# resolve_language — Priority 2: agent language setting
# ---------------------------------------------------------------------------

class TestResolveLanguageAgentSetting:
    """Ticket required scenarios — agent language wins over message language."""

    def test_scenario_1_lang_en_question_en(self):
        """Language=en, Question=English → Expected=en"""
        result = resolve_language(
            user_message="What are your business hours?",
            agent_language="en",
        )
        assert result == "en"

    def test_scenario_2_lang_id_question_id(self):
        """Language=id, Question=Indonesian → Expected=id"""
        result = resolve_language(
            user_message="Apa jam operasional toko Anda?",
            agent_language="id",
        )
        assert result == "id"

    def test_scenario_3_lang_en_question_id(self):
        """Language=en, Question=Indonesian → Expected=en (agent setting wins)"""
        result = resolve_language(
            user_message="Apa jam operasional toko Anda?",
            agent_language="en",
        )
        assert result == "en"

    def test_scenario_4_lang_id_question_en(self):
        """Language=id, Question=English → Expected=id (agent setting wins)"""
        result = resolve_language(
            user_message="What are your business hours?",
            agent_language="id",
        )
        assert result == "id"

    def test_agent_en_no_override_in_message(self):
        result = resolve_language(
            user_message="Berikan saya informasi tentang produk ini",
            agent_language="en",
        )
        assert result == "en"

    def test_agent_id_no_override_in_message(self):
        result = resolve_language(
            user_message="Tell me about your products",
            agent_language="id",
        )
        assert result == "id"


# ---------------------------------------------------------------------------
# resolve_language — Priority 3: conversation memory
# ---------------------------------------------------------------------------

class TestResolveLanguageConversationMemory:
    def test_conversation_memory_used_when_no_agent_language(self):
        result = resolve_language(
            user_message="ok",
            agent_language=None,
            conversation_language="en",
        )
        assert result == "en"

    def test_agent_language_beats_conversation_memory(self):
        result = resolve_language(
            user_message="ok",
            agent_language="id",
            conversation_language="en",
        )
        assert result == "id"


# ---------------------------------------------------------------------------
# resolve_language — Priority 4: auto-detect
# ---------------------------------------------------------------------------

class TestResolveLanguageAutoDetect:
    def test_auto_detect_english_when_no_agent_language(self):
        result = resolve_language(
            user_message="How can I contact customer support?",
            agent_language=None,
            conversation_language=None,
        )
        assert result == "en"

    def test_auto_detect_indonesian_when_no_agent_language(self):
        result = resolve_language(
            user_message="Bagaimana cara menghubungi layanan pelanggan?",
            agent_language=None,
            conversation_language=None,
        )
        assert result == "id"


# ---------------------------------------------------------------------------
# validate_output_language
# ---------------------------------------------------------------------------

class TestValidateOutputLanguage:
    def test_english_output_passes_when_expected_en(self):
        text = (
            "Our business hours are Monday through Friday, 9 AM to 5 PM. "
            "We are closed on weekends and public holidays."
        )
        assert validate_output_language(text, "en") is True

    def test_indonesian_output_passes_when_expected_id(self):
        text = (
            "Jam operasional kami adalah Senin hingga Jumat, pukul 09.00 hingga 17.00. "
            "Kami tutup pada akhir pekan dan hari libur nasional."
        )
        assert validate_output_language(text, "id") is True

    def test_indonesian_output_fails_when_expected_en(self):
        text = (
            "Jam operasional kami adalah Senin hingga Jumat, pukul 09.00 hingga 17.00. "
            "Kami tutup pada akhir pekan dan hari libur nasional."
        )
        assert validate_output_language(text, "en") is False

    def test_english_output_fails_when_expected_id(self):
        text = (
            "Our business hours are Monday through Friday, 9 AM to 5 PM. "
            "We are closed on weekends and public holidays."
        )
        assert validate_output_language(text, "id") is False

    def test_short_response_always_valid(self):
        # Fewer than min_words (8) — should not trigger retry
        assert validate_output_language("Yes!", "en") is True
        assert validate_output_language("Ya!", "id") is True
        assert validate_output_language("Sure.", "id") is True


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_english_prompt_starts_with_language_rule(self):
        prompt = build_system_prompt(None, [], "en")
        assert prompt.startswith("LANGUAGE RULE:"), (
            "English system prompt must start with LANGUAGE RULE directive"
        )

    def test_indonesian_prompt_starts_with_aturan_bahasa(self):
        prompt = build_system_prompt(None, [], "id")
        assert prompt.startswith("ATURAN BAHASA:"), (
            "Indonesian system prompt must start with ATURAN BAHASA directive"
        )

    def test_english_prompt_contains_english_directive(self):
        prompt = build_system_prompt(None, [], "en")
        assert "respond in English only" in prompt

    def test_indonesian_prompt_contains_indonesian_directive(self):
        prompt = build_system_prompt(None, [], "id")
        assert "Bahasa Indonesia saja" in prompt

    def test_english_prompt_style_guide_in_english(self):
        prompt = build_system_prompt(None, [], "en")
        assert "Response style" in prompt
        # Must not contain Indonesian style guide marker
        assert "Gaya jawaban" not in prompt

    def test_indonesian_prompt_style_guide_in_indonesian(self):
        prompt = build_system_prompt(None, [], "id")
        assert "Gaya jawaban" in prompt
        # Must not contain English style guide marker
        assert "Response style" not in prompt

    def test_custom_prompt_preserved(self):
        custom = "You are a sales agent for Acme Corp. Only discuss Acme products."
        prompt = build_system_prompt(custom, [], "en")
        assert custom in prompt

    def test_chunks_included_in_prompt(self):
        chunks = [{"content": "Our return policy is 30 days."}]
        prompt = build_system_prompt(None, chunks, "en")
        assert "Our return policy is 30 days." in prompt

    def test_english_kb_context_header_in_english(self):
        chunks = [{"content": "Product info here."}]
        prompt = build_system_prompt(None, chunks, "en")
        assert "Context from knowledge base" in prompt
        assert "Konteks dari knowledge base" not in prompt

    def test_indonesian_kb_context_header_in_indonesian(self):
        chunks = [{"content": "Info produk di sini."}]
        prompt = build_system_prompt(None, chunks, "id")
        assert "Konteks dari knowledge base" in prompt
        assert "Context from knowledge base" not in prompt

    def test_language_directive_before_base_prompt(self):
        prompt = build_system_prompt(None, [], "en")
        lang_pos = prompt.index("LANGUAGE RULE")
        style_pos = prompt.index("Response style")
        assert lang_pos < style_pos, "Language directive must precede the style guide"

    def test_language_directive_before_custom_prompt(self):
        custom = "You are a helpful assistant for UniqueCustomCompany."
        prompt = build_system_prompt(custom, [], "id")
        lang_pos = prompt.index("ATURAN BAHASA")
        custom_pos = prompt.index("UniqueCustomCompany")
        assert lang_pos < custom_pos, "Language directive must precede the custom prompt"


# ---------------------------------------------------------------------------
# language_enforcement_suffix
# ---------------------------------------------------------------------------

class TestLanguageEnforcementSuffix:
    def test_english_suffix_in_english(self):
        suffix = language_enforcement_suffix("en")
        assert "English" in suffix
        assert "CRITICAL" in suffix or "REMINDER" in suffix

    def test_indonesian_suffix_in_indonesian(self):
        suffix = language_enforcement_suffix("id")
        assert "Indonesia" in suffix
        assert "KRITIS" in suffix or "PENGINGAT" in suffix
