import asyncio

import base
from base import BaseAgent


class _FakeGroq429Response:
    status_code = 429

    def json(self):
        return {}

    def raise_for_status(self):
        raise base.httpx.HTTPStatusError(
            "rate limited", request=base.httpx.Request("POST", "https://groq.test"), response=self
        )


class _FakeGroq429Client:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        self.calls += 1
        return _FakeGroq429Response()


def test_call_llm_falls_back_to_gemini_after_groq_429(monkeypatch):
    monkeypatch.setattr(base.httpx, "AsyncClient", _FakeGroq429Client)

    async def fake_gemini(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        assert messages == [{"role": "user", "content": "hello"}]
        assert response_format is None
        return "gemini answer"

    monkeypatch.setattr(BaseAgent, "_call_gemini", fake_gemini)

    agent = BaseAgent(
        api_key="groq-key",
        model="groq-main",
        gemini_api_key="google-key",
        gemini_model="gemini-1.5-flash",
    )
    answer = asyncio.run(agent._call_llm([{"role": "user", "content": "hello"}]))

    assert answer == "gemini answer"


def test_gemini_payload_maps_system_user_and_json_mode():
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
