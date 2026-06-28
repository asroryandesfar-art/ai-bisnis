"""
agents/cs_agent.py — CS Agent
Menjawab pertanyaan pelanggan menggunakan konteks percakapan + knowledge base.
"""
from __future__ import annotations
from base import BaseAgent, AgentResult
import language_middleware


SYNTHESIS_SYSTEM_PROMPT = (
    "Kamu adalah konsultan bisnis tingkat eksekutif. "
    "Gabungkan analisis dari tim spesialis menjadi satu jawaban komprehensif untuk pengguna bisnis. "
    "Untuk pertanyaan bisnis/strategi, susun dengan struktur profesional: "
    "Ringkasan Eksekutif → Analisis Masalah → Akar Masalah → Strategi → Rencana Implementasi → "
    "KPI & Metrik → Manfaat & ROI yang Diharapkan → Risiko & Mitigasi → Rekomendasi Akhir. "
    "Gunakan tabel, bullet point, dan struktur yang rapi — jangan paragraf panjang tanpa struktur. "
    "Jangan pernah menyebut confidence score, nama provider AI, atau proses internal. "
    "Balas SELALU dalam Bahasa Indonesia, dan HANYA dalam format JSON."
)

SYNTHESIS_SYSTEM_PROMPT_EN = (
    "You are an executive-level business consultant (McKinsey standard). "
    "Synthesize the specialist team analysis into one comprehensive answer for a business user. "
    "For business/strategy questions, use this structure: "
    "Executive Summary → Problem Analysis → Root Cause → Recommended Strategy → Implementation Plan → "
    "KPIs & Metrics → Expected Benefits & ROI → Risks & Mitigation → Alternative Options → Final Recommendation. "
    "Use tables, bullet points, and clear structure — never plain paragraphs for business questions. "
    "Never mention confidence scores, AI provider names, or internal reasoning processes. "
    "ALWAYS respond 100% in English. Return ONLY JSON format."
)


