"""
test_base_llm_fallback.py — Tests for BaseAgent LLM routing behavior.

With gemini_api_key set: Gemini is PRIMARY, Groq is FALLBACK.
Without gemini_api_key:  Groq only.
"""
import asyncio

import base
from base import BaseAgent


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeGroqOkResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{"message": {"content": "groq answer"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    def raise_for_status(self):
        pass


class _FakeGroqOkClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *args, **kwargs):
        return _FakeGroqOkResponse()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_gemini_is_primary_when_key_is_set(monkeypatch):
    """When gemini_api_key is set, _call_llm should call Gemini (not Groq first)."""
    gemini_called = []

    async def fake_gemini_complete(self_provider, request, *, model=None):
        gemini_called.append(model or self_provider.model)
        from ai_providers.types import LLMResponse
        return LLMResponse(content="gemini answer", model=model or "gemini-2.5-flash", provider="gemini")

    from ai_providers import gemini as gemini_mod
    monkeypatch.setattr(gemini_mod.GeminiProvider, "complete", fake_gemini_complete)
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    agent = BaseAgent(
        api_key="groq-key",
        model="groq-model",
        gemini_api_key="gemini-key",
        gemini_model="gemini-2.5-flash",
    )
    answer = asyncio.run(agent._call_llm([{"role": "user", "content": "hello"}]))

    assert answer == "gemini answer"
    assert len(gemini_called) == 1
    assert "gemini" in gemini_called[0]


def test_groq_fallback_when_gemini_fails(monkeypatch):
    """When Gemini returns an error response, Groq is used as fallback."""
    async def fake_gemini_complete(self_provider, request, *, model=None):
        from ai_providers.types import LLMResponse
        return LLMResponse(content="", model="gemini-2.5-flash", provider="gemini",
                           error="connection timeout")

    from ai_providers import gemini as gemini_mod
    monkeypatch.setattr(gemini_mod.GeminiProvider, "complete", fake_gemini_complete)
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda timeout=None: _FakeGroqOkClient())
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    agent = BaseAgent(
        api_key="groq-key",
        model="groq-model",
        gemini_api_key="gemini-key",
    )
    answer = asyncio.run(agent._call_llm([{"role": "user", "content": "hello"}]))
    assert answer == "groq answer"


def test_groq_only_when_no_gemini_key(monkeypatch):
    """When no gemini_api_key, _call_llm goes straight to Groq."""
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda timeout=None: _FakeGroqOkClient())
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    agent = BaseAgent(api_key="groq-key", model="groq-model")
    answer = asyncio.run(agent._call_llm([{"role": "user", "content": "hello"}]))
    assert answer == "groq answer"


def test_pro_model_selected_for_pro_tier(monkeypatch):
    """PRO tier routes to gemini_pro_model."""
    used_models = []

    async def fake_gemini_complete(self_provider, request, *, model=None):
        used_models.append(model)
        from ai_providers.types import LLMResponse
        return LLMResponse(content="pro answer", model=model or "", provider="gemini")

    from ai_providers import gemini as gemini_mod
    monkeypatch.setattr(gemini_mod.GeminiProvider, "complete", fake_gemini_complete)
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    agent = BaseAgent(
        gemini_api_key="key",
        gemini_model="gemini-2.5-flash",
        gemini_pro_model="gemini-2.5-pro",
    )
    asyncio.run(agent._call_llm([{"role": "user", "content": "analyze"}], tier="pro"))
    assert used_models[0] == "gemini-2.5-pro"


def test_complex_task_type_uses_pro_model(monkeypatch):
    """Task type 'document' forces Pro model even on standard tier."""
    used_models = []

    async def fake_gemini_complete(self_provider, request, *, model=None):
        used_models.append(model)
        from ai_providers.types import LLMResponse
        return LLMResponse(content="ok", model=model or "", provider="gemini")

    from ai_providers import gemini as gemini_mod
    monkeypatch.setattr(gemini_mod.GeminiProvider, "complete", fake_gemini_complete)
    monkeypatch.setattr(base, "add_token_usage", lambda **k: None)

    agent = BaseAgent(
        gemini_api_key="key",
        gemini_model="gemini-2.5-flash",
        gemini_pro_model="gemini-2.5-pro",
    )
    asyncio.run(agent._call_llm([{"role": "user", "content": "x"}], task_type="document"))
    assert used_models[0] == "gemini-2.5-pro"


def test_no_key_raises():
    """No Gemini key and no Groq key → RuntimeError."""
    agent = BaseAgent()
    try:
        asyncio.run(agent._call_llm([{"role": "user", "content": "x"}]))
        assert False, "must raise"
    except RuntimeError as exc:
        assert "API key" in str(exc) or "GEMINI" in str(exc) or "GROQ" in str(exc)


def test_gemini_payload_maps_system_user_and_json_mode():
    """_gemini_messages_payload still builds correct Gemini request body."""
    agent = BaseAgent(gemini_api_key="google-key")
    payload = agent._gemini_messages_payload(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Return JSON."},
        ],
        temperature=0.2,
        max_tokens=128,
        response_format={"type": "json_object"},
    )

    assert payload["systemInstruction"]["parts"][0]["text"] == "You are helpful."
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "Return JSON."}]}]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
