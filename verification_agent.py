"""
verification_agent.py — Agen verifikasi untuk pipeline reasoning Pro.

Mengecek jawaban sintesis sebelum dikirim ke pengguna: apakah pertanyaan
benar-benar terjawab, jawaban tidak terlalu dangkal untuk pertanyaan kompleks,
tidak ada kontradiksi internal, dan penalaran didukung oleh bukti/analisis
spesialis yang diberikan.
"""
from __future__ import annotations

from anti_hallucination_engine import score_hallucination_risk as _score_hallucination_risk
from base import AgentResult, BaseAgent
from identity_agent import COMPETITOR_PATTERN

# Frasa promosi/berlebihan yang menandakan jawaban condong ke "iklan".
MARKETING_PHRASES = (
    "anda harus memilih",
    "anda wajib memilih",
    "harus pilih",
    "wajib pilih",
    "wajib memilih",
    "paling baik",
    "yang terbaik",
    "terbaik di",
    "solusi terbaik",
    "nomor satu",
    "no.1",
    "no 1",
    "paling unggul",
    "jauh lebih unggul",
    "pasti lebih baik",
    "tanpa kekurangan",
    "tanpa kelemahan",
    "sempurna",
    "paket enterprise",
)

# Klaim "lebih hebat dari AI lain" tanpa kualifikasi — overclaim.
OVERCLAIM_PHRASES = (
    "lebih pintar dari",
    "lebih hebat dari",
    "lebih canggih dari",
    "lebih unggul dari",
    "lebih baik dari chatgpt",
    "lebih baik dari claude",
    "lebih baik dari gemini",
    "mengalahkan chatgpt",
    "mengalahkan claude",
    "mengalahkan gemini",
    "tidak terkalahkan",
    "tidak ada tandingan",
)

# Kata-kata yang menunjukkan kehati-hatian/kualifikasi (jujur, tidak overclaim).
HEDGE_PHRASES = (
    "kemungkinan",
    "mungkin",
    "tergantung",
    "belum yakin",
    "belum tentu",
    "saat ini",
    "untuk saat ini",
    "bisa jadi",
    "relatif",
)

# Penyebutan keterbatasan/kekurangan secara terbuka.
LIMITATION_PHRASES = (
    "keterbatasan",
    "kekurangan",
    "kelemahan",
    "bukan pengganti",
    "belum sempurna",
    "masih dalam pengembangan",
    "tidak bisa menggantikan",
    "tidak menggantikan",
)

# Konektor penalaran (sebab-akibat) yang menandakan ada reasoning.
REASONING_CONNECTORS = (
    "karena",
    "sehingga",
    "oleh karena itu",
    "akibatnya",
    "artinya",
    "dengan kata lain",
    "maka",
)

# Penanda kesimpulan di akhir jawaban.
CONCLUSION_MARKERS = (
    "jadi",
    "kesimpulannya",
    "kesimpulan",
    "intinya",
    "singkatnya",
    "secara keseluruhan",
)

VERIFICATION_SYSTEM_PROMPT = (
    "Kamu adalah AnswerQualityScorer — quality checker untuk jawaban konsultan AI. "
    "Nilai jawaban secara kritis berdasarkan 8 dimensi: relevansi (sesuai pertanyaan), "
    "kelengkapan, kejelasan, akurasi (sesuai data spesialis, tidak mengarang), reasoning "
    "(ada alur penalaran, bukan sekadar data mentah), kesesuaian dengan maksud user, "
    "apakah ada kesimpulan yang jelas, dan apakah jawaban TIDAK dangkal/generik. "
    "Balas HANYA dalam format JSON."
)


