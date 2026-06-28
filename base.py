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


def parse_json_response(raw, default: dict | None = None) -> dict:
    """Parse LLM JSON output dengan fallback markdown code-fence. Tidak pernah raise."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
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
        gemini_api_key: str | None = None,
        gemini_model: str | None = None,
        gemini_pro_model: str | None = None,
        gemini_timeout: float = 30.0,
        gemini_max_retry: int = 3,
    ):
        self.api_key = api_key or ""
        self.model   = model or ""
        self.base_url = base_url or ""
        self.app_url = app_url
        self.gemini_api_key = gemini_api_key or ""
        self.gemini_model = gemini_model or "gemini-2.5-flash"
        self.gemini_pro_model = gemini_pro_model or "gemini-2.5-pro"
        self.gemini_timeout = gemini_timeout
        self.gemini_max_retry = gemini_max_retry

        # Lazy-initialized router (set on first _call_llm if gemini key is set)
        self._router = None

    def _gemini_messages_payload(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format: dict | None = None,
    ) -> dict:
        system_parts: list[dict] = []
        contents: list[dict] = []
        for msg in messages:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "")
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": content}],
            })
        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if response_format and response_format.get("type") == "json_object":
            generation_config["responseMimeType"] = "application/json"
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        return payload

    def _get_gemini_provider(self):
        """Lazy-init GeminiProvider using this agent's config."""
        from ai_providers.gemini import GeminiProvider
        return GeminiProvider(
            api_key=self.gemini_api_key,
            model=self.gemini_model,
            pro_model=self.gemini_pro_model,
            timeout=self.gemini_timeout,
            max_retries=self.gemini_max_retry,
        )

    async def _call_gemini(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict | None = None,
        *,
        model: str | None = None,
    ) -> str:
        if not self.gemini_api_key:
            raise RuntimeError("GOOGLE_API_KEY / GEMINI_API_KEY kosong. Gemini tidak aktif.")
        from ai_providers.types import LLMRequest
        req = LLMRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        provider = self._get_gemini_provider()
        resp = await provider.complete(req, model=model)
        if resp.error:
            raise RuntimeError(f"Gemini error: {resp.error}")
        return resp.content

    async def _call_llm(
        self,
        messages:    list[dict],
        temperature: float = 0.3,
        max_tokens:  int   = 1024,
        response_format: dict | None = None,
        *,
        tier: str = "standard",
        task_type: str = "chat",
    ) -> str:
        """
        Smart LLM call: Gemini primary (Flash/Pro by tier) when key is set,
        Groq fallback otherwise or on Gemini failure.
        """
        # ── Gemini primary path ──────────────────────────────────────────────
        if self.gemini_api_key:
            from ai_providers.gemini import GeminiProvider
            from ai_providers.types import LLMRequest, PRO_TASK_TYPES
            use_pro = (tier == "pro") or (task_type.lower() in PRO_TASK_TYPES)
            model = self.gemini_pro_model if use_pro else self.gemini_model
            provider = self._get_gemini_provider()
            req = LLMRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            try:
                resp = await provider.complete(req, model=model)
                if resp.error is None:
                    return resp.content
            except Exception:
                pass

            # Retry with Flash model if Pro was used and failed
            if use_pro and self.gemini_model and self.gemini_model != model:
                try:
                    resp = await provider.complete(req, model=self.gemini_model)
                    if resp.error is None:
                        return resp.content
                except Exception:
                    pass

            # Groq fallback after both Gemini attempts fail
            if not self.api_key:
                raise RuntimeError(
                    "Gemini tidak dapat dihubungi dan GROQ_API_KEY tidak tersedia."
                )

        elif not self.api_key:
            raise RuntimeError("API key kosong. Set GEMINI_API_KEY atau GROQ_API_KEY.")

        # ── Groq path ────────────────────────────────────────────────────────
        base_url = (self.base_url or "https://api.groq.com/openai/v1").rstrip("/")
        default_model = self.model or "meta-llama/llama-4-scout-17b-16e-instruct"
        selected_model = routed_model(default_model)
        models = [selected_model]
        if selected_model != default_model:
            models.append(default_model)
        _FAST_FALLBACK = "llama-3.1-8b-instant"
        if _FAST_FALLBACK not in models:
            models.append(_FAST_FALLBACK)
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
                        if resp.status_code == 429:
                            if attempt < max_attempts - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                        resp.raise_for_status()
                        data = resp.json() or {}
                        break
                    break
                except httpx.HTTPStatusError as exc:
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

    async def _call_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        tool_ctx: dict,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        max_rounds: int = 4,
    ) -> dict:
        """
        Tool-calling loop sungguhan (AI Workforce Phase 2, Tool Framework) --
        kirim `tools` ke Groq (skema OpenAI-compatible, lihat tool_executor.py),
        kalau model balas `tool_calls`, JALANKAN tool itu via
        `tool_executor.execute_tool()` (eksekusi nyata: query DB, browser,
        web search, dst -- tidak ada mock), append hasilnya sebagai pesan
        role="tool", lalu panggil ulang model sampai dia jawab teks biasa
        atau `max_rounds` habis.

        Return: {"final_answer": str, "tool_calls": [{"name","args","result"}],
        "rounds": int} -- `tool_calls` ini bukti eksekusi runtime nyata,
        bisa dipersist langsung ke log (lihat task_engine.py).
        """
        import tool_executor

        if not self.api_key:
            raise RuntimeError("API key kosong. Set GROQ_API_KEY untuk mode cloud.")

        base_url = (self.base_url or "https://api.groq.com/openai/v1").rstrip("/")
        model = routed_model(self.model or "meta-llama/llama-4-scout-17b-16e-instruct")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        conversation = list(messages)
        executed_calls: list[dict] = []

        async with httpx.AsyncClient(timeout=60) as client:
            for round_no in range(max_rounds):
                payload = {
                    "model": model, "messages": conversation,
                    "temperature": temperature, "max_tokens": max_tokens,
                    "tools": tools, "tool_choice": "auto",
                }
                for attempt in range(3):
                    resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code == 429 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status_code >= 400:
                        # Kegagalan LLM (400 "tool_use_failed", 429 quota habis
                        # setelah retry, 5xx, dst) -- bukan bug pemanggil, jadi
                        # degradasi seperti _call_llm_json's except Exception,
                        # bukan crash satu task gara-gara satu round gagal.
                        return {
                            "final_answer": "", "tool_calls": executed_calls,
                            "rounds": round_no + 1, "_llm_unavailable": True,
                        }
                    data = resp.json() or {}
                    break

                usage = data.get("usage") or {}
                add_token_usage(model=model, prompt_tokens=usage.get("prompt_tokens", 0),
                                 completion_tokens=usage.get("completion_tokens", 0))
                choices = data.get("choices") or []
                if not choices:
                    return {"final_answer": "", "tool_calls": executed_calls, "rounds": round_no + 1}

                message = (choices[0] or {}).get("message") or {}
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return {
                        "final_answer": str(message.get("content") or "").strip(),
                        "tool_calls": executed_calls, "rounds": round_no + 1,
                    }

                conversation.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name", "")
                    args = tool_executor.parse_tool_call_args(fn.get("arguments", "{}"))
                    result = await tool_executor.execute_tool(name, args, ctx=tool_ctx)
                    executed_calls.append({"name": name, "args": args, "result": result})
                    conversation.append({
                        "role": "tool", "tool_call_id": call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=True, default=str),
                    })

        return {"final_answer": "", "tool_calls": executed_calls, "rounds": max_rounds}

    async def run_task(
        self,
        goal: str,
        *,
        pool: Any,
        org_id: str,
        bot_id: str | None = None,
        ctx: dict | None = None,
    ) -> dict:
        """Jalankan satu goal bebas/multi-step lewat Task Engine
        (task_engine.run_agent_task) menggunakan `self.tools` agent ini.
        Pintu masuk BARU yang dipakai bersama jalur intent-classify lama
        (mis. finance_agent.parse_intent()) yang TIDAK diubah -- lihat
        task_engine.py untuk detail Plan->Subtasks->Tool Selection->
        Execution->Verification->Report."""
        import task_engine
        return await task_engine.run_agent_task(self, goal, pool=pool, org_id=org_id, bot_id=bot_id, ctx=ctx)

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
