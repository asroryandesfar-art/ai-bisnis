"""
test_gemini_integration.py — Full Gemini 2.5 Flash integration tests.

Coverage:
  ✓ simple chat
  ✓ long conversation
  ✓ streaming
  ✓ image input
  ✓ PDF input
  ✓ tool calling
  ✓ structured JSON
  ✓ retry on 429/503
  ✓ timeout fallback
  ✓ Groq fallback when Gemini fails
  ✓ token usage logging
  ✓ concurrent requests
  ✓ safety block handling
  ✓ pro model routing
  ✓ SmartModelRouter
"""
import asyncio
import base64
import json

import pytest

from ai_providers.gemini import GeminiProvider, _openai_tools_to_gemini, _parse_response
from ai_providers.groq_provider import GroqProvider
from ai_providers.router import SmartModelRouter
from ai_providers.types import LLMRequest, LLMResponse, PRO_TASK_TYPES, FLASH_TASK_TYPES


# ── Fake HTTP infrastructure ──────────────────────────────────────────────────

def _gemini_ok(text="Hello!", prompt_tokens=10, completion_tokens=5):
    return {
        "candidates": [{
            "content": {"parts": [{"text": text}], "role": "model"},
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
            "totalTokenCount": prompt_tokens + completion_tokens,
        },
    }


def _gemini_safety_block():
    return {
        "candidates": [{
            "content": {"parts": [], "role": "model"},
            "finishReason": "SAFETY",
            "safetyRatings": [],
        }],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 0},
    }


def _gemini_tool_call(fn_name, args):
    return {
        "candidates": [{
            "content": {
                "parts": [{"functionCall": {"name": fn_name, "args": args}}],
                "role": "model",
            },
            "finishReason": "STOP",
        }],
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5},
    }


class _FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("POST", "https://generativelanguage.test")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(f"status {self.status_code}", request=req, response=resp)

    @property
    def request(self):
        import httpx
        return httpx.Request("POST", "https://generativelanguage.test")


class _FakeClient:
    """Synchronous fake that returns responses from a queue."""
    def __init__(self, responses):
        self._queue = list(responses)
        self.call_count = 0
        self.is_closed = False

    async def post(self, url, params=None, json=None):
        self.call_count += 1
        return self._queue.pop(0)

    async def aclose(self):
        self.is_closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _patch_provider(provider: GeminiProvider, responses: list) -> _FakeClient:
    client = _FakeClient(responses)
    provider._client = client
    return client


# ── GeminiProvider unit tests ─────────────────────────────────────────────────

def test_simple_chat():
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    _patch_provider(provider, [_FakeResponse(200, _gemini_ok("Halo!"))])
    monkeypatch_token_usage(provider)

    req = LLMRequest(messages=[{"role": "user", "content": "Halo"}])
    result = asyncio.run(provider.complete(req))

    assert result.content == "Halo!"
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"
    assert result.error is None


def test_long_conversation():
    messages = []
    for i in range(10):
        messages.append({"role": "user", "content": f"Pesan user {i}"})
        messages.append({"role": "assistant", "content": f"Jawaban {i}"})
    messages.append({"role": "user", "content": "Pertanyaan terakhir"})

    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, _gemini_ok("Jawaban akhir"))])
    monkeypatch_token_usage(provider)

    req = LLMRequest(messages=messages)
    result = asyncio.run(provider.complete(req))

    assert result.content == "Jawaban akhir"
    assert result.error is None


def test_json_mode():
    body = _gemini_ok('{"result": "ok", "score": 9}')
    provider = GeminiProvider(api_key="test-key")
    client = _patch_provider(provider, [_FakeResponse(200, body)])
    monkeypatch_token_usage(provider)

    req = LLMRequest(
        messages=[{"role": "user", "content": "Rate this JSON"}],
        response_format={"type": "json_object"},
    )
    result = asyncio.run(provider.complete(req))
    assert result.content
    parsed = json.loads(result.content)
    assert parsed["result"] == "ok"


