"""
ai_providers/gemini.py — Full Gemini Content API client.

Features: retries, timeout, streaming, JSON mode, image/PDF input,
function/tool calling, safety handling, token counting, usage logging.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, AsyncGenerator

import httpx

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse

logger = logging.getLogger("botnesia.gemini")

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Gemini finish reasons that indicate a safety block (treat as empty, not error)
_SAFETY_FINISH_REASONS = frozenset({"SAFETY", "RECITATION", "PROHIBITED_CONTENT"})

# HTTP status codes that should be retried
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Pricing per 1M tokens (USD) — update via AI_MODEL_PRICING_JSON env var
GEMINI_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash":               {"input": 0.075,  "output": 0.30},
    "gemini-2.5-flash-preview-05-20": {"input": 0.075,  "output": 0.30},
    "gemini-2.5-pro":                 {"input": 1.25,   "output": 10.00},
    "gemini-2.5-pro-preview-06-05":   {"input": 1.25,   "output": 10.00},
    "gemini-1.5-flash":               {"input": 0.075,  "output": 0.30},
    "gemini-1.5-pro":                 {"input": 1.25,   "output": 5.00},
}


def _add_token_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    try:
        from agent_observability import add_token_usage
        add_token_usage(model=model, prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens)
    except Exception:
        pass


class GeminiProvider(AIProvider):
    """
    Full-featured async Gemini client.

    Connection pooling: one httpx.AsyncClient is created per provider instance
    and reused across requests (call `await provider.aclose()` on shutdown).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        pro_model: str = "gemini-2.5-pro",
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.model = model
        self.pro_model = pro_model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── AIProvider interface ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self.model

    # ── payload builders ─────────────────────────────────────────────────────

    def _build_contents(
        self,
        messages: list[dict],
        images: list[bytes | str] | None = None,
        pdfs: list[bytes | str] | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Returns (system_parts, contents)."""
        system_parts: list[dict] = []
        contents: list[dict] = []

        for i, msg in enumerate(messages):
            role = str(msg.get("role") or "user")
            content = msg.get("content") or ""

            if role == "system":
                if isinstance(content, str):
                    system_parts.append({"text": content})
                continue

            gemini_role = "model" if role == "assistant" else "user"

            # Build parts list for this message
            parts: list[dict] = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append({"text": block.get("text", "")})
                        elif block.get("type") == "image_url":
                            url = (block.get("image_url") or {}).get("url", "")
                            if url.startswith("data:"):
                                mime, b64 = _parse_data_url(url)
                                parts.append({"inline_data": {"mime_type": mime, "data": b64}})

            # Attach images/PDFs to the last user message
            is_last_user = (gemini_role == "user" and i == len(messages) - 1)
            if is_last_user:
                for img in (images or []):
                    parts.append(_encode_media(img, "image/jpeg"))
                for pdf in (pdfs or []):
                    parts.append(_encode_media(pdf, "application/pdf"))

            if not parts:
                parts = [{"text": ""}]

            contents.append({"role": gemini_role, "parts": parts})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})

        return system_parts, contents

    def _build_payload(self, request: LLMRequest, model: str) -> dict:
        system_parts, contents = self._build_contents(
            request.messages, request.images, request.pdfs
        )
        generation_config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.response_format and request.response_format.get("type") == "json_object":
            generation_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if request.tools:
            payload["tools"] = [{"function_declarations": _openai_tools_to_gemini(request.tools)}]

        return payload

    # ── core HTTP ────────────────────────────────────────────────────────────

    async def _post_with_retry(
        self, url: str, payload: dict
    ) -> tuple[dict, int]:
        """POST with exponential backoff. Returns (response_json, retry_count)."""
        client = self._get_client()
        params = {"key": self.api_key}
        last_exc: Exception | None = None
        retries = 0

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = min(2 ** (attempt - 1), 16)
                await asyncio.sleep(delay)
                retries += 1

            try:
                resp = await client.post(url, params=params, json=payload)

                if resp.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                    logger.warning("gemini %s status=%d attempt=%d", url, resp.status_code, attempt)
                    last_exc = httpx.HTTPStatusError(
                        f"status {resp.status_code}", request=resp.request, response=resp
                    )
                    continue

                resp.raise_for_status()
                return resp.json() or {}, retries

            except httpx.TimeoutException as exc:
                logger.warning("gemini timeout attempt=%d", attempt)
                last_exc = exc
                if attempt >= self.max_retries:
                    raise

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status not in _RETRYABLE_STATUS or attempt >= self.max_retries:
                    raise
                last_exc = exc

        raise last_exc or RuntimeError("Gemini request failed after retries")

    # ── public API ───────────────────────────────────────────────────────────

    async def complete(self, request: LLMRequest, *, model: str | None = None) -> LLMResponse:
        """Non-streaming completion."""
        resolved = model or self.model
        url = f"{_BASE_URL}/{resolved}:generateContent"
        payload = self._build_payload(request, resolved)

        t0 = time.monotonic()
        try:
            data, retries = await self._post_with_retry(url, payload)
        except Exception as exc:
            return LLMResponse(
                content="", model=resolved, provider="gemini",
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        text, usage = _parse_response(data, resolved)
        _add_token_usage(f"gemini:{resolved}", usage["prompt"], usage["completion"])

        return LLMResponse(
            content=text,
            model=resolved,
            provider="gemini",
            prompt_tokens=usage["prompt"],
            completion_tokens=usage["completion"],
            latency_ms=latency_ms,
            retries=retries,
        )

    async def complete_with_tools(
        self,
        request: LLMRequest,
        *,
        model: str | None = None,
        tool_executor: Any = None,
        tool_ctx: dict | None = None,
        max_rounds: int = 4,
    ) -> LLMResponse:
        """Gemini-native tool calling loop."""
        resolved = model or self.model
        url = f"{_BASE_URL}/{resolved}:generateContent"
        messages = list(request.messages)
        executed_calls: list[dict] = []
        total_prompt = 0
        total_completion = 0
        retries_total = 0

        t0 = time.monotonic()
        for round_no in range(max_rounds):
            loop_req = LLMRequest(
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
            )
            payload = self._build_payload(loop_req, resolved)
            try:
                data, retries = await self._post_with_retry(url, payload)
                retries_total += retries
            except Exception as exc:
                return LLMResponse(
                    content="", model=resolved, provider="gemini",
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    error=str(exc), tool_calls=executed_calls,
                )

            usage = data.get("usageMetadata") or {}
            total_prompt += usage.get("promptTokenCount", 0)
            total_completion += usage.get("candidatesTokenCount", 0)

            candidates = data.get("candidates") or []
            if not candidates:
                break
            candidate = candidates[0] or {}
            finish = candidate.get("finishReason", "")
            if finish in _SAFETY_FINISH_REASONS:
                break

            parts = ((candidate.get("content") or {}).get("parts") or [])

            # Check for function calls
            fn_calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not fn_calls:
                text = "".join(str(p.get("text") or "") for p in parts).strip()
                _add_token_usage(f"gemini:{resolved}", total_prompt, total_completion)
                return LLMResponse(
                    content=text, model=resolved, provider="gemini",
                    prompt_tokens=total_prompt, completion_tokens=total_completion,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    retries=retries_total, tool_calls=executed_calls,
                )

            # Execute tools and append results
            messages.append({
                "role": "model",
                "parts": parts,
            })
            tool_result_parts: list[dict] = []
            for fn_call in fn_calls:
                name = fn_call.get("name", "")
                args = fn_call.get("args") or {}
                result: Any = {}
                if tool_executor:
                    try:
                        result = await tool_executor(name, args, ctx=tool_ctx or {})
                    except Exception as exc:
                        result = {"error": str(exc)}
                executed_calls.append({"name": name, "args": args, "result": result})
                tool_result_parts.append({
                    "functionResponse": {"name": name, "response": result}
                })
            messages.append({"role": "user", "parts": tool_result_parts})

        _add_token_usage(f"gemini:{resolved}", total_prompt, total_completion)
        return LLMResponse(
            content="", model=resolved, provider="gemini",
            prompt_tokens=total_prompt, completion_tokens=total_completion,
            latency_ms=int((time.monotonic() - t0) * 1000),
            retries=retries_total, tool_calls=executed_calls,
        )

    async def stream(self, request: LLMRequest, *, model: str | None = None):
        """Async generator yielding str text chunks."""
        resolved = model or self.model
        url = f"{_BASE_URL}/{resolved}:streamGenerateContent"
        payload = self._build_payload(request, resolved)
        params = {"key": self.api_key, "alt": "sse"}

        client = self._get_client()
        async with client.stream("POST", url, params=params, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                candidates = chunk.get("candidates") or []
                if not candidates:
                    continue
                parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
                for part in parts:
                    text = part.get("text")
                    if text:
                        yield text

    async def count_tokens(self, request: LLMRequest, *, model: str | None = None) -> int:
        """Return estimated token count for a request without generating output."""
        resolved = model or self.model
        url = f"{_BASE_URL}/{resolved}:countTokens"
        _, contents = self._build_contents(request.messages)
        payload: dict[str, Any] = {"contents": contents}
        try:
            data, _ = await self._post_with_retry(url, payload)
            return int(data.get("totalTokens") or 0)
        except Exception:
            return 0


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_response(data: dict, model: str) -> tuple[str, dict]:
    """Extract text + token usage from a Gemini generateContent response."""
    usage_meta = data.get("usageMetadata") or {}
    usage = {
        "prompt": int(usage_meta.get("promptTokenCount") or 0),
        "completion": int(usage_meta.get("candidatesTokenCount") or 0),
    }
    candidates = data.get("candidates") or []
    if not candidates:
        return "", usage

    candidate = candidates[0] or {}
    finish = candidate.get("finishReason", "")
    if finish in _SAFETY_FINISH_REASONS:
        logger.warning("gemini safety block: finishReason=%s model=%s", finish, model)
        return "", usage

    parts = ((candidate.get("content") or {}).get("parts") or [])
    text = "".join(str(p.get("text") or "") for p in parts).strip()
    return text, usage


def _encode_media(data: bytes | str, default_mime: str) -> dict:
    """Encode bytes or base64 string into a Gemini inline_data part."""
    if isinstance(data, bytes):
        b64 = base64.b64encode(data).decode()
    else:
        b64 = data  # assume already base64
    return {"inline_data": {"mime_type": default_mime, "data": b64}}


def _parse_data_url(url: str) -> tuple[str, str]:
    """Parse a data: URL into (mime_type, base64_data)."""
    rest = url[5:]
    if "," in rest:
        header, data = rest.split(",", 1)
        mime = header.split(";")[0] if ";" in header else header
        return mime, data
    return "image/jpeg", rest


def _openai_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Convert OpenAI function-calling schema to Gemini function_declarations."""
    declarations = []
    for tool in tools:
        fn = tool.get("function") or tool
        decl: dict[str, Any] = {"name": fn.get("name", "")}
        if fn.get("description"):
            decl["description"] = fn["description"]
        if fn.get("parameters"):
            decl["parameters"] = fn["parameters"]
        declarations.append(decl)
    return declarations
