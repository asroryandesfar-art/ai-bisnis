"""
planner_agent.py — Agen perencana untuk pipeline reasoning Pro.

Menentukan lensa analisis ("agents_to_invoke") mana yang relevan untuk
pertanyaan kompleks, strategi eksekusi, dan fokus sintesis jawaban akhir.
"""
from __future__ import annotations

from base import AgentResult, BaseAgent

AVAILABLE_LENSES = ["market_technical", "news", "sentiment", "risk", "self_knowledge", "business"]

DEFAULT_PLAN = {
    "agents_to_invoke": ["market_technical"],
    "execution_strategy": "parallel",
    "synthesis_focus": "",
}

_LENS_DESCRIPTIONS = (
    "- market_technical: analisis data harga/pasar real-time (kripto/saham)\n"
    "- news: analisis berita/peristiwa terkini yang relevan\n"
    "- sentiment: analisis sentimen pasar dari berita\n"
    "- risk: analisis risiko (selalu dijalankan terakhir, memakai kesimpulan lensa lain)\n"
    "- self_knowledge: pertanyaan tentang BotNesia sendiri — paket/pricing, billing, "
    "usage limit, channel, fitur dashboard, integrasi, atau konfigurasi AI Agent ini\n"
    "- business: pertanyaan tentang performa bisnis/toko tenant — penjualan, pelanggan, "
    "kelemahan bisnis, cara meningkatkan penjualan, berdasarkan data percakapan historis"
)


class PlannerAgent(BaseAgent):
    name = "planner_agent"
    system_prompt = (
        "Kamu adalah perencana tim analis untuk chatbot bisnis. Tugasmu menentukan "
        "lensa analisis mana yang relevan agar pertanyaan pengguna dijawab secara "
        "mendalam dan terarah. Balas HANYA dalam format JSON."
    )

    async def run(self, context: dict) -> AgentResult:
        user_message = context.get("user_message", "")
        socratic_brief = str(context.get("_socratic_brief") or "").strip()
        first_principle_brief = str(context.get("_first_principle_brief") or "").strip()
        prompt = (
            f"Pertanyaan pengguna: {user_message}\n\n"
            + (f"Brief Socratic internal:\n{socratic_brief}\n\n" if socratic_brief else "")
            + (f"Decomposition first-principles:\n{first_principle_brief}\n\n" if first_principle_brief else "")
            + f"Lensa analisis yang tersedia:\n{_LENS_DESCRIPTIONS}\n\n"
            "Pilih lensa yang relevan untuk pertanyaan ini, tentukan strategi eksekusi, "
            "dan fokus sintesis jawaban akhir.\n\n"
            'Jawab dalam format JSON: {"agents_to_invoke": ["..."], '
            '"execution_strategy": "parallel"|"sequential", "synthesis_focus": "<fokus jawaban akhir>"}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
            default=dict(DEFAULT_PLAN),
        )

        agents = result.get("agents_to_invoke")
        if not isinstance(agents, list):
            agents = []
        agents = [a for a in agents if a in AVAILABLE_LENSES]
        if not agents:
            agents = list(DEFAULT_PLAN["agents_to_invoke"])
        result["agents_to_invoke"] = agents
        result.setdefault("execution_strategy", "parallel")
        result.setdefault("synthesis_focus", "")

        return AgentResult(agent=self.name, success=True, output=result, latency_ms=0)

    async def plan(self, context: dict) -> dict:
        """Convenience: jalankan run() dan kembalikan output dict langsung."""
        return (await self.safe_run(context)).output or dict(DEFAULT_PLAN)
