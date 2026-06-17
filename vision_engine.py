"""vision_engine.py — Image Analysis / Vision AI.

`cfg.groq_model` sudah default ke `meta-llama/llama-4-scout-17b-16e-instruct`,
yang native multimodal di Groq Chat Completions API — jadi tidak perlu
provider vision baru/key tambahan. Modul ini membangun message dengan content
type `image_url` (data URI base64) dan memanggil endpoint Groq yang sama
dipakai `base.py._call_llm`, dengan retry 429 yang sama persis.

Catatan: fallback model 8b yang dipakai `base.py._call_llm` (`llama-3.1-8b-instant`)
TIDAK vision-capable, jadi sengaja tidak dipakai di sini — kalau model vision
gagal, biarkan caller menampilkan error, jangan failover ke model non-vision.
"""
from __future__ import annotations

import asyncio
import base64

import httpx

MODE_PROMPTS = {
    "describe": "Deskripsikan gambar ini secara detail dalam Bahasa Indonesia: objek, warna, suasana, dan konteks.",
    "ocr": "Baca dan tuliskan ulang SEMUA teks yang ada pada gambar ini kata demi kata, urut dari atas ke bawah. Jika tidak ada teks, katakan tidak ada teks.",
    "ui_analysis": "Analisis tampilan UI/dashboard pada gambar ini: layout, komponen, hierarki visual, masalah usability, dan saran perbaikan.",
    "document": "Ekstrak informasi penting dari dokumen/invoice pada gambar ini (nomor, tanggal, nama, jumlah, total, item) dan kembalikan sebagai JSON yang rapi.",
}


def _data_uri(image_bytes: bytes, content_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"


async def analyze_image(
    image_bytes: bytes,
    content_type: str,
    *,
    api_key: str,
    model: str,
    question: str = "",
    mode: str = "describe",
    base_url: str = "https://api.groq.com/openai/v1",
) -> str:
    if not api_key:
        raise RuntimeError("GROQ_API_KEY belum dikonfigurasi.")

    instruction = (question or "").strip() or MODE_PROMPTS.get(mode, MODE_PROMPTS["describe"])
    response_format = None
    if mode == "document":
        instruction += " Jawab dalam format JSON."
        response_format = {"type": "json_object"}

    payload: dict = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": _data_uri(image_bytes, content_type or "image/png")}},
            ],
        }],
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/chat/completions"

    max_attempts = 3
    data: dict = {}
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(max_attempts):
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429 and attempt < max_attempts - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            break

    choices = data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return str(message.get("content") or "").strip()
