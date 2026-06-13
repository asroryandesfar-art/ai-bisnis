"""
groq_expert_agent.py — GroqExpertAgent: spesialis Groq API & model LLM Groq
untuk BotNesia.

Tugas:
  - memahami dokumentasi Groq (lihat `groq_knowledge.py`)
  - menjawab pertanyaan teknis tentang Groq API
  - membantu debugging error/rate limit
  - membantu memilih & mengoptimalkan model (kecepatan/biaya/akurasi/
    reasoning/coding/customer service)
  - membantu troubleshooting integrasi

Dipakai sebagai lensa "groq_expert" di pipeline reasoning Pro
(`reasoning_agent.py`). Untuk mode Standard, `groq_knowledge.build_groq_context`
+ `GROQ_EXPERT_BLOCK` disisipkan langsung ke `knowledge_base_context` di
`supervisor.py` (STEP 0.3) sehingga CSAgent bisa menjawab tanpa lensa terpisah.
"""
from __future__ import annotations

from base import AgentResult, BaseAgent
import groq_knowledge as gk

_OUTPUT_INSTRUCTION = (
    "\n\nJawab dalam format JSON: "
    '{"analysis": "<analisis 2-4 kalimat>", "conclusion": "<kesimpulan singkat>", '
    '"confidence": <0-100>, "limitations": "<keterbatasan analisis ini, atau string kosong>", '
    '"suggested_next_action": "<saran tindak lanjut konkret, atau string kosong>"}'
)


class GroqExpertAgent(BaseAgent):
    """Spesialis Groq API & model LLM Groq."""

    name = "groq_expert_agent"
    system_prompt = (
        "Kamu adalah GroqExpertAgent, spesialis Groq API dan model LLM Groq untuk "
        "BotNesia. Jawab pertanyaan teknis, bantu debugging error/rate limit, dan "
        "rekomendasikan/optimalkan pemilihan model (kecepatan, biaya, akurasi, "
        "reasoning, coding, customer service) berdasarkan dokumentasi Groq yang "
        "diberikan. Jika data (mis. rate limit atau daftar model terbaru) bisa "
        "berubah, arahkan user ke https://console.groq.com/docs untuk memastikan. "
        "Balas HANYA dalam format JSON."
    )

    def recommend_model(self, use_case: str) -> dict:
        """Rekomendasi model Groq untuk `use_case` (lihat groq_knowledge.MODEL_CATALOG)."""
        return gk.recommend_model(use_case)

    async def run(self, context: dict) -> AgentResult:
        user_message = context.get("user_message", "")
        groq_context = gk.build_groq_context(user_message)
        if not groq_context:
            return AgentResult(
                agent=self.name,
                success=True,
                output={
                    "analysis": "", "conclusion": "", "confidence": 0,
                    "skipped": True, "reason": "not_groq_question",
                },
                latency_ms=0,
            )

        prompt = (
            f"Pertanyaan pengguna: {user_message}\n\n"
            f"Dokumentasi & katalog model Groq:\n{groq_context}\n\n"
            "Jawab pertanyaan pengguna tentang Groq API/model berdasarkan "
            "dokumentasi di atas. Untuk pertanyaan pemilihan model, sebutkan "
            "model spesifik (id-nya) dan alasannya."
            + _OUTPUT_INSTRUCTION
        )
        result = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=500,
            default={"analysis": "", "conclusion": "", "confidence": 0},
        )
        result.setdefault("analysis", "")
        result.setdefault("conclusion", "")
        result.setdefault("confidence", 0)
        result.setdefault("limitations", "")
        result.setdefault("suggested_next_action", "")
        return AgentResult(agent=self.name, success=True, output=result, latency_ms=0)
