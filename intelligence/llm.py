"""
intelligence/llm.py — Klien LLM tipis bersama untuk modul Intelligence.

Mengulang pola `BaseAgent._call_llm` (Groq, OpenAI-compatible chat completions)
tanpa menambah dependensi baru. Dipakai oleh conversation_memory (ringkasan),
faq_agent (pemilihan jawaban kanonik), dan sales_agent (ekstraksi sinyal).
Semua pemanggil WAJIB tahan terhadap kegagalan LLM (fallback heuristik) —
lihat masing-masing modul.
"""
from __future__ import annotations

import httpx

from .config import cfg


async def call_llm(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    if not cfg.groq_api_key:
        raise RuntimeError("GROQ_API_KEY belum diisi — LLM tidak tersedia.")

    base_url = cfg.groq_base_url.rstrip("/")
    payload = {
        "model": cfg.groq_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {cfg.groq_api_key}",
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
