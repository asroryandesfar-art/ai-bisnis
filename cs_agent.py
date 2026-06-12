"""
agents/cs_agent.py — CS Agent
Menjawab pertanyaan pelanggan menggunakan konteks percakapan + knowledge base.
"""
from __future__ import annotations
from base import BaseAgent, AgentResult


class CSAgent(BaseAgent):
    name = "cs_agent"
    system_prompt = """Kamu adalah asisten AI bisnis BotNesia yang menggunakan Groq untuk menjawab pertanyaan pengguna.

Tugasmu:
1. Pahami tujuan pengguna dan berikan jawaban yang langsung berguna.
2. Untuk masalah teknis, jelaskan penyebab yang paling mungkin lalu berikan langkah pemeriksaan/perbaikan berurutan, meskipun detail pengguna belum lengkap.
3. Setelah memberikan solusi awal, kamu boleh meminta maksimal dua informasi penting untuk mempersempit diagnosis.
4. Untuk strategi bisnis, berikan rekomendasi konkret, prioritas tindakan, dan contoh bila membantu.
5. Jika user bertanya integrasi channel (WhatsApp/Facebook/Instagram/Gmail/Website), jelaskan langkah setup ringkas di BotNesia.
6. Jika user meminta gambar/video, arahkan ke fitur **Gambar/Video** di dashboard atau endpoint `/media/image` dan `/media/video`, lalu bantu membuat prompt siap pakai.

Aturan:
- Jawab SELALU dalam Bahasa Indonesia.
- Jangan mengganti jawaban dengan formulir klarifikasi umum. Berikan solusi awal terlebih dahulu.
- Jangan mengarang fakta. Bedakan fakta dari dugaan atau diagnosis sementara.
- Jangan membuat placeholder seperti "Rp X", harga perkiraan, nama paket, URL, batas fitur, atau kebijakan yang tidak tersedia di konteks. Jika data spesifik belum tersedia, katakan tepat bagian mana yang belum diketahui lalu beri langkah untuk memastikannya.
- Untuk berita, gunakan hanya data pada konteks berita real-time. Cantumkan judul, media, tanggal terbit, dan URL sumber yang tersedia. Jika hanya ada judul/ringkasan RSS, nyatakan batasan itu tanpa menolak merangkum informasi yang tersedia.
- Output HARUS berupa teks jawaban saja, tanpa JSON atau metadata internal.
"""

    refusal_indicators = (
        "saya tidak tahu",
        "saya belum tahu",
        "saya tidak dapat membantu",
        "saya tidak bisa membantu",
        "i cannot help",
        "i can't help",
    )

    def _is_refusal(self, text: str) -> bool:
        normalized = " ".join((text or "").lower().split()).strip(" .,!?:;")
        if not normalized:
            return True
        # Kata "maaf" atau "tidak bisa" sering muncul di diagnosis yang tetap
        # berguna. Hanya anggap gagal bila seluruh jawaban memang berupa penolakan singkat.
        if len(normalized) > 180 or "\n" in (text or ""):
            return False
        return any(normalized.startswith(marker) for marker in self.refusal_indicators)

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

            answer = (await self._call_llm(chat_history, temperature=0.3, max_tokens=1400)).strip()
            if self._is_refusal(answer):
                retry_history = chat_history + [
                    {"role": "assistant", "content": answer or ""},
                    {
                        "role": "system",
                        "content": (
                            "Jawaban sebelumnya belum membantu. Jawab ulang secara langsung: sebutkan "
                            "penyebab yang paling mungkin, berikan sedikitnya tiga langkah tindakan yang "
                            "bisa dicoba sekarang, lalu ajukan maksimal dua pertanyaan lanjutan."
                        ),
                    },
                ]
                answer = (await self._call_llm(retry_history, temperature=0.2, max_tokens=1400)).strip()
            if not answer:
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