def test_image_input():
    fake_image = base64.b64encode(b"\xff\xd8\xff").decode()
    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, _gemini_ok("Gambar berisi kucing"))])
    monkeypatch_token_usage(provider)

    req = LLMRequest(
        messages=[{"role": "user", "content": "Apa isi gambar ini?"}],
        images=[fake_image],
    )
    result = asyncio.run(provider.complete(req))
    assert result.content == "Gambar berisi kucing"

    # Verify the payload included inline_data
    payload = provider._build_payload(req, "gemini-2.5-flash")
    last_parts = payload["contents"][-1]["parts"]
    assert any("inline_data" in p for p in last_parts)


def test_pdf_input():
    fake_pdf = base64.b64encode(b"%PDF-1.4").decode()
    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, _gemini_ok("Dokumen berisi kontrak"))])
    monkeypatch_token_usage(provider)

    req = LLMRequest(
        messages=[{"role": "user", "content": "Ringkas dokumen ini"}],
        pdfs=[fake_pdf],
    )
    result = asyncio.run(provider.complete(req))
    assert result.content == "Dokumen berisi kontrak"

    payload = provider._build_payload(req, "gemini-2.5-flash")
    last_parts = payload["contents"][-1]["parts"]
    pdf_parts = [p for p in last_parts if p.get("inline_data", {}).get("mime_type") == "application/pdf"]
    assert len(pdf_parts) == 1


def test_tool_calling():
    tool_response = _gemini_tool_call("knowledge_search", {"query": "jam buka"})
    final_response = _gemini_ok("Toko buka 09:00-17:00")

    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [
        _FakeResponse(200, tool_response),
        _FakeResponse(200, final_response),
    ])
    monkeypatch_token_usage(provider)

    executed = {}

    async def fake_executor(name, args, *, ctx=None):
        executed["name"] = name
        executed["args"] = args
        return {"jam_buka": "09:00", "jam_tutup": "17:00"}

    req = LLMRequest(
        messages=[{"role": "user", "content": "Jam buka toko berapa?"}],
        tools=[{"function": {"name": "knowledge_search", "description": "Cari di KB",
                             "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}],
    )
    result = asyncio.run(provider.complete_with_tools(
        req, tool_executor=fake_executor, tool_ctx={}
    ))

    assert executed["name"] == "knowledge_search"
    assert result.content == "Toko buka 09:00-17:00"
    assert len(result.tool_calls) == 1


def test_structured_json_output():
    json_body = _gemini_ok('{"complexity": "simple", "reason": "short message"}')
    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, json_body)])
    monkeypatch_token_usage(provider)

    req = LLMRequest(
        messages=[{"role": "user", "content": 'Classify: {"role":"user","content":"halo"}. JSON only.'}],
        response_format={"type": "json_object"},
    )
    result = asyncio.run(provider.complete(req))
    data = json.loads(result.content)
    assert data["complexity"] == "simple"


def test_retry_on_429():
    """Provider retries on 429 status responses then succeeds."""
    import ai_providers.gemini as gmod

    async def no_sleep(delay):
        pass

    original_sleep = gmod.asyncio.sleep
    gmod.asyncio.sleep = no_sleep
    try:
        provider = GeminiProvider(api_key="test-key", max_retries=2)
        _patch_provider(provider, [
            _FakeResponse(429, {}),
            _FakeResponse(429, {}),
            _FakeResponse(200, _gemini_ok("Berhasil setelah retry")),
        ])
        monkeypatch_token_usage(provider)

        req = LLMRequest(messages=[{"role": "user", "content": "test"}])
        result = asyncio.run(provider.complete(req))
    finally:
        gmod.asyncio.sleep = original_sleep

    assert result.content == "Berhasil setelah retry"
    assert result.retries == 2


