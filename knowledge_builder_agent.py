"""
knowledge_builder_agent.py — Agen AI untuk Auto Knowledge Builder.

Mengubah dokumen mentah (PDF/DOCX/TXT/Markdown/CSV/Website) menjadi
Knowledge Base siap pakai: ringkasan, kategori, tag, suggested intents,
FAQ, SOP, dan Knowledge Quality Score (completeness, redundancy, coverage).
"""
from __future__ import annotations

from base import AgentResult, BaseAgent

KNOWLEDGE_BUILDER_SYSTEM_PROMPT = (
    "Kamu adalah KnowledgeBuilderAgent — AI yang mengubah dokumen bisnis mentah "
    "menjadi basis pengetahuan (knowledge base) siap pakai untuk chatbot customer "
    "service. Tugasmu: meringkas, mengklasifikasi, serta mengekstrak FAQ dan SOP "
    "dari teks yang diberikan, tanpa mengarang informasi yang tidak ada di "
    "dokumen. Balas HANYA dalam format JSON."
)


class KnowledgeBuilderAgent(BaseAgent):
    name = "knowledge_builder_agent"
    system_prompt = KNOWLEDGE_BUILDER_SYSTEM_PROMPT

    async def classify(self, *, title: str, text: str) -> dict:
        """Klasifikasi dokumen: kategori, tag, dan suggested intents.

        Returns: {"categories": [...], "tags": [...], "suggested_intents": [...]}
        """
        excerpt = (text or "")[:4000]
        prompt = (
            f"Judul dokumen: {title or '(tanpa judul)'}\n\n"
            f"Isi dokumen (cuplikan):\n{excerpt}\n\n"
            "Analisis dokumen di atas untuk knowledge base chatbot bisnis. Tentukan:\n"
            "1. categories — 1-3 kategori topik utama (contoh: 'Pengiriman', "
            "'Pembayaran', 'Produk', 'Kebijakan Refund').\n"
            "2. tags — 3-8 tag pendek relevan untuk pencarian.\n"
            "3. suggested_intents — 2-6 intent percakapan yang bisa dijawab dari "
            "dokumen ini (contoh: 'cek_status_pesanan', 'tanya_kebijakan_refund').\n\n"
            'Jawab dalam format JSON: {"categories": ["..."], "tags": ["..."], '
            '"suggested_intents": ["..."]}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=400,
            default={"categories": [], "tags": [], "suggested_intents": []},
        )
        for key in ("categories", "tags", "suggested_intents"):
            if not isinstance(result.get(key), list):
                result[key] = []
            result[key] = [str(v).strip() for v in result[key] if str(v).strip()][:8]
        return result

    async def summarize(self, *, title: str, text: str) -> dict:
        """Ringkasan dokumen untuk knowledge base.

        Returns: {"summary": "..."}
        """
        excerpt = (text or "")[:6000]
        prompt = (
            f"Judul dokumen: {title or '(tanpa judul)'}\n\n"
            f"Isi dokumen (cuplikan):\n{excerpt}\n\n"
            "Tulis ringkasan singkat (3-6 kalimat) yang menjelaskan inti informasi "
            "dokumen ini untuk tim customer service. Fokus pada hal-hal yang akan "
            "ditanyakan pelanggan.\n\n"
            'Jawab dalam format JSON: {"summary": "<ringkasan>"}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
            default={"summary": ""},
        )
        result["summary"] = str(result.get("summary") or "").strip()
        return result

    async def generate_faqs(self, *, title: str, text: str, max_items: int = 8) -> dict:
        """Ekstrak pertanyaan & jawaban FAQ yang jawabannya ADA di dokumen.

        Returns: {"faqs": [{"question": "...", "answer": "...", "category": "..."}]}
        """
        excerpt = (text or "")[:6000]
        prompt = (
            f"Judul dokumen: {title or '(tanpa judul)'}\n\n"
            f"Isi dokumen (cuplikan):\n{excerpt}\n\n"
            f"Ekstrak maksimal {max_items} pasangan FAQ (pertanyaan & jawaban) yang "
            "kemungkinan besar ditanyakan pelanggan dan jawabannya ADA di dalam "
            "dokumen ini. Jangan mengarang informasi yang tidak ada di dokumen. "
            "Setiap FAQ harus punya kategori singkat.\n\n"
            'Jawab dalam format JSON: {"faqs": [{"question": "...", "answer": "...", '
            '"category": "..."}]}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
            default={"faqs": []},
        )
        faqs = result.get("faqs")
        if not isinstance(faqs, list):
            faqs = []
        cleaned = []
        for item in faqs:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question or not answer:
                continue
            cleaned.append({
                "question": question,
                "answer": answer,
                "category": str(item.get("category") or "").strip() or None,
            })
        result["faqs"] = cleaned[:max_items]
        return result

    async def generate_sops(self, *, title: str, text: str, max_items: int = 5) -> dict:
        """Ekstrak SOP (prosedur langkah demi langkah) yang ADA di dokumen.

        Returns: {"sops": [{"title": "...", "steps": ["..."], "category": "..."}]}
        """
        excerpt = (text or "")[:6000]
        prompt = (
            f"Judul dokumen: {title or '(tanpa judul)'}\n\n"
            f"Isi dokumen (cuplikan):\n{excerpt}\n\n"
            f"Identifikasi maksimal {max_items} SOP (Standard Operating Procedure / "
            "prosedur langkah demi langkah) yang ADA atau bisa disimpulkan langsung "
            "dari dokumen ini (contoh: cara melakukan refund, cara melacak pesanan, "
            "cara mengajukan komplain). Jika tidak ada prosedur eksplisit, kembalikan "
            "list kosong — jangan mengarang.\n\n"
            'Jawab dalam format JSON: {"sops": [{"title": "...", "steps": '
            '["langkah 1", "langkah 2"], "category": "..."}]}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1200,
            default={"sops": []},
        )
        sops = result.get("sops")
        if not isinstance(sops, list):
            sops = []
        cleaned = []
        for item in sops:
            if not isinstance(item, dict):
                continue
            sop_title = str(item.get("title") or "").strip()
            steps = item.get("steps")
            if not isinstance(steps, list):
                steps = []
            steps = [str(s).strip() for s in steps if str(s).strip()]
            if not sop_title or not steps:
                continue
            cleaned.append({
                "title": sop_title,
                "steps": steps,
                "category": str(item.get("category") or "").strip() or None,
            })
        result["sops"] = cleaned[:max_items]
        return result

    async def assess_quality(
        self,
        *,
        title: str,
        text: str,
        faq_count: int,
        sop_count: int,
        existing_categories: list[str] | None = None,
    ) -> dict:
        """Nilai kualitas knowledge base hasil dokumen ini.

        Returns: {"completeness_score": 0-100, "redundancy_score": 0-100,
                  "coverage_score": 0-100, "overall_score": 0-100,
                  "missing_topics": [...], "duplicate_groups": [...]}
        """
        excerpt = (text or "")[:4000]
        categories_text = ", ".join(existing_categories or []) or "(belum ada)"
        prompt = (
            f"Judul dokumen: {title or '(tanpa judul)'}\n\n"
            f"Isi dokumen (cuplikan):\n{excerpt}\n\n"
            f"Jumlah FAQ yang dihasilkan: {faq_count}. Jumlah SOP yang dihasilkan: "
            f"{sop_count}.\n"
            f"Kategori knowledge yang sudah tercakup: {categories_text}.\n\n"
            "Nilai kualitas knowledge base dari dokumen ini untuk kebutuhan chatbot "
            "customer service (skor 0-100):\n"
            "1. completeness_score — apakah dokumen ini cukup detail/lengkap untuk "
            "menjawab pertanyaan pelanggan di topiknya?\n"
            "2. redundancy_score — seberapa rendah duplikasi/pengulangan informasi "
            "(100 = tidak ada duplikasi).\n"
            "3. coverage_score — seberapa luas topik penting (kebijakan, harga, "
            "prosedur, kontak) yang tercakup.\n"
            "4. overall_score — skor keseluruhan kualitas knowledge (rata-rata "
            "tertimbang dari ketiga skor di atas).\n"
            "5. missing_topics — daftar topik penting yang TIDAK dibahas di dokumen "
            "ini tapi biasanya dibutuhkan pelanggan (contoh: 'kebijakan garansi', "
            "'cara pembayaran').\n"
            "6. duplicate_groups — daftar string yang menjelaskan kelompok informasi "
            "yang terlihat berulang/redundan (list kosong jika tidak ada).\n\n"
            'Jawab dalam format JSON: {"completeness_score": <0-100>, '
            '"redundancy_score": <0-100>, "coverage_score": <0-100>, '
            '"overall_score": <0-100>, "missing_topics": ["..."], '
            '"duplicate_groups": ["..."]}'
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=600,
            default={
                "completeness_score": 50, "redundancy_score": 100,
                "coverage_score": 50, "overall_score": 50,
                "missing_topics": [], "duplicate_groups": [],
            },
        )
        for key in ("completeness_score", "redundancy_score", "coverage_score", "overall_score"):
            try:
                value = int(result.get(key, 50))
            except (TypeError, ValueError):
                value = 50
            result[key] = max(0, min(100, value))
        for key in ("missing_topics", "duplicate_groups"):
            if not isinstance(result.get(key), list):
                result[key] = []
            result[key] = [str(v).strip() for v in result[key] if str(v).strip()][:10]
        return result

    async def run(self, context: dict) -> AgentResult:
        title = context.get("title", "")
        text = context.get("text", "")
        classification = await self.classify(title=title, text=text)
        summary = await self.summarize(title=title, text=text)
        faqs = await self.generate_faqs(title=title, text=text)
        sops = await self.generate_sops(title=title, text=text)
        quality = await self.assess_quality(
            title=title,
            text=text,
            faq_count=len(faqs.get("faqs", [])),
            sop_count=len(sops.get("sops", [])),
            existing_categories=classification.get("categories"),
        )
        output = {
            **classification,
            **summary,
            **faqs,
            **sops,
            "quality": quality,
        }
        return AgentResult(agent=self.name, success=True, output=output, latency_ms=0)
