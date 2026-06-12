"""
reasoning_agent.py — Agen spesialis "lensa" analisis untuk pipeline reasoning Pro.

Setiap lensa mengambil data real-time (pasar/berita) sebagai INPUT, lalu membuat
SATU panggilan LLM untuk bernalar (analisis + kesimpulan + confidence) — bukan
sekadar menyalin/meneruskan data mentah ke pengguna.
"""
from __future__ import annotations

import asyncio

from base import AgentResult, BaseAgent
from finance_fetcher import (
    build_crypto_market_context,
    build_stock_market_context,
    fetch_crypto_quotes,
    fetch_stock_quotes,
    looks_like_market_price_query,
)
from news_fetcher import build_news_context

LENS_SYSTEM_PROMPTS = {
    "market_technical": (
        "Kamu adalah analis pasar teknikal. Berdasarkan data harga real-time yang diberikan, "
        "jelaskan pergerakan harga, level penting, dan implikasinya bagi trader/investor. "
        "Balas HANYA dalam format JSON."
    ),
    "news": (
        "Kamu adalah analis berita yang menghubungkan peristiwa terkini dengan dampaknya. "
        "Berdasarkan data berita real-time yang diberikan, jelaskan peristiwa relevan dan "
        "potensi dampaknya terhadap pertanyaan pengguna. Balas HANYA dalam format JSON."
    ),
    "sentiment": (
        "Kamu adalah analis sentimen pasar. Berdasarkan data berita yang diberikan, nilai "
        "sentimen pasar saat ini (positif/negatif/netral) dan jelaskan alasannya. "
        "Balas HANYA dalam format JSON."
    ),
    "risk": (
        "Kamu adalah analis risiko. Berdasarkan kesimpulan analis lain, identifikasi risiko "
        "utama dan hal yang perlu diwaspadai pengguna. Balas HANYA dalam format JSON."
    ),
    "self_knowledge": (
        "Kamu adalah asisten dukungan BotNesia yang sangat memahami platform BotNesia: "
        "paket/pricing, billing, usage limit, channel, fitur dashboard, dan integrasi. "
        "Berdasarkan data akun & paket tenant yang diberikan, jawab pertanyaan secara "
        "SPESIFIK dan akurat — JANGAN jawab umum atau menebak. Jika data yang dibutuhkan "
        "tidak tersedia, katakan dengan jujur apa yang belum diketahui. "
        "Balas HANYA dalam format JSON."
    ),
    "business": (
        "Kamu adalah konsultan bisnis yang menganalisis performa toko/bisnis tenant "
        "berdasarkan data percakapan pelanggan (sentimen, topik, friction point, sinyal "
        "penjualan). Berikan diagnosis konkret dan rekomendasi tindakan yang bisa langsung "
        "dilakukan, bukan saran generik. Balas HANYA dalam format JSON."
    ),
}

_OUTPUT_INSTRUCTION = (
    "\n\nJawab dalam format JSON: "
    '{"analysis": "<analisis 2-4 kalimat>", "conclusion": "<kesimpulan singkat>", '
    '"confidence": <0-100>, "limitations": "<keterbatasan analisis ini, atau string kosong>", '
    '"suggested_next_action": "<saran tindak lanjut konkret, atau string kosong>"}'
)