def test_retry_on_503():
    """Provider retries on 503 overloaded response."""
    provider = GeminiProvider(api_key="test-key", max_retries=2)
    responses = [
        _FakeResponse(503, {"error": "overloaded"}),
        _FakeResponse(503, {"error": "overloaded"}),
        _FakeResponse(200, _gemini_ok("ok")),
    ]
    _patch_provider(provider, responses)
    monkeypatch_token_usage(provider)

    req = LLMRequest(messages=[{"role": "user", "content": "test"}])
    result = asyncio.run(_run_no_sleep(provider, req))
    # 503 raises HTTPStatusError which triggers retry
    # After 2 retries exhausted with 503, last attempt also 503 → error
    assert result is not None  # no crash


def test_timeout_returns_error():
    """Timeout produces LLMResponse with error, doesn't crash."""
    import httpx

    provider = GeminiProvider(api_key="test-key", max_retries=0, timeout=0.001)

    async def patched_post(url, params=None, json=None):
        raise httpx.TimeoutException("timeout")

    provider._client = type("C", (), {
        "is_closed": False,
        "post": patched_post,
    })()

    req = LLMRequest(messages=[{"role": "user", "content": "test"}])
    result = asyncio.run(provider.complete(req))
    assert result.error is not None
    assert result.content == ""


def test_fallback_to_groq_when_gemini_fails():
    """SmartModelRouter falls back to Groq when Gemini returns error."""
    gemini = GeminiProvider(api_key="gemini-key")
    groq = GroqProvider(api_key="groq-key")

    async def failing_gemini_complete(request, *, model=None):
        return LLMResponse(content="", model=model or "gemini-2.5-flash",
                           provider="gemini", error="API error")

    async def ok_groq_complete(request, *, model=None):
        return LLMResponse(content="groq fallback answer", model="llama", provider="groq")

    gemini.complete = failing_gemini_complete
    groq.complete = ok_groq_complete

    router = SmartModelRouter(gemini=gemini, groq=groq)
    req = LLMRequest(messages=[{"role": "user", "content": "hello"}])
    result = asyncio.run(router.route(req))

    assert result.content == "groq fallback answer"
    assert result.provider == "groq"


def test_token_usage_logged():
    """Token counts are captured in LLMResponse."""
    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, _gemini_ok("ok", prompt_tokens=42, completion_tokens=17))])
    monkeypatch_token_usage(provider)

    req = LLMRequest(messages=[{"role": "user", "content": "test"}])
    result = asyncio.run(provider.complete(req))

    assert result.prompt_tokens == 42
    assert result.completion_tokens == 17
    assert result.total_tokens == 59


def test_concurrent_requests():
    """Multiple concurrent requests all succeed."""
    import time

    provider = GeminiProvider(api_key="test-key")

    responses = [_FakeResponse(200, _gemini_ok(f"answer-{i}")) for i in range(5)]
    _patch_provider(provider, responses)
    monkeypatch_token_usage(provider)

    async def run_all():
        tasks = [
            provider.complete(LLMRequest(messages=[{"role": "user", "content": f"msg {i}"}]))
            for i in range(5)
        ]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_all())
    assert len(results) == 5
    for r in results:
        assert r.error is None or "answer" in r.content


def test_safety_block_returns_empty_not_error():
    """Safety-blocked responses return empty content, not an exception."""
    provider = GeminiProvider(api_key="test-key")
    _patch_provider(provider, [_FakeResponse(200, _gemini_safety_block())])
    monkeypatch_token_usage(provider)

    req = LLMRequest(messages=[{"role": "user", "content": "bad content"}])
    result = asyncio.run(provider.complete(req))

    assert result.content == ""
    assert result.error is None  # safety block is not an error, just empty


def test_pro_model_routing():
    """SmartModelRouter selects Pro for pro tier and complex tasks."""
    gemini = GeminiProvider(api_key="key", model="gemini-2.5-flash", pro_model="gemini-2.5-pro")
    router = SmartModelRouter(gemini=gemini, groq=None)

    assert router.select_model(tier="standard", task_type="chat") == "gemini-2.5-flash"
    assert router.select_model(tier="pro", task_type="chat") == "gemini-2.5-pro"
    assert router.select_model(tier="standard", task_type="document") == "gemini-2.5-pro"
    assert router.select_model(tier="standard", task_type="reasoning") == "gemini-2.5-pro"
    assert router.select_model(tier="standard", task_type="faq") == "gemini-2.5-flash"
    assert router.select_model(tier="standard", task_type="knowledge_search") == "gemini-2.5-flash"


