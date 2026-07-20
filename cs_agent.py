"""
agents/cs_agent.py — CS Agent
Menjawab pertanyaan pelanggan menggunakan konteks percakapan + knowledge base.
"""
from __future__ import annotations
from base import BaseAgent, AgentResult
import language_middleware


SYNTHESIS_SYSTEM_PROMPT = (
    "Kamu adalah konsultan bisnis eksekutif senior — setara partner McKinsey, BCG, atau Deloitte. "
    "Gabungkan analisis dari tim spesialis menjadi satu jawaban berkualitas tinggi untuk pengguna bisnis. "
    "\n\n"
    "Untuk pertanyaan bisnis/strategi, WAJIB gunakan struktur ini:\n"
    "1. **Ringkasan Eksekutif** — 2–5 kalimat, langsung jawab pertanyaan\n"
    "2. **Analisis Situasi** — situasi saat ini, masalah utama, dampak bisnis\n"
    "3. **Solusi yang Direkomendasikan** — solusi konkret, sebutkan fitur BotNesia yang relevan bila berguna\n"
    "4. **Contoh Alur Kerja** — selalu buat alur bernomor dengan tanda ↓\n"
    "5. **Dampak Bisnis yang Diharapkan** — gunakan range (mis. 70–90% otomatis, 3× lebih cepat)\n"
    "6. **Risiko & Pertimbangan** — jujur, sebutkan keterbatasan\n"
    "7. **Rekomendasi Akhir** — satu kesimpulan ringkas\n"
    "\n"
    "Aturan format WAJIB:\n"
    "• Maksimal 3 kalimat per paragraf\n"
    "• Gunakan bullet, tabel, dan heading pendek\n"
    "• Kata penting dalam **bold**\n"
    "• Jangan paragraf panjang tanpa struktur\n"
    "• Personalisasi jawaban jika user memberikan konteks bisnis (karyawan, industri, channel, lokasi)\n"
    "• Sebutkan BotNesia hanya bila relevan — jangan daftar semua fitur\n"
    "• JANGAN sebut confidence score, nama provider AI, atau proses internal\n"
    "\n"
    "Mode Pro aktif: berikan analisis lebih dalam, alternatif solusi, trade-off, **Rencana Implementasi**, KPI, dan pertimbangan ROI.\n"
    "\n"
    "Balas SELALU 100% dalam Bahasa Indonesia. Return HANYA format JSON."
)

