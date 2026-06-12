"""
agents/base.py — Base class untuk semua agen
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

import vendor_bootstrap  # noqa: F401
from agent_observability import add_token_usage, observe_agent
from cost_intelligence import routed_model


def parse_json_response(raw: str, default: dict | None = None) -> dict:
    """Parse LLM JSON output dengan fallback markdown code-fence. Tidak pernah raise."""
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return dict(default) if default is not None else {}


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
        response_format: dict | None = None,
    ) -> str:
        """
        Cloud LLM call via Groq chat completions.
        """
        if not self.api_key:
            raise RuntimeError("API key kosong. Set GROQ_API_KEY untuk mode cloud.")

        base_url = (self.base_url or "https://api.groq.com/openai/v1").rstrip("/")
        default_model = self.model or "llama-3.3-70b-versatile"
        selected_model = routed_model(default_model)
        models = [selected_model]
        if selected_model != default_model:
            models.append(default_model)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        max_attempts = 3
        async with httpx.AsyncClient(timeout=60) as client:
            for model_index, model in enumerate(models):
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format is not None:
                    payload["response_format"] = response_format
                try:
                    for attempt in range(max_attempts):
                        resp = await client.post(
                            f"{base_url}/chat/completions", json=payload, headers=headers
                        )
                        if resp.status_code == 429 and attempt < max_attempts - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        resp.raise_for_status()
                        data = resp.json() or {}
                        break
                    break
                except httpx.HTTPStatusError:
                    if model_index >= len(models) - 1:
                        raise
        usage = data.get("usage") or {}
        add_token_usage(
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        return str(message.get("content") or "").strip()

    async def _call_llm_json(
        self,
        messages:    list[dict],
        temperature: float = 0.2,
        max_tokens:  int   = 512,
        default:     dict | None = None,
    ) -> dict:
        """LLM call dengan Groq json_object mode + parsing aman.

        Catatan: Groq mewajibkan kata "JSON" muncul di prompt saat
        response_format json_object dipakai.
        """
        try:
            raw = await self._call_llm(
                messages, temperature=temperature, max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:
            # LLM call gagal total (mis. 429 quota harian) — beda dari respons
            # kosong/refusal yang valid. Tandai supaya caller bisa pilih pesan
            # fallback yang lebih jujur ("sistem sibuk" vs "tolong kirim detail").
            out = dict(default) if default is not None else {}
            out["_llm_unavailable"] = True
            return out
        return parse_json_response(raw, default=default)

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
        """Wrapper run() dengan error handling, timing, dan tracing."""
        async def execute() -> AgentResult:
            t = time.monotonic()
            try:
                result = await self.run(context)
                result.latency_ms = int((time.monotonic() - t) * 1000)
                return result
            except Exception as e:
                return AgentResult(
                    agent=self.name, success=False, output={},
                    latency_ms=int((time.monotonic() - t) * 1000), error=str(e),
                )

        return await observe_agent(self.name, context, execute)
