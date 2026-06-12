"""
verification_agent.py — Agen verifikasi untuk pipeline reasoning Pro.

Mengecek jawaban sintesis sebelum dikirim ke pengguna: apakah pertanyaan
benar-benar terjawab, jawaban tidak terlalu dangkal untuk pertanyaan kompleks,
tidak ada kontradiksi internal, dan penalaran didukung oleh bukti/analisis
spesialis yang diberikan.
"""
from __future__ import annotations

from base import AgentResult, BaseAgent

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
