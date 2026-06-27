"""
ai_providers/groq_provider.py — Groq provider wrapping the OpenAI-compatible API.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse

logger = logging.getLogger("botnesia.groq")

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _add_token_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    try:
        from agent_observability import add_token_usage
        add_token_usage(model=model, prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens)
    except Exception:
        pass


class GroqProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        base_url: str = "https://api.groq.com/openai/v1",
        max_retries: int = 3,
        timeout: float = 60.0,
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
        return "groq"

    @property
    def default_model(self) -> str:
        return self.model

    async def complete(self, request: LLMRequest, *, model: str | None = None) -> LLMResponse:
        resolved = model or self.model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            if attempt > 0:
                await asyncio.sleep(min(2 ** (attempt - 1), 16))
                retries += 1
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload, headers=headers,
                )
                if resp.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                    last_exc = httpx.HTTPStatusError(
                        f"status {resp.status_code}", request=resp.request, response=resp
                    )
                    continue
                resp.raise_for_status()
                data = resp.json() or {}
                break
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    return LLMResponse(
                        content="", model=resolved, provider="groq",
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        error=str(exc), retries=retries,
                    )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status not in _RETRYABLE_STATUS or attempt >= self.max_retries:
                    return LLMResponse(
                        content="", model=resolved, provider="groq",
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        error=str(exc), retries=retries,
                    )
                last_exc = exc
        else:
            return LLMResponse(
                content="", model=resolved, provider="groq",
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(last_exc), retries=retries,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = data.get("usage") or {}
        prompt_t = int(usage.get("prompt_tokens") or 0)
        completion_t = int(usage.get("completion_tokens") or 0)
        _add_token_usage(resolved, prompt_t, completion_t)

        choices = data.get("choices") or []
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()

        return LLMResponse(
            content=content, model=resolved, provider="groq",
            prompt_tokens=prompt_t, completion_tokens=completion_t,
            latency_ms=latency_ms, retries=retries,
        )

    async def stream(self, request: LLMRequest, *, model: str | None = None):
        """Async generator for Groq streaming (SSE)."""
        resolved = model or self.model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            json=payload, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    import json as _json
                    chunk = _json.loads(raw)
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                    text = delta.get("content")
                    if text:
                        yield text
                except Exception:
                    continue
