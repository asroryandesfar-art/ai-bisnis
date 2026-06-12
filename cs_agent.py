"""
agents/cs_agent.py — CS Agent
Menjawab pertanyaan pelanggan menggunakan konteks percakapan + knowledge base.
"""
from __future__ import annotations
from base import BaseAgent, AgentResult


SYNTHESIS_SYSTEM_PROMPT = (
    "Kamu adalah konsultan ahli yang menggabungkan analisis dari tim spesialis menjadi satu "
    "jawaban yang koheren, mendalam, dan mudah dipahami untuk pengguna bisnis. Susun jawaban "
    "seperti konsultan profesional: berikan konteks/alasan lalu kesimpulan yang jelas. "
    "Jika confidence rendah, akui ketidakpastian secara eksplisit. "
    "Balas SELALU dalam Bahasa Indonesia, dan HANYA dalam format JSON."
)


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

    def _service_unavailable_response(self) -> str:
        return (
            "Maaf, sistem AI sedang sibuk dan belum bisa memproses pertanyaan Anda saat ini. "
            "Ini bukan karena pertanyaan Anda kurang jelas — coba kirim ulang dalam beberapa menit."
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

            try:
                answer = (await self._call_llm(chat_history, temperature=0.3, max_tokens=1400)).strip()
                retried = False
                if self._is_refusal(answer):
                    retried = True
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
            except Exception:
                # LLM call gagal total (mis. 429 quota harian) — beda dari respons
                # kosong/refusal yang valid, jadi pakai pesan fallback yang lebih jujur.
                output = {"answer": self._service_unavailable_response(), "_llm_unavailable": True}
            else:
                if not answer:
                    answer = self._clarify_response(user_msg)
                output = {"answer": answer}
                if retried:
                    output["_retried"] = True
        else:
            raise RuntimeError("Cloud AI belum aktif. Isi GROQ_API_KEY lalu restart server.")

        return AgentResult(
            agent   = self.name,
            success = True,
            output  = output,
            latency_ms = 0,
        )

    async def synthesize(self, context: dict, specialist_results: dict) -> dict:
        """Gabungkan hasil analisis tim spesialis (reasoning agents) jadi satu jawaban.

        Returns: {"answer", "confidence_score" (0-100), "topics", "suggested_followup",
                  "reasoning_summary"}
        """
        user_message = context.get("user_message", "")
        kb_context = context.get("knowledge_base_context", "")
        plan = context.get("_plan") or {}

        specialist_blocks: list[str] = []
        confidences: list[float] = []
        for lens, out in (specialist_results or {}).items():
            if not out or out.get("skipped"):
                continue
            analysis = (out.get("analysis") or "").strip()
            conclusion = (out.get("conclusion") or "").strip()
            if not analysis and not conclusion:
                continue
            conf = out.get("confidence")
            if isinstance(conf, (int, float)):
                confidences.append(conf)
            block = (
                f"### Analis {lens} (confidence: {conf if conf is not None else 'n/a'})\n"
                f"Analisis: {analysis}\n"
                f"Kesimpulan: {conclusion}"
            )
            limitations = (out.get("limitations") or "").strip()
            if limitations:
                block += f"\nKeterbatasan: {limitations}"
            next_action = (out.get("suggested_next_action") or "").strip()
            if next_action:
                block += f"\nSaran tindak lanjut: {next_action}"
            specialist_blocks.append(block)

        specialist_text = "\n\n".join(specialist_blocks) or "(tidak ada hasil spesialis)"
        avg_confidence = round(sum(confidences) / len(confidences)) if confidences else None

        prompt_parts = [f"Pertanyaan pengguna: {user_message}"]
        if kb_context:
            prompt_parts.append(f"## Konteks tambahan\n{kb_context.strip()}")
        prompt_parts.append(f"## Hasil analisis tim spesialis\n{specialist_text}")
        if avg_confidence is not None:
            prompt_parts.append(f"Rata-rata confidence spesialis: {avg_confidence}/100")
        if plan.get("synthesis_focus"):
            prompt_parts.append(f"## Fokus sintesis\n{plan['synthesis_focus']}")
        feedback = context.get("_verification_feedback")
        if feedback:
            prompt_parts.append(f"## Catatan perbaikan dari verifikasi\n{feedback}")

        prompt_parts.append(
            "Susun jawaban akhir untuk pengguna: gabungkan analisis tim spesialis di atas "
            "menjadi satu jawaban koheren seperti konsultan ahli, dengan konteks/alasan lalu "
            "kesimpulan yang jelas. Jika confidence rendah, akui ketidakpastian secara eksplisit.\n\n"
            'Jawab dalam format JSON: {"answer": "<jawaban lengkap untuk pengguna>", '
            '"confidence_score": <0-100>, "topics": ["..."], '
            '"suggested_followup": "<pertanyaan lanjutan atau null>", '
            '"reasoning_summary": "<ringkasan singkat alur penalaran>"}'
        )
        prompt = "\n\n".join(prompt_parts)

        result = await self._call_llm_json(
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1400,
            default={},
        )

        answer = (result.get("answer") or "").strip()
        if not answer:
            answer = (
                self._service_unavailable_response()
                if result.get("_llm_unavailable")
                else self._clarify_response(user_message)
            )
        result["answer"] = answer
        result.setdefault("confidence_score", avg_confidence if avg_confidence is not None else 50)
        result.setdefault("topics", [])
        result.setdefault("suggested_followup", None)
        result.setdefault("reasoning_summary", "")
        return result