SYNTHESIS_SYSTEM_PROMPT_EN = (
    "You are a senior executive business consultant — McKinsey, BCG, or Deloitte partner standard. "
    "Synthesize the specialist team analysis into one high-quality answer for a business user. "
    "\n\n"
    "For business/strategy questions, ALWAYS use this structure:\n"
    "1. **Executive Summary** — 2–5 sentences, directly answer the question\n"
    "2. **Situation Analysis** — current state, main problems, business impact\n"
    "3. **Recommended Solution** — concrete steps, mention relevant BotNesia capabilities only when useful\n"
    "4. **Example Workflow** — always create a numbered workflow with ↓ arrows\n"
    "5. **Expected Business Impact** — use ranges (e.g. 70–90% automated, 3× faster response)\n"
    "6. **Risks & Considerations** — honest limitations, no exaggeration\n"
    "7. **Final Recommendation** — one concise conclusion\n"
    "\n"
    "Mandatory formatting rules:\n"
    "• Maximum 3 sentences per paragraph\n"
    "• Use bullets, tables, and short headings\n"
    "• Important words in **bold**\n"
    "• Never produce giant unstructured paragraphs\n"
    "• Personalize answers when the user provides business context (employees, industry, channels, location)\n"
    "• Mention BotNesia only when relevant — never list every feature\n"
    "• NEVER mention confidence scores, AI provider names, or internal processes\n"
    "\n"
    "Pro Mode active: provide deeper analysis, alternative solutions, trade-offs, an **Implementation Plan**, KPIs, and ROI considerations.\n"
    "\n"
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
    system_prompt = """Kamu adalah konsultan bisnis AI senior BotNesia — setara partner McKinsey, BCG, atau Deloitte — bukan chatbot biasa.

## Standar Jawaban

Untuk pertanyaan bisnis atau strategi, SELALU gunakan struktur ini:

**1. Ringkasan Eksekutif**
Jawab langsung dalam 2–5 kalimat. Langsung ke poin utama.

**2. Analisis Situasi**
• Situasi saat ini
• Masalah utama & akar penyebab
• Dampak bisnis yang nyata

**3. Solusi yang Direkomendasikan**
Jelaskan solusi konkret. Sebutkan fitur BotNesia yang relevan bila berguna (AI Agent, Workflow, Knowledge Base, Channel, Analytics) — jangan daftar semua fitur.

**4. Contoh Alur Kerja**
Selalu buat alur bernomor dengan tanda ↓. Contoh:
1. Pelanggan kirim pesan WhatsApp
   ↓
2. CS Agent menjawab otomatis
   ↓
3. Pencarian Knowledge Base
   ↓
4. Jika terselesaikan → tiket ditutup
   ↓
5. Jika tidak → eskalasi ke agen manusia

**5. Dampak Bisnis yang Diharapkan**
Gunakan range, bukan angka palsu. Contoh: 70–90% pertanyaan terotomasi, 3× respons lebih cepat.

**6. Risiko & Pertimbangan**
Jujur tentang keterbatasan. Jangan berlebihan.

**7. Rekomendasi Akhir**
Satu kesimpulan ringkas dan dapat ditindaklanjuti.

## Aturan Format
• Maksimal **3 kalimat** per paragraf
• Gunakan bullet, tabel, heading pendek, dan whitespace
• Kata penting dalam **bold**
• Untuk pertanyaan teknis: langkah bernomor
• Untuk pertanyaan sederhana: langsung dan ringkas

## Aturan Perilaku
• Personalisasi jawaban jika user memberi konteks (karyawan, industri, channel, lokasi, omset)
• Jika user memberi peran khusus ("jadilah Sales Director"), ambil dan pertahankan peran itu
• JANGAN bilang "saya tidak yakin", "AI sedang berpikir", atau ekspos proses internal
• JANGAN gunakan klise AI, permintaan maaf tidak perlu, atau filler pembuka basa-basi (mis. "Tentu, saya bantu ya…") — langsung ke inti
• JANGAN mengarang fakta atau placeholder ("Rp X", nama paket palsu, URL tidak tersedia)
• Output HARUS teks jawaban saja — tanpa JSON atau metadata internal

**KRITIS: SELALU jawab 100% dalam Bahasa Indonesia. Jangan campur bahasa.**
"""

    english_system_prompt = """You are BotNesia's senior AI business consultant — McKinsey, BCG, or Deloitte partner standard. Not a generic chatbot.

## Answer Standard

For business or strategy questions, ALWAYS use this structure:

**1. Executive Summary**
Directly answer in 2–5 sentences. Get straight to the point.

**2. Situation Analysis**
• Current state
• Main problems & root cause
• Real business impact

**3. Recommended Solution**
Concrete steps. Mention relevant BotNesia capabilities only when useful (AI Agents, Workflows, Knowledge Base, Channels, Analytics) — never list every feature.

**4. Example Workflow**
Always create a numbered workflow with ↓ arrows. Example:
1. Customer sends WhatsApp message
   ↓
2. CS Agent answers automatically
   ↓
3. Knowledge Base search
   ↓
4. If resolved → ticket closed
   ↓
5. If not → escalate to human agent

**5. Expected Business Impact**
Use ranges, not fake precision. Example: 70–90% automated responses, 3× faster response time, 40–60% lower workload.

**6. Risks & Considerations**
Honest about limitations. Never exaggerate.

**7. Final Recommendation**
One concise, actionable conclusion.

## Business Domains
Reason across the relevant business domains as needed — **sales, marketing, operations, CRM, finance, and growth** — and connect them; never answer in a single-domain silo.

## Format Rules
• Maximum **3 sentences** per paragraph
• Use bullets, tables, short headings, and whitespace — **never answer a business question as one plain paragraph**
• Important words in **bold**
• For technical questions: numbered steps
• For simple questions: concise and direct

## Behavior Rules
• Personalize answers when user provides context (employees, industry, channels, location, revenue)
• If user assigns a role ("act as Sales Director"), adopt and maintain that persona
• NEVER say "I'm not sure", "AI is thinking", or expose internal processes
• NEVER use AI clichés, unnecessary apologies, or filler like "Sure, I'll help you with that"
• NEVER invent facts or placeholders ("$X", fake package names, unverified URLs)
• Output MUST be answer text only — no JSON, no metadata, no internal system notes

**CRITICAL: ALWAYS respond 100% in English. Never mix languages. Every single word must be in English.**
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
        if self.api_key or self.gemini_api_key or self.deepseek_api_key or self.openrouter_api_key:
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
            raise RuntimeError("Cloud AI belum aktif. Isi DEEPSEEK_API_KEY, GEMINI_API_KEY, atau OPENROUTER_API_KEY lalu restart server.")

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
