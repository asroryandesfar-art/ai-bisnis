"""
agents/base.py — Base class untuk semua agen
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

import vendor_bootstrap  # noqa: F401


@dataclass
class AgentMessage:
    """Pesan yang mengalir antar agen."""
    role:    str            # "user" | "assistant" | "system"
    content: str
    meta:    dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Hasil dari satu agen."""
    agent:      str
    success:    bool
    output:     dict
    latency_ms: int
    error:      str | None = None


class BaseAgent:
    """
    Kelas dasar semua agen.
    Setiap subclass wajib definisikan:
      - name: str
      - system_prompt: str
    Dan boleh override method `run()`.
    """
    name:          str = "base"
    system_prompt: str = "Kamu adalah asisten AI."

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        app_url: str = "https://botnesia.id",
    ):
        self.api_key = api_key or ""
        self.model   = model or ""
        self.base_url = base_url or ""
        self.app_url = app_url

    async def _call_llm(
        self,
        messages:    list[dict],
        temperature: float = 0.3,
        max_tokens:  int   = 1024,
    ) -> str:
        """
        Cloud LLM call via Groq chat completions.
        """
        if not self.api_key:
            raise RuntimeError("API key kosong. Set GROQ_API_KEY untuk mode cloud.")

        base_url = (self.base_url or "https://api.groq.com/openai/v1").rstrip("/")
        model = self.model or "llama-3.3-70b-versatile"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        return str(message.get("content") or "").strip()

    async def run(self, context: dict) -> AgentResult:
        """
        Override ini di subclass.
        context berisi semua data yang dibutuhkan agen:
          - conversation_id, bot_id, org_id
          - messages: list pesan percakapan
          - user_message: pesan terbaru dari pelanggan
          - bot_response: jawaban bot (opsional)
          - metadata: info tambahan
        """
        raise NotImplementedError

    async def safe_run(self, context: dict) -> AgentResult:
        """Wrapper run() dengan error handling dan timing."""
        t = time.monotonic()
        try:
            result = await self.run(context)
            result.latency_ms = int((time.monotonic() - t) * 1000)
            return result
        except Exception as e:
            return AgentResult(
                agent      = self.name,
                success    = False,
                output     = {},
                latency_ms = int((time.monotonic() - t) * 1000),
                error      = str(e),
            )
