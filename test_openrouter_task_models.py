"""Peta task→model OpenRouter sesuai arsitektur BotNesia + tanpa jebakan gpt-4o."""
from ai_providers.openrouter import DEFAULT_TASK_MODELS, task_model


def test_coding_docs_writing_use_claude():
    assert "claude" in task_model("coding")
    assert "claude" in task_model("advanced_coding")
    assert "claude" in task_model("document")
    assert "claude" in task_model("document_analysis")
    assert "claude" in task_model("writing")


def test_multimodal_uses_gemini():
    for t in ("vision", "multimodal", "image", "pdf", "audio", "document_ocr"):
        assert "gemini" in task_model(t), t


def test_reasoning_planning_use_deepseek_r1():
    assert task_model("reasoning") == "deepseek/deepseek-r1"
    assert task_model("planning") == "deepseek/deepseek-r1"
    assert task_model("business_planning") == "deepseek/deepseek-r1"


def test_standard_and_unknown_use_cheap_deepseek_chat():
    for t in ("chat", "cs", "faq", "sales", "marketing", "hr", "fast", "low_latency", "sesuatu-tak-dikenal"):
        assert task_model(t) == "deepseek/deepseek-chat", t


def test_no_gpt4o_cost_trap_in_defaults():
    assert not any("gpt-4o" in v for v in DEFAULT_TASK_MODELS.values()), "gpt-4o mahal harus dibuang"


def test_env_override_takes_priority(monkeypatch):
    import ai_providers.openrouter as orp
    monkeypatch.setenv("OPENROUTER_TASK_MODELS_JSON", '{"chat": "custom/model-x"}')
    monkeypatch.setattr(orp, "_TASK_MODELS", None)   # bust cache
    try:
        assert orp.task_model("chat") == "custom/model-x"
    finally:
        monkeypatch.setattr(orp, "_TASK_MODELS", None)
