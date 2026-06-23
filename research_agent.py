"""
research_agent.py — Research Agent.

Agen "Digital Employee" untuk riset web/lead discovery/analisis kompetitor.
Menerima goal bebas (mis. "Cari 20 pelanggan potensial untuk bisnis kuliner
di Jakarta"), memecahnya jadi beberapa sub-query, mencari tiap sub-query
lewat web_search_agent.search() (SearXNG -> Tavily, reuse murni, tidak
mengimplementasi ulang HTTP call apapun), me-rank/dedupe hasil lewat
web_search_agent.rank_sources(), lalu menyintesis temuan jadi satu laporan.

Web search BISA nonaktif (SEARXNG_URL/SEARCH_API_KEY kosong di .env, sesuai
keputusan eksplisit user sebelumnya) -- dalam kondisi itu, run_research()
degradasi dengan jujur ke {"success": False, "skipped": True, ...} tanpa
memanggil LLM sintesis, mengikuti pola graceful-degradation yang sama
seperti web_search_agent.search() sendiri.

Tidak ada persistensi/tabel baru di fase ini -- hasil riset dikembalikan
sebagai laporan sekali pakai (caller/operator yang memutuskan tindak lanjut,
mis. menyalin ke workforce_tasks secara manual).
"""
from __future__ import annotations

from base import AgentResult, BaseAgent
import web_search_agent


class ResearchAgent(BaseAgent):
    name = "research_agent"
    system_prompt = (
        "Kamu adalah Research Agent BotNesia. Pecah goal riset jadi beberapa "
        "sub-query pencarian yang konkret dan saling melengkapi (bukan duplikat), "
        "dalam Bahasa Indonesia. Balas HANYA JSON."
    )

    skills = ["web_research", "lead_discovery", "competitive_analysis"]
    tools = ["web_search_agent.search", "web_search_agent.rank_sources"]
    goals = [
        "Mengubah goal riset bebas (mis. 'cari pelanggan potensial') menjadi "
        "temuan konkret dengan sumber yang jelas, tanpa mengarang data.",
    ]

    async def decompose_goal(self, goal: str) -> list[str]:
        """Pecah goal jadi 2-4 sub-query pencarian. Default: goal itu sendiri
        sebagai satu-satunya sub-query kalau LLM gagal/tidak tersedia."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Goal riset: {goal}\n\n"
                    'Balas JSON: {"sub_queries": ["query 1", "query 2", ...]} '
                    "(2-4 sub-query, masing-masing query pencarian web yang konkret)."
                ),
            },
        ]
        result = await self._call_llm_json(
            messages, temperature=0.3, max_tokens=400, default={"sub_queries": [goal]},
        )
        sub_queries = result.get("sub_queries") or [goal]
        return [str(q).strip() for q in sub_queries if str(q).strip()][:4] or [goal]

    async def run_research(
        self, goal: str, *, searxng_url: str = "", tavily_api_key: str = "",
    ) -> dict:
        goal = (goal or "").strip()
        if not goal:
            return {"success": False, "error": "Goal riset kosong."}

        sub_queries = await self.decompose_goal(goal)

        all_results: list[dict] = []
        any_attempted = False
        for query in sub_queries:
            search_result = await web_search_agent.search(
                query, searxng_url=searxng_url, tavily_api_key=tavily_api_key,
            )
            if search_result.get("skipped"):
                continue
            any_attempted = True
            all_results.extend(search_result.get("results") or [])

        if not any_attempted:
            return {
                "success": False,
                "skipped": True,
                "reason": "SEARXNG_URL/SEARCH_API_KEY belum dikonfigurasi — web research tidak aktif.",
                "sub_queries": sub_queries,
            }

        ranked = web_search_agent.rank_sources(all_results)

        if not ranked:
            return {
                "success": True,
                "sub_queries": sub_queries,
                "results": [],
                "summary": "Tidak ditemukan hasil yang relevan dari sumber yang tersedia.",
                "key_findings": [],
            }

        sources_text = "\n".join(
            f"- {r.get('title') or r.get('url')} ({r.get('url')}): {(r.get('snippet') or '')[:300]}"
            for r in ranked[:15]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Kamu adalah Research Agent BotNesia. Sintesis hasil pencarian web di "
                    "bawah menjadi temuan riset yang jujur -- HANYA berdasarkan sumber yang "
                    "diberikan, jangan mengarang. Balas HANYA JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Goal riset: {goal}\n\nHasil pencarian:\n{sources_text}\n\n"
                    'Balas JSON: {"summary": "<ringkasan temuan>", '
                    '"key_findings": ["<temuan 1>", "<temuan 2>", ...]}'
                ),
            },
        ]
        synthesis = await self._call_llm_json(
            messages, temperature=0.3, max_tokens=800,
            default={"summary": "", "key_findings": []},
        )

        return {
            "success": True,
            "sub_queries": sub_queries,
            "results": ranked,
            "summary": synthesis.get("summary") or "",
            "key_findings": synthesis.get("key_findings") or [],
        }

    async def run(self, context: dict) -> AgentResult:
        output = await self.run_research(
            context.get("goal", ""),
            searxng_url=context.get("_searxng_url", ""),
            tavily_api_key=context.get("_search_api_key", ""),
        )
        return AgentResult(agent=self.name, success=True, output=output, latency_ms=0)