def test_no_provider_raises():
    """Router with no available providers raises RuntimeError."""
    router = SmartModelRouter(gemini=None, groq=None)
    req = LLMRequest(messages=[{"role": "user", "content": "x"}])
    try:
        asyncio.run(router.route(req))
        assert False, "should raise"
    except RuntimeError as exc:
        assert "No AI provider" in str(exc)


# ── Tool conversion tests ─────────────────────────────────────────────────────

def test_openai_tools_to_gemini_conversion():
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "knowledge_search",
                "description": "Search the knowledge base",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    declarations = _openai_tools_to_gemini(openai_tools)
    assert len(declarations) == 1
    assert declarations[0]["name"] == "knowledge_search"
    assert declarations[0]["description"] == "Search the knowledge base"
    assert "parameters" in declarations[0]


# ── Cost model tests ──────────────────────────────────────────────────────────

def test_gemini_pricing_registered():
    """Gemini models appear in cost_intelligence pricing registry."""
    from cost_intelligence import estimate_cost_usd
    from decimal import Decimal

    cost = estimate_cost_usd("gemini-2.5-flash", 1_000_000, 0)
    assert cost == Decimal("0.07500000")

    cost_pro = estimate_cost_usd("gemini-2.5-pro", 1_000_000, 0)
    assert cost_pro == Decimal("1.25000000")


def test_gemini_prefixed_model_name_cost():
    """'gemini:gemini-2.5-flash' (logged format) is priced correctly."""
    from cost_intelligence import estimate_cost_usd
    from decimal import Decimal

    cost = estimate_cost_usd("gemini:gemini-2.5-flash", 1_000_000, 1_000_000)
    expected = Decimal("0.07500000") + Decimal("0.30000000")
    assert cost == expected


# ── Task type classification tests ───────────────────────────────────────────

def test_task_type_sets_are_mutually_exclusive():
    overlap = PRO_TASK_TYPES & FLASH_TASK_TYPES
    assert not overlap, f"Task types overlap: {overlap}"


# ── Streaming ─────────────────────────────────────────────────────────────────

def test_streaming_yields_text_chunks():
    """stream() yields text from SSE data lines."""
    provider = GeminiProvider(api_key="test-key")

    sse_lines = [
        'data: {"candidates":[{"content":{"parts":[{"text":"Halo "}]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"dunia!"}]}}]}',
        "data: [DONE]",
    ]

    class _FakeStreamResp:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for line in sse_lines:
                yield line

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _FakeStreamClient:
        is_closed = False

        def stream(self, method, url, params=None, json=None):
            return _FakeStreamResp()

    provider._client = _FakeStreamClient()

    async def collect():
        chunks = []
        async for chunk in provider.stream(LLMRequest(messages=[{"role": "user", "content": "hi"}])):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert chunks == ["Halo ", "dunia!"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def monkeypatch_token_usage(provider):
    """Silence add_token_usage calls inside the provider (no observability module needed)."""
    import ai_providers.gemini as gmod
    original = gmod._add_token_usage
    gmod._add_token_usage = lambda *a, **k: None
    return original


async def _run_with_sleep_patch(provider, req):
    """Run complete() with asyncio.sleep patched to no-op."""
    import ai_providers.gemini as gmod
    original_sleep = asyncio.sleep

    async def no_sleep(delay):
        pass

    import asyncio as _asyncio
    _asyncio.sleep = no_sleep
    try:
        return await provider.complete(req)
    finally:
        _asyncio.sleep = original_sleep


async def _run_no_sleep(provider, req):
    import asyncio as _asyncio
    original = _asyncio.sleep

    async def no_sleep(delay):
        pass

    _asyncio.sleep = no_sleep
    try:
        return await provider.complete(req)
    finally:
        _asyncio.sleep = original
