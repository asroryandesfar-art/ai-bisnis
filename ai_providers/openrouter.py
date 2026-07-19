"""
ai_providers/openrouter.py — OpenRouter provider.

OpenRouter (https://openrouter.ai) provides access to 200+ LLMs including
GPT-4o, DeepSeek, Qwen, Mistral, Llama, and more
through a single OpenAI-compatible API endpoint.

Set OPENROUTER_API_KEY in .env to activate.  When the key is present the
SmartModelRouter inserts an OpenRouter attempt between Gemini and Groq,
using the task-optimal model for each request type.

Task → Model mapping is configurable via OPENROUTER_TASK_MODELS_JSON (.env):
  '{"coding": "openai/gpt-4o", "reasoning": "deepseek/deepseek-r1"}'
"""
import asyncio
import json as _json
import logging
import os
import time

import httpx

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse

logger = logging.getLogger("botnesia.openrouter")

_BASE_URL = "https://openrouter.ai/api/v1"
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

# Peta task→model OpenRouter — sesuai arsitektur BotNesia:
#   Claude  → coding, analisis dokumen, penulisan kompleks
#   Gemini  → multimodal (vision/gambar/PDF/audio)
#   DeepSeek→ standar/chat/speed (murah & cepat) + reasoning/planning (R1)
# Otak inti (chat/reasoning/planning) tetap DeepSeek LANGSUNG di jalur utama;
# entri di sini dipakai saat request memang lewat OpenRouter (fallback/spesialis).
# Semua bisa di-override via env OPENROUTER_TASK_MODELS_JSON. TIDAK ada gpt-4o
# (mahal) di default demi menjaga margin.
_CLAUDE = "anthropic/claude-3.5-sonnet"      # ganti ke claude-3-haiku bila mau lebih murah
_GEMINI = "google/gemini-2.0-flash-001"
_DS_CHAT = "deepseek/deepseek-chat"
_DS_R1 = "deepseek/deepseek-r1"

DEFAULT_TASK_MODELS: dict = {
    # ── Claude: coding / dokumen / penulisan kompleks ───────────────────
    "coding":             _CLAUDE,
    "advanced_coding":    _CLAUDE,
    "document":           _CLAUDE,
    "document_analysis":  _CLAUDE,
    "writing":            _CLAUDE,
    "complex_writing":    _CLAUDE,
    "workflow":           _CLAUDE,
    "complex_workflow":   _CLAUDE,
    # ── Gemini: multimodal (vision/gambar/PDF/audio) ────────────────────
    "vision":             _GEMINI,
    "multimodal":         _GEMINI,
    "image":              _GEMINI,
    "image_analysis":     _GEMINI,
    "pdf":                _GEMINI,
    "document_ocr":       _GEMINI,
    "audio":              _GEMINI,
    # ── DeepSeek R1: reasoning / planning ───────────────────────────────
    "reasoning":          _DS_R1,
    "deep_reasoning":     _DS_R1,
    "planning":           _DS_R1,
    "business_planning":  _DS_R1,
    # ── DeepSeek chat: standar / chat / speed (murah & cepat) ───────────
    "chat":               _DS_CHAT,
    "cs":                 _DS_CHAT,
    "customer_service":   _DS_CHAT,
    "faq":                _DS_CHAT,
    "sales":              _DS_CHAT,
    "marketing":          _DS_CHAT,
    "hr":                 _DS_CHAT,
    "knowledge":          _DS_CHAT,
    "knowledge_search":   _DS_CHAT,
    "internal":           _DS_CHAT,
    "fast":               _DS_CHAT,
    "low_latency":        _DS_CHAT,
}

_DEFAULT_MODEL = "deepseek/deepseek-chat"   # fallback murah (bukan gpt-4o-mini)

# Module-level cache — rebuilt once per process (or when env var changes)
_TASK_MODELS: dict | None = None


def task_model(task_type: str) -> str:
    """Return the best OpenRouter model slug for a given task type."""
    global _TASK_MODELS
    if _TASK_MODELS is None:
        models = dict(DEFAULT_TASK_MODELS)
        raw = os.environ.get("OPENROUTER_TASK_MODELS_JSON", "").strip()
        if raw:
            try:
                models.update(_json.loads(raw))
            except Exception:
                pass
        _TASK_MODELS = models
    return _TASK_MODELS.get((task_type or "").lower(), _DEFAULT_MODEL)


def _add_token_usage(model: str, pt: int, ct: int) -> None:
    try:
        from agent_observability import add_token_usage
        add_token_usage(model=model, prompt_tokens=pt, completion_tokens=ct)
    except Exception:
        pass


class OpenRouterProvider(AIProvider):
    """
    OpenRouter — single API key, access to GPT-4o, DeepSeek, Qwen, Mistral, Llama, and 200+ models via OpenAI-compatible API.

    Implements AIProvider so it plugs directly into SmartModelRouter.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        site_url: str = "https://botnesia.id",
        app_name: str = "BotNesia",
        max_retries: int = 2,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        self.site_url = site_url
        self.app_name = app_name
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def default_model(self) -> str:
        return self.model

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }

    async def complete(self, request: LLMRequest, *, model: str | None = None) -> LLMResponse:
        resolved = model or self.model
        payload: dict = {
            "model": resolved,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format:
            payload["response_format"] = request.response_format

        client = self._get_client()
        t0 = time.monotonic()
        last_exc: Exception | None = None
        retries = 0

        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                retries += 1
            try:
                resp = await client.post(
                    f"{_BASE_URL}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code in _RETRYABLE and attempt < self.max_retries:
                    last_exc = httpx.HTTPStatusError(
                        f"status {resp.status_code}", request=resp.request, response=resp
                    )
                    continue
                resp.raise_for_status()
                data = resp.json() or {}
                break
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    return LLMResponse(
                        content="", model=resolved, provider="openrouter",
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        error=str(exc), retries=retries,
                    )
        else:
            return LLMResponse(
                content="", model=resolved, provider="openrouter",
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(last_exc), retries=retries,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = data.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        _add_token_usage(resolved, pt, ct)
        choices = data.get("choices") or []
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
        return LLMResponse(
            content=content, model=resolved, provider="openrouter",
            prompt_tokens=pt, completion_tokens=ct,
            latency_ms=latency_ms, retries=retries,
        )

    async def stream(self, request: LLMRequest, *, model: str | None = None):
        resolved = model or self.model
        payload = {
            "model": resolved,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        client = self._get_client()
        async with client.stream(
            "POST", f"{_BASE_URL}/chat/completions",
            json=payload, headers=self._headers(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    chunk = _json.loads(raw)
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                    text = delta.get("content")
                    if text:
                        yield text
                except Exception:
                    continue