class ReasoningAgent(BaseAgent):
    name = "reasoning_agent"
    system_prompt = "Kamu adalah analis spesialis. Balas HANYA dalam format JSON."

    async def run_lens(self, lens: str, context: dict, cross_context: str = "") -> AgentResult:
        """Jalankan satu lensa analisis. Tidak pernah raise — error jadi lens skip."""
        try:
            return await self._run_lens(lens, context, cross_context)
        except Exception as e:
            return self._skip(lens, f"error: {e}")

    async def _run_lens(self, lens: str, context: dict, cross_context: str) -> AgentResult:
        user_message = context.get("user_message", "")

        if lens == "market_technical":
            data_context = await self._build_market_context(user_message)
            if not data_context:
                return self._skip(lens, "no_data_available")
            prompt = (
                f"Pertanyaan pengguna: {user_message}\n\n"
                f"Data pasar real-time:\n{data_context}\n\n"
                "Jelaskan analisis teknikal singkat berdasarkan data ini "
                "(pergerakan harga, level penting, implikasinya)."
                + _OUTPUT_INSTRUCTION
            )
        elif lens in ("news", "sentiment"):
            data_context = await self._build_news_context(user_message)
            if not data_context:
                return self._skip(lens, "no_data_available")
            if lens == "news":
                instruction = "Identifikasi peristiwa relevan dan dampaknya terhadap pertanyaan pengguna."
            else:
                instruction = "Nilai sentimen pasar saat ini berdasarkan berita di atas dan jelaskan alasannya."
            prompt = (
                f"Pertanyaan pengguna: {user_message}\n\n"
                f"Data berita real-time:\n{data_context}\n\n"
                f"{instruction}"
                + _OUTPUT_INSTRUCTION
            )
        elif lens == "risk":
            if not cross_context:
                return self._skip(lens, "no_cross_context")
            prompt = (
                f"Pertanyaan pengguna: {user_message}\n\n"
                f"Kesimpulan analis lain:\n{cross_context}\n\n"
                "Identifikasi risiko utama dan hal yang perlu diwaspadai pengguna "
                "berdasarkan kesimpulan di atas."
                + _OUTPUT_INSTRUCTION
            )
        elif lens == "self_knowledge":
            data_context = (context.get("self_knowledge_context") or "").strip()
            if not data_context:
                return self._skip(lens, "no_data_available")
            prompt = (
                f"Pertanyaan pengguna: {user_message}\n\n"
                f"Data akun & platform BotNesia:\n{data_context}\n\n"
                "Jawab pertanyaan pengguna tentang BotNesia menggunakan data di atas. "
                "Jika pertanyaan membandingkan paket, gunakan bagian Perbandingan Paket. "
                "Jika pertanyaan tentang status/troubleshooting (mis. channel disconnect), "
                "berikan diagnosis dan langkah perbaikan berdasarkan data akun di atas."
                + _OUTPUT_INSTRUCTION
            )
        elif lens == "business":
            data_context = (context.get("business_context") or "").strip()
            if not data_context:
                return self._skip(lens, "no_data_available")
            prompt = (
                f"Pertanyaan pengguna: {user_message}\n\n"
                f"Data performa bisnis tenant:\n{data_context}\n\n"
                "Diagnosis kondisi bisnis tenant berdasarkan data di atas dan berikan "
                "rekomendasi tindakan konkret yang bisa langsung dilakukan."
                + _OUTPUT_INSTRUCTION
            )
        else:
            return self._skip(lens, "unknown_lens")

        system = LENS_SYSTEM_PROMPTS.get(lens, self.system_prompt)
        result = await self._call_llm_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
            default={"analysis": "", "conclusion": "", "confidence": 0},
        )
        result.setdefault("analysis", "")
        result.setdefault("conclusion", "")
        result.setdefault("confidence", 0)
        result.setdefault("limitations", "")
        result.setdefault("suggested_next_action", "")
        result["lens"] = lens
        return AgentResult(agent=f"reasoning_agent:{lens}", success=True, output=result, latency_ms=0)

    def _skip(self, lens: str, reason: str) -> AgentResult:
        return AgentResult(
            agent=f"reasoning_agent:{lens}",
            success=True,
            output={
                "analysis": "", "conclusion": "", "confidence": 0,
                "skipped": True, "reason": reason, "lens": lens,
            },
            latency_ms=0,
        )

    async def _build_market_context(self, user_message: str) -> str:
        if not looks_like_market_price_query(user_message):
            return ""
        crypto_quotes, stock_quotes = await asyncio.gather(
            fetch_crypto_quotes(user_message),
            fetch_stock_quotes(user_message),
        )
        blocks: list[str] = []
        stock_ctx = build_stock_market_context(stock_quotes)
        crypto_ctx = build_crypto_market_context(crypto_quotes)
        if stock_ctx:
            blocks.append(stock_ctx)
        if crypto_ctx:
            blocks.append(crypto_ctx)
        return "\n\n".join(blocks)

    async def _build_news_context(self, user_message: str) -> str:
        return await build_news_context(
            user_message, limit=5, include_bodies=False, fetch_timeout_s=5.0,
        )