class VerificationAgent(BaseAgent):
    name = "verification_agent"
    system_prompt = VERIFICATION_SYSTEM_PROMPT

    async def verify(self, context: dict, answer: str, specialist_results: dict) -> dict:
        """
        Returns: {"verified": bool, "confidence_score": 0-100, "issues": [...]}
        """
        user_message = context.get("user_message", "")

        specialist_blocks: list[str] = []
        for lens, out in (specialist_results or {}).items():
            if not out or out.get("skipped"):
                continue
            conclusion = (out.get("conclusion") or "").strip()
            if conclusion:
                specialist_blocks.append(f"- {lens}: {conclusion}")
        specialist_text = "\n".join(specialist_blocks) or "(tidak ada hasil spesialis)"

        prompt = (
            f"Pertanyaan pengguna: {user_message}\n\n"
            f"Jawaban yang akan dikirim:\n{answer}\n\n"
            f"Kesimpulan analisis spesialis:\n{specialist_text}\n\n"
            "Nilai jawaban di atas berdasarkan rubrik (0-100, total = confidence_score):\n"
            "1. Relevansi — apakah pertanyaan pengguna benar-benar terjawab?\n"
            "2. Kelengkapan — apakah ada bagian penting yang belum dibahas?\n"
            "3. Kejelasan — apakah mudah dipahami dan terstruktur?\n"
            "4. Akurasi — apakah sesuai analisis spesialis, tidak mengarang fakta?\n"
            "5. Reasoning — apakah ada alur penalaran/sebab-akibat, bukan sekadar data mentah?\n"
            "6. Kesesuaian maksud user — apakah jawaban sesuai apa yang sebenarnya diinginkan user?\n"
            "7. Kesimpulan — apakah ada kesimpulan/rekomendasi yang jelas di akhir?\n"
            "8. Tidak dangkal — apakah jawaban bukan jawaban umum/template/hanya angka?\n\n"
            "Jika ada dimensi yang gagal, jelaskan di 'issues' dan turunkan confidence_score. "
            "verified=true HANYA jika confidence_score >= 80.\n\n"
            'Jawab dalam format JSON: {"verified": true|false, "confidence_score": <0-100>, '
            '"issues": ["<masalah 1>", "..."]}'
        )

        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
            default={"verified": True, "confidence_score": 100, "issues": []},
        )
        result.setdefault("verified", True)
        result.setdefault("confidence_score", 100)
        if not isinstance(result.get("issues"), list):
            result["issues"] = []
        return result

    async def run(self, context: dict) -> AgentResult:
        answer = context.get("bot_response", "")
        specialist_results = context.get("specialist_results", {})
        output = await self.verify(context, answer, specialist_results)
        return AgentResult(agent=self.name, success=True, output=output, latency_ms=0)

    def score_meta_answer(
        self, question: str, answer: str, reasoning_brief: dict | None = None
    ) -> dict:
        """Cek heuristik (tanpa LLM) khusus untuk pertanyaan "meta" — identitas,
        perbandingan dengan AI lain, kelebihan/kelemahan, posisi BotNesia.

        Dipakai oleh `SupervisorAgent` untuk memutuskan apakah jawaban perlu
        ditulis ulang agar sesuai Truthfulness Policy & Comparison Engine
        (jujur, tidak overclaim, mengakui keterbatasan, ada kesimpulan).

        Returns: {
            "truthfulness_score": 0-100,
            "reasoning_score": 0-100,
            "comparison_score": 0-100,
            "self_awareness_score": 0-100,
            "marketing_bias_score": 0-100,
            "needs_rewrite": bool,
            "issues": [...],
        }
        """
        brief = reasoning_brief or {}
        text = (answer or "").lower()

        marketing_hits = sum(1 for p in MARKETING_PHRASES if p in text)
        overclaim_hits = sum(1 for p in OVERCLAIM_PHRASES if p in text)
        hedge_hits = sum(1 for p in HEDGE_PHRASES if p in text)
        limitation_hits = sum(1 for p in LIMITATION_PHRASES if p in text)
        reasoning_hits = sum(1 for p in REASONING_CONNECTORS if p in text)
        conclusion_hits = sum(1 for p in CONCLUSION_MARKERS if p in text)
        competitor_mentioned = bool(COMPETITOR_PATTERN.search(text))

        marketing_bias_score = min(100, marketing_hits * 35 + overclaim_hits * 25)

        truthfulness_score = 100
        truthfulness_score -= marketing_hits * 25
        truthfulness_score -= overclaim_hits * 30
        if brief.get("is_meta") and limitation_hits == 0:
            truthfulness_score -= 20
        truthfulness_score += min(10, hedge_hits * 5)
        truthfulness_score = max(0, min(100, truthfulness_score))

        reasoning_score = 40
        reasoning_score += min(40, reasoning_hits * 15)
        reasoning_score += 20 if conclusion_hits else 0
        reasoning_score = max(0, min(100, reasoning_score))

        if brief.get("is_comparison"):
            comparison_score = 0
            comparison_score += 25 if competitor_mentioned else 0
            comparison_score += 25 if (limitation_hits or hedge_hits) else 0
            comparison_score += 25 if "botnesia" in text else 0
            comparison_score += 25 if conclusion_hits else 0
        else:
            comparison_score = 100

        if brief.get("is_meta"):
            self_awareness_score = 0
            self_awareness_score += 40 if limitation_hits else 0
            self_awareness_score += 30 if "botnesia" in text else 0
            self_awareness_score += 30 if (conclusion_hits or hedge_hits) else 0
            self_awareness_score = min(100, self_awareness_score)
        else:
            self_awareness_score = 100

        issues: list[str] = []
        if marketing_hits:
            issues.append("Jawaban memuat bahasa promosi/berlebihan.")
        if overclaim_hits:
            issues.append("Jawaban mengklaim lebih unggul dari AI lain tanpa kualifikasi yang jujur.")
        if brief.get("is_meta") and limitation_hits == 0:
            issues.append("Jawaban tidak menyebut keterbatasan BotNesia.")
        if brief.get("is_comparison") and not competitor_mentioned:
            issues.append("Jawaban tidak menyebut AI yang dibandingkan oleh pengguna.")
        if brief.get("is_comparison") and not conclusion_hits:
            issues.append("Jawaban perbandingan tidak memberi kesimpulan/rekomendasi.")

        needs_rewrite = (
            marketing_bias_score >= 50
            or truthfulness_score < 60
            or (brief.get("is_comparison") and comparison_score < 50)
        )

        return {
            "truthfulness_score": truthfulness_score,
            "reasoning_score": reasoning_score,
            "comparison_score": comparison_score,
            "self_awareness_score": self_awareness_score,
            "marketing_bias_score": marketing_bias_score,
            "needs_rewrite": needs_rewrite,
            "issues": issues,
        }

    def score_hallucination_risk(
        self, answer: str, knowledge_base_context: str = "", specialist_results: dict | None = None
    ) -> dict:
        """Cek heuristik (tanpa LLM) risiko hallucination untuk SEMUA jawaban.

        Delegasi ke `anti_hallucination_engine.score_hallucination_risk` —
        dipakai oleh `SupervisorAgent` untuk memutuskan apakah jawaban perlu
        ditulis ulang karena memuat klaim angka yang tidak didukung konteks
        atau bahasa "pasti"/"dijamin" tanpa kualifikasi.

        Returns: {
            "risk_score": 0-100,
            "unsupported_claims": [...],
            "overconfidence_hits": int,
            "needs_rewrite": bool,
        }
        """
        return _score_hallucination_risk(answer, knowledge_base_context, specialist_results)
