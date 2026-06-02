"""
agents/cs_agent.py — CS Agent
Menjawab pertanyaan pelanggan menggunakan konteks percakapan + knowledge base.
"""
from __future__ import annotations
import os
from base import BaseAgent, AgentResult
from news_fetcher import build_news_context


class CSAgent(BaseAgent):
    name = "cs_agent"
    system_prompt = """Kamu adalah CS Agent cerdas dalam sistem multi-agent BotNesia.

Tugasmu:
1. Analisa pertanyaan pelanggan dengan cermat
2. Buat jawaban yang akurat, ramah, dan singkat berdasarkan konteks
3. Kalau butuh info tambahan, minta dengan jelas (singkat)
4. Jika user bertanya integrasi channel (WhatsApp/Facebook/Instagram/Gmail/Website), jelaskan langkah setup ringkas di BotNesia.
5. Jika user meminta dibuatkan gambar/video: jelaskan bahwa BotNesia bisa generate media lewat fitur **Gambar/Video** di dashboard (atau endpoint `/media/image` dan `/media/video`), minta prompt yang jelas, lalu berikan prompt yang siap dipakai. Jangan mengatakan "tidak bisa membuat gambar".

Aturan:
- Jawab SELALU dalam Bahasa Indonesia
- Jangan buat-buat informasi — lebih baik jujur tidak tahu, tapi jangan langsung menolak.
- Jika tidak yakin dengan detail, jangan mengatakan "tidak bisa". Minta detail tambahan secara sopan dan tawarkan langkah atau alternatif.
- Output HARUS berupa teks jawaban saja (jangan JSON, jangan menampilkan confidence/topics/metadata).
- Untuk berita/artikel: jika ada bagian "Kutipan relevan", jawaban WAJIB hanya berdasarkan kutipan/teks itu. Jika teks artikel tidak tersedia atau tidak cukup data, katakan "data artikel tidak cukup" dan minta link publisher asli.
"""

    refusal_indicators = [
        "saya tidak tahu",
        "gak tahu",
        "nggak tahu",
        "tidak bisa",
        "maaf",
        "sayangnya",
        "sorry",
    ]

    def _is_refusal(self, text: str) -> bool:
        normalized = (text or "").lower()
        return any(marker in normalized for marker in self.refusal_indicators)

    def _clarify_response(self, user_msg: str) -> str:
        return (
            "Saya ingin membantu lebih baik. "
            "Tolong kirim detail berikut supaya saya bisa memberikan jawaban yang tepat:\n"
            "- masalah atau tujuan Anda\n"
            "- langkah yang sudah dicoba\n"
            "- fitur BotNesia atau channel yang dipakai\n"
            "- pesan error atau hasil yang muncul (jika ada)\n\n"
            "Dengan informasi itu, saya dapat bantu mencari solusi yang cocok."
        )

    async def run(self, context: dict) -> AgentResult:
        user_msg   = context.get("user_message", "")
        kb_context = context.get("knowledge_base_context", "")

        # Mode cloud: pakai LLM supaya bisa jawab pertanyaan bebas.
        if self.api_key:
            history = context.get("messages", [])

            system_parts = [self.system_prompt.strip()]
            if kb_context:
                system_parts.append("\n## Konteks knowledge base\n" + kb_context.strip())

            msg_l = (user_msg or "").lower()
            news_triggers = [
                "berita",
                "news",
                "terbaru",
                "terkini",
                "hari ini",
                "kemarin",
                "tadi",
                "update",
                "trending",
                "viral",
                "headline",
            ]
            if any(k in msg_l for k in news_triggers):
                try:
                    rss_urls = [u.strip() for u in (os.getenv("NEWS_RSS_FEEDS", "") or "").split(",") if u.strip()] or None
                    news_ctx = await build_news_context(user_msg, limit=6, include_bodies=True, rss_urls=rss_urls)
                except Exception:
                    news_ctx = ""
                if news_ctx:
                    system_parts.append(
                        "\n## Berita terbaru (RSS)\n"
                        + news_ctx
                        + "\n\nInstruksi: Gunakan daftar berita di atas sebagai konteks. "
                        "Jika user meminta ringkasan isi artikel, gunakan kutipan/teks artikel yang tersedia. "
                        "Jika user meminta 'berita terkini', rangkum 3-6 poin utama dan sertakan link sumber dari RSS. "
                        "Jika teks artikel tidak tersedia atau belum cukup, katakan 'data artikel tidak cukup' dan minta link publisher."
                    )

            system = "\n\n".join(system_parts).strip()

            chat_history: list[dict] = [{"role": "system", "content": system}]
            for m in (history or [])[-8:]:
                chat_history.append(
                    {
                        "role": m.get("role", "user"),
                        "content": m.get("content", ""),
                    }
                )
            chat_history.append({"role": "user", "content": user_msg})

            answer = await self._call_llm(chat_history, temperature=0.3, max_tokens=900)
            answer = answer.strip()
            if not answer or self._is_refusal(answer):
                answer = self._clarify_response(user_msg)

            output = {
                "answer": answer,
            }
        else:
            raise RuntimeError("Cloud AI belum aktif. Isi GROQ_API_KEY lalu restart server.")

        return AgentResult(
            agent   = self.name,
            success = True,
            output  = output,
            latency_ms = 0,
        )
