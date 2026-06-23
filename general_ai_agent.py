"""
general_ai_agent.py — General AI Agent.

Agen "Digital Employee" untuk pertanyaan umum di luar topik bisnis tenant
(pengetahuan umum, terjemahan, penulisan kreatif, sains, hitung-hitungan).

PENTING: jawaban chat sesungguhnya untuk pertanyaan umum TETAP dihasilkan
oleh cs_agent.py, dipandu oleh GENERAL_AI_BLOCK (general_ai_engine.py) yang
disuntikkan lewat reasoning_controller.py -- jalur itu sudah stabil dan
teruji, tidak diubah. Kelas ini didaftarkan di SupervisorAgent untuk
kelengkapan identitas/registry Agent OS (skills/tools/goals per-agent,
sesuai visi "Digital Employee"), BUKAN dipanggil di hot path chat.
"""
from __future__ import annotations

from base import AgentResult, BaseAgent


class GeneralAIAgent(BaseAgent):
    name = "general_ai_agent"
    system_prompt = (
        "GeneralAIAgent tidak dipanggil di jalur chat -- jawaban pertanyaan umum "
        "dihasilkan cs_agent.py dengan panduan GENERAL_AI_BLOCK."
    )

    skills = [
        "general_knowledge",
        "translation",
        "creative_writing",
        "summarization",
        "basic_math",
    ]
    tools: list[str] = []
    goals = [
        "Menjawab pertanyaan umum di luar topik bisnis tenant secara akurat dan "
        "lengkap, tanpa menolak atau mengarahkan ke topik bisnis.",
    ]

    async def run(self, context: dict) -> AgentResult:
        return AgentResult(
            agent=self.name,
            success=True,
            output={
                "skills": self.skills,
                "tools": self.tools,
                "goals": self.goals,
                "note": (
                    "Jawaban General AI sesungguhnya dihasilkan cs_agent.py + "
                    "GENERAL_AI_BLOCK; agent ini terdaftar untuk kelengkapan "
                    "registry Agent OS."
                ),
            },
            latency_ms=0,
        )