class CSAgent(BaseAgent):
    name = "cs_agent"
    skills = ["customer_conversation", "intent_understanding", "refusal_handling"]
    tools: list[str] = []
    goals = [
        "Menjawab pertanyaan pelanggan secara langsung berguna menggunakan konteks percakapan + knowledge base.",
        "Menjaga jawaban jujur dan bebas placeholder/karangan saat data spesifik belum tersedia.",
    ]
    system_prompt = """Kamu adalah asisten AI bisnis BotNesia yang memberikan konsultasi tingkat enterprise, bukan sekadar chatbot biasa.

Kemampuan utama:
1. **Strategi bisnis**: berikan rekomendasi konkret, prioritas tindakan, dan analisis ROI — bukan saran generik.
2. **Masalah teknis**: diagnosis akar masalah dan langkah perbaikan berurutan (bahkan tanpa detail lengkap dari user).
3. **Pertanyaan bisnis** (penjualan, marketing, operasional, CRM, keuangan, pertumbuhan, AI, SaaS): jawab seperti konsultan senior, gunakan tabel/bullet/metrik.
4. **Integrasi channel** (WhatsApp/Facebook/Instagram/Gmail/Website): jelaskan langkah setup ringkas di BotNesia.
5. **Multimedia**: jika user meminta gambar, sistem AKAN OTOMATIS membuatnya — jelaskan singkat apa yang dibuat. Untuk analisis gambar, dokumen (PDF/DOCX/XLSX/PPTX), atau voice, arahkan ke **Multimedia Studio** di dashboard.

Aturan format:
- Untuk pertanyaan bisnis/strategi: wajib gunakan bullet point, tabel, atau langkah bernomor — jangan paragraf panjang.
- Untuk pertanyaan teknis: berikan langkah bernomor.
- Untuk pertanyaan sederhana: langsung dan ringkas.

Aturan perilaku:
- Jika user memberikan peran khusus ("jadilah Sales Director", "berperan sebagai CEO saya"), ambil dan pertahankan peran itu sepanjang percakapan.
- Jangan pernah berkata "saya tidak yakin", "AI sedang berpikir", atau mengekspos reasoning internal.
- Jangan gunakan klise AI atau minta maaf yang tidak perlu.
- Jangan mengarang fakta atau buat placeholder seperti "Rp X", nama paket palsu, atau URL yang tidak tersedia di konteks.
- Output HARUS berupa teks jawaban saja, tanpa JSON atau metadata internal.

KRITIS: SELALU jawab 100% dalam Bahasa Indonesia. Setiap kata harus Bahasa Indonesia. Jangan mencampur bahasa.
"""

    english_system_prompt = """You are BotNesia's intelligent business AI assistant — built to deliver enterprise-grade consulting, not generic chatbot responses.

Core capabilities:
1. **Business strategy**: give concrete recommendations, prioritized actions, and ROI-focused insights — never vague advice.
2. **Technical issues**: diagnose with root cause + ordered fix steps, even with incomplete user details.
3. **Business intelligence** (sales, marketing, operations, CRM, finance, growth, AI, SaaS, workflow): respond like a senior consultant — use tables, bullets, metrics, KPIs.
4. **Channel integrations** (WhatsApp/Facebook/Instagram/Gmail/Website): explain concise BotNesia setup steps.
5. **Multimedia**: if the user requests image creation, the system WILL automatically generate it — briefly describe what was created. For image analysis, document generation (PDF/DOCX/XLSX/PPTX), or voice, direct to Multimedia Studio.

Format rules:
- For business/strategy questions: MUST use bullet points, tables, or numbered steps — never plain paragraphs.
- For technical questions: provide numbered steps.
- For simple questions: be concise and direct.

Behavior rules:
- If the user assigns you a specific role ("act as Sales Director", "be my CEO"), adopt and maintain that persona throughout the conversation.
- Never say "I'm not sure", "AI is thinking", "based on available data", or expose internal reasoning.
- Never use AI clichés, unnecessary apologies, or filler phrases like "Sure, I'll help you with that."
- Do not invent facts or create placeholders ("Rp X", fake package names, unverified URLs, unavailable policies).
- Output MUST be the answer text only — no JSON, no metadata, no internal system notes.

CRITICAL: ALWAYS respond 100% in English. Every single word must be in English. Never mix languages.
"""

    def _selected_language(self, context: dict) -> language_middleware.LangCode:
        return language_middleware.normalize_language(context.get("selected_language")) or "id"

    def _system_prompt_for(self, language: language_middleware.LangCode) -> str:
        return self.english_system_prompt if language == "en" else self.system_prompt

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

    def _clarify_response(self, user_msg: str, language: language_middleware.LangCode = "id") -> str:
        if language == "en":
            return (
                "I want to help more accurately. Please send these details so I can give the right answer:\n"
                "- your issue or goal\n"
                "- steps you have already tried\n"
                "- the BotNesia feature or channel you are using\n"
                "- any error message or result you see, if available\n\n"
                "With that information, I can help find the right solution."
            )
        return (
            "Saya ingin membantu lebih baik. "
            "Tolong kirim detail berikut supaya saya bisa memberikan jawaban yang tepat:\n"
            "- masalah atau tujuan Anda\n"
            "- langkah yang sudah dicoba\n"
            "- fitur BotNesia atau channel yang dipakai\n"
            "- pesan error atau hasil yang muncul (jika ada)\n\n"
            "Dengan informasi itu, saya dapat bantu mencari solusi yang cocok."
        )

    def _service_unavailable_response(self, language: language_middleware.LangCode = "id") -> str:
        if language == "en":
            return (
                "Sorry, the AI system is busy and cannot process your question right now. "
                "This is not because your question is unclear. Please try again in a few minutes."
            )
        return (
            "Maaf, sistem AI sedang sibuk dan belum bisa memproses pertanyaan Anda saat ini. "
            "Ini bukan karena pertanyaan Anda kurang jelas — coba kirim ulang dalam beberapa menit."
        )

    async def run(self, context: dict) -> AgentResult:
        user_msg   = context.get("user_message", "")
        kb_context = str(context.get("knowledge_base_context") or "")
        selected_language = self._selected_language(context)

        # Mode cloud: pakai LLM supaya bisa jawab pertanyaan bebas.
        if self.api_key or self.gemini_api_key:
            history = context.get("messages", [])

            system_parts = [self._system_prompt_for(selected_language).strip()]
            if kb_context:
                kb_heading = "\n## Knowledge base context\n" if selected_language == "en" else "\n## Konteks knowledge base\n"
                system_parts.append(kb_heading + kb_context.strip())
            feedback = str(context.get("_verification_feedback") or "").strip()
            if feedback:
                feedback_heading = "\n## Verification improvement notes\n" if selected_language == "en" else "\n## Catatan perbaikan dari verifikasi\n"
                system_parts.append(feedback_heading + feedback)
            first_principle_brief = str(context.get("_first_principle_brief") or "").strip()
            if first_principle_brief:
                first_principle_instruction = (
                    "\nBuild the answer from basic facts and cause-effect relationships. Do not jump to one cause without evidence. Present hypotheses as hypotheses and give ways to test them."
                    if selected_language == "en" else
                    "\nBangun jawaban dari fakta dasar dan hubungan sebab-akibat. Jangan melompat ke satu penyebab tanpa bukti. Sajikan hipotesis sebagai hipotesis dan berikan cara mengujinya."
                )
                system_parts.append(
                    "\n## Decomposition first-principles internal\n" + first_principle_brief
                    + first_principle_instruction
                )
            socratic_brief = str(context.get("_socratic_brief") or "").strip()
            if socratic_brief:
                socratic_heading = (
                    "\n## Internal Socratic brief (do not expose as chain-of-thought)\n"
                    if selected_language == "en" else
                    "\n## Brief Socratic internal (jangan tampilkan sebagai proses berpikir)\n"
                )
                socratic_instruction = (
                    "\nUse this brief to identify assumptions, acknowledge missing data, consider alternatives, and avoid risky claims. Provide initial help; if needed, ask at most two important clarifying questions."
                    if selected_language == "en" else
                    "\nGunakan brief ini untuk menandai asumsi, mengakui data yang kurang, mempertimbangkan alternatif, dan menghindari klaim berisiko. Berikan bantuan awal; bila perlu ajukan maksimal dua klarifikasi penting."
                )
                system_parts.append(
                    socratic_heading
                    + socratic_brief
                    + socratic_instruction
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
                                "The previous answer was not helpful enough. Answer again directly: state the most likely cause, provide at least three actions the user can try now, then ask at most two follow-up questions."
                                if selected_language == "en" else
                                "Jawaban sebelumnya belum membantu. Jawab ulang secara langsung: sebutkan penyebab yang paling mungkin, berikan sedikitnya tiga langkah tindakan yang bisa dicoba sekarang, lalu ajukan maksimal dua pertanyaan lanjutan."
                            ),
                        },
                    ]
                    answer = (await self._call_llm(retry_history, temperature=0.2, max_tokens=1400)).strip()
            except Exception:
                # LLM call gagal total (mis. 429 quota harian) — beda dari respons
                # kosong/refusal yang valid, jadi pakai pesan fallback yang lebih jujur.
                output = {"answer": self._service_unavailable_response(selected_language), "_llm_unavailable": True}
            else:
                if not answer:
                    answer = self._clarify_response(user_msg, selected_language)
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

    async def revise_with_critique(
        self, context: dict, draft_answer: str, critique: dict, specialist_results: dict | None = None,
    ) -> dict:
        """Revise one draft using actionable adversarial findings, at most once."""
        from devil_advocate_agent import format_devil_critique

        critique_brief = format_devil_critique(critique)
        if not critique.get("needs_revision") or not critique_brief:
            return {"answer": draft_answer, "revised": False}
        lang = self._selected_language(context)
        is_en = (lang == "en")
        evidence = []
        knowledge = str(context.get("knowledge_base_context") or "").strip()
        if knowledge:
            label = "Available knowledge/data:\n" if is_en else "Knowledge/data tersedia:\n"
            evidence.append(label + knowledge[:5000])
        for name, output in (specialist_results or {}).items():
            if isinstance(output, dict) and output.get("conclusion"):
                evidence.append(f"{name}: {output['conclusion']}")
        if is_en:
            prompt = (
                f"User question: {context.get('user_message', '')}\n\n"
                f"Draft answer: {draft_answer}\n\n"
                f"Internal critique:\n{critique_brief}\n\n"
                + ("\n\n".join(evidence) if evidence else "No additional evidence.")
                + "\n\nRevise the draft into an objective, balanced answer: remove or soften unsupported claims, "
                  "explain assumptions and trade-offs, and note that alternatives may be better in certain conditions "
                  "where relevant. Do not mention internal processes or the critique system. Do not add new facts. "
                  'Reply JSON: {"answer": "revised answer"}.'
            )
            sys_msg = "You are a neutral, evidence-based consulting answer editor. Reply ONLY JSON."
        else:
            prompt = (
                f"Pertanyaan pengguna: {context.get('user_message', '')}\n\n"
                f"Draft jawaban: {draft_answer}\n\n"
                f"Kritik internal:\n{critique_brief}\n\n"
                + ("\n\n".join(evidence) if evidence else "Tidak ada bukti tambahan.")
                + "\n\nRevisi draft menjadi jawaban yang objektif: hapus atau lunakkan klaim tanpa bukti, "
                  "jelaskan asumsi dan trade-off, dan sebutkan bahwa alternatif dapat lebih unggul pada "
                  "kondisi tertentu bila relevan. Jangan menyebut proses internal. Jangan menambah fakta baru. "
                  'Balas JSON: {"answer": "jawaban revisi"}.'
            )
            sys_msg = "Kamu adalah editor jawaban konsultan yang netral, evidence-based. Balas HANYA JSON."
        result = await self._call_llm_json(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1, max_tokens=1400, default={"answer": draft_answer},
        )
        revised = str(result.get("answer") or draft_answer).strip()
        return {"answer": revised, "revised": revised != draft_answer}

    async def synthesize(self, context: dict, specialist_results: dict) -> dict:
        """Gabungkan hasil analisis tim spesialis (reasoning agents) jadi satu jawaban.

        Returns: {"answer", "confidence_score" (0-100), "topics", "suggested_followup",
                  "reasoning_summary"}
        """
        user_message = context.get("user_message", "")
        kb_context = str(context.get("knowledge_base_context") or "")
        selected_language = self._selected_language(context)
        plan = context.get("_plan") or {}
        socratic_brief = str(context.get("_socratic_brief") or "").strip()
        first_principle_brief = str(context.get("_first_principle_brief") or "").strip()

        is_en = (selected_language == "en")

        specialist_blocks: list[str] = []
        confidences: list[float] = []
        for lens, out in (specialist_results or {}).items():
            if not out or out.get("skipped"):
                continue
            analysis = str(out.get("analysis") or "").strip()
            conclusion = str(out.get("conclusion") or "").strip()
            if not analysis and not conclusion:
                continue
            conf = out.get("confidence")
            if isinstance(conf, (int, float)):
                confidences.append(conf)
            if is_en:
                block = (
                    f"### {lens.replace('_', ' ').title()} Analysis\n"
                    f"Analysis: {analysis}\n"
                    f"Conclusion: {conclusion}"
                )
                limitations = str(out.get("limitations") or "").strip()
                if limitations:
                    block += f"\nLimitations: {limitations}"
                next_action = str(out.get("suggested_next_action") or "").strip()
                if next_action:
                    block += f"\nNext action: {next_action}"
            else:
                block = (
                    f"### Analis {lens}\n"
                    f"Analisis: {analysis}\n"
                    f"Kesimpulan: {conclusion}"
                )
                limitations = str(out.get("limitations") or "").strip()
                if limitations:
                    block += f"\nKeterbatasan: {limitations}"
                next_action = str(out.get("suggested_next_action") or "").strip()
                if next_action:
                    block += f"\nSaran tindak lanjut: {next_action}"
            specialist_blocks.append(block)

        no_specialist = "(no specialist results)" if is_en else "(tidak ada hasil spesialis)"
        specialist_text = "\n\n".join(specialist_blocks) or no_specialist
        avg_confidence = round(sum(confidences) / len(confidences)) if confidences else None

        if is_en:
            prompt_parts = [f"User question: {user_message}"]
            if first_principle_brief:
                prompt_parts.append("## Internal first-principles decomposition\n" + first_principle_brief)
            if socratic_brief:
                prompt_parts.append("## Internal Socratic brief (do not surface as reasoning)\n" + socratic_brief)
            if kb_context:
                prompt_parts.append(f"## Additional context\n{kb_context.strip()}")
            prompt_parts.append(f"## Specialist team analysis\n{specialist_text}")
            if plan.get("synthesis_focus"):
                prompt_parts.append(f"## Synthesis focus\n{plan['synthesis_focus']}")
            devil_feedback = context.get("_devil_advocate_feedback")
            if devil_feedback:
                prompt_parts.append(f"## Objectivity critique (must follow)\n{devil_feedback}")
            feedback = context.get("_verification_feedback")
            if feedback:
                prompt_parts.append(f"## Verification improvement notes\n{feedback}")
            prompt_parts.append(
                "Build the final answer for the user by synthesizing the specialist analysis above. "
                "Deliver executive-level output: structured, concrete, and actionable. "
                "Never mention confidence scores, AI providers, or internal reasoning. "
                'Return ONLY JSON: {"answer": "<full answer>", '
                '"confidence_score": <0-100>, "topics": ["..."], '
                '"suggested_followup": "<follow-up question or null>", '
                '"reasoning_summary": "<brief internal reasoning summary>"}'
            )
        else:
            prompt_parts = [f"Pertanyaan pengguna: {user_message}"]
            if first_principle_brief:
                prompt_parts.append("## Decomposition first-principles internal\n" + first_principle_brief)
            if socratic_brief:
                prompt_parts.append("## Brief Socratic internal (jangan uraikan proses berpikir)\n" + socratic_brief)
            if kb_context:
                prompt_parts.append(f"## Konteks tambahan\n{kb_context.strip()}")
            prompt_parts.append(f"## Hasil analisis tim spesialis\n{specialist_text}")
            if plan.get("synthesis_focus"):
                prompt_parts.append(f"## Fokus sintesis\n{plan['synthesis_focus']}")
            devil_feedback = context.get("_devil_advocate_feedback")
            if devil_feedback:
                prompt_parts.append(f"## Kritik objektivitas internal yang tetap wajib dipatuhi\n{devil_feedback}")
            feedback = context.get("_verification_feedback")
            if feedback:
                prompt_parts.append(f"## Catatan perbaikan dari verifikasi\n{feedback}")
            prompt_parts.append(
                "Susun jawaban akhir untuk pengguna: gabungkan analisis tim spesialis di atas "
                "menjadi satu jawaban komprehensif tingkat eksekutif — konkret, terstruktur, dan actionable. "
                "Jangan menyebut confidence score, nama provider AI, atau proses internal.\n\n"
                'Jawab dalam format JSON: {"answer": "<jawaban lengkap untuk pengguna>", '
                '"confidence_score": <0-100>, "topics": ["..."], '
                '"suggested_followup": "<pertanyaan lanjutan atau null>", '
                '"reasoning_summary": "<ringkasan singkat alur penalaran>"}'
            )

        prompt = "\n\n".join(prompt_parts)

        result = await self._call_llm_json(
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT_EN if is_en else SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
            default={},
        )

        answer = str(result.get("answer") or "").strip()
        if not answer:
            answer = (
                self._service_unavailable_response(selected_language)
                if result.get("_llm_unavailable")
                else self._clarify_response(user_message, selected_language)
            )
        result["answer"] = answer
        result.setdefault("confidence_score", avg_confidence if avg_confidence is not None else 50)
        result.setdefault("topics", [])
        result.setdefault("suggested_followup", None)
        result.setdefault("reasoning_summary", "")
        return result
