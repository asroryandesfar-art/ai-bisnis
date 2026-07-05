"""
ai_providers/deepseek.py — DeepSeek provider.

DeepSeek exposes an OpenAI-compatible API at https://api.deepseek.com.
Models available:
  deepseek-chat      — DeepSeek-V3, general purpose (fast, cheap, excellent for coding)
  deepseek-reasoner  — DeepSeek-R1, chain-of-thought reasoning (slower, deeper analysis)

Set DEEPSEEK_API_KEY in .env to activate.  When set, the SmartModelRouter
uses DeepSeek directly for coding and reasoning tasks — without the OpenRouter
markup — before falling back to OpenRouter or Groq.
"""
import asyncio
import json as _json
import logging
import time

import httpx

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse

logger = logging.getLogger("botnesia.deepseek")

_BASE_URL = "https://api.deepseek.com"
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

# Default model per task type when routing through DeepSeek directly.
# CATATAN: task-routing internal ini SENGAJA memakai model DeepSeek yang sudah
# terbukti (deepseek-chat/deepseek-reasoner) agar pipeline lama tetap stabil.
# Nama model per-tier "3 otak" yang env-driven ditangani terpisah di
# deepseek_brain.py (lihat docs/DEEPSEEK_BOTNESIA_BRAIN.md).
DEEPSEEK_TASK_MODELS: dict = {
    "coding":          "deepseek-chat",
    "advanced_coding": "deepseek-chat",
    "reasoning":       "deepseek-reasoner",
    "deep_reasoning":  "deepseek-reasoner",
    "planning":        "deepseek-chat",
    "document":        "deepseek-chat",
    "document_analysis": "deepseek-chat",
}

# Tasks where DeepSeek should NOT be the primary (let Gemini handle these)
_SKIP_TASKS = frozenset({
    "chat", "cs", "customer_service", "faq", "sales",
    "marketing", "hr", "knowledge", "knowledge_search", "internal",
})


def deepseek_model_for_task(task_type: str) -> str | None:
    """Return DeepSeek model for task, or None if task is better handled elsewhere."""
    task = (task_type or "chat").lower()
    if task in _SKIP_TASKS:
        return None
    return DEEPSEEK_TASK_MODELS.get(task, "deepseek-chat")


def _add_token_usage(model: str, pt: int, ct: int) -> None:
    try:
        from agent_observability import add_token_usage
        add_token_usage(model=model, prompt_tokens=pt, completion_tokens=ct)
    except Exception:
        pass


class DeepSeekProvider(AIProvider):
    """
    DeepSeek direct API — best for coding (deepseek-chat/V3) and
    chain-of-thought reasoning (deepseek-reasoner/R1).

    Cheaper than routing through OpenRouter because there is no intermediary markup.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = _BASE_URL,
        max_retries: int = 2,
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
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
        return "deepseek"

    @property
    def default_model(self) -> str:
        return self.model

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
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
                    f"{self.base_url}/chat/completions",
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
                        content="", model=resolved, provider="deepseek",
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        error=str(exc), retries=retries,
                    )
        else:
            return LLMResponse(
                content="", model=resolved, provider="deepseek",
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
            content=content, model=resolved, provider="deepseek",
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
            "POST", f"{self.base_url}/chat/completions",
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
