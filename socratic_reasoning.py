"""Structured pre-answer reflection without exposing private chain-of-thought."""
from __future__ import annotations

from base import AgentResult, BaseAgent

RISK_LEVELS = {"low", "medium", "high"}

DEFAULT_REVIEW = {
    "interpreted_question": "",
    "user_goal": "",
    "assumptions": [],
    "ambiguities": [],
    "available_evidence": [],
    "missing_information": [],
    "alternative_perspectives": [],
    "risk_if_wrong": "medium",
    "answer_strategy": "Berikan jawaban berbasis data yang tersedia, tandai asumsi, dan akui keterbatasan.",
    "needs_clarification": False,
    "clarifying_questions": [],
}

SOCRATIC_SYSTEM_PROMPT = """Kamu adalah Socratic Reasoning Engine internal untuk konsultan AI senior.
Tugasmu BUKAN menjawab pengguna. Sebelum agent lain menjawab, telaah permintaan secara kritis:
- apa yang sebenarnya ditanyakan dan tujuan pengguna;
- asumsi serta kemungkinan salah paham;
- data yang tersedia dan yang belum tersedia;
- sudut pandang alternatif yang masuk akal;
- risiko bila jawaban salah;
- strategi jawaban paling aman dan berguna.

Hasil harus berupa reasoning brief yang ringkas, faktual, dan dapat diaudit. Jangan menulis monolog,
langkah berpikir rahasia, atau jawaban final. Jangan mengarang data. Balas HANYA dalam format JSON."""


class SocraticReasoningEngine(BaseAgent):
    name = "socratic_reasoning_engine"
    system_prompt = SOCRATIC_SYSTEM_PROMPT

    async def run(self, context: dict) -> AgentResult:
        user_message = str(context.get("user_message") or "").strip()
        history = context.get("messages") or []
        knowledge = str(context.get("knowledge_base_context") or "").strip()
        evidence_note = knowledge[:5000] if knowledge else "(tidak ada knowledge base tambahan)"
        history_note = "\n".join(
            f"{str(item.get('role') or 'user').upper()}: {str(item.get('content') or '')[:600]}"
            for item in history[-6:]
        ) or "(tidak ada riwayat)"
        prompt = f"""Pesan pengguna:\n{user_message}\n\nRiwayat relevan:\n{history_note}\n\nData/knowledge yang tersedia:\n{evidence_note}\n\nBuat brief JSON dengan schema berikut:
{{
  "interpreted_question": "ringkasan pertanyaan sebenarnya",
  "user_goal": "hasil yang ingin dicapai pengguna",
  "assumptions": ["asumsi yang perlu dijaga"],
  "ambiguities": ["potensi salah paham"],
  "available_evidence": ["data yang benar-benar tersedia"],
  "missing_information": ["data penting yang belum tersedia"],
  "alternative_perspectives": ["sudut pandang alternatif"],
  "risk_if_wrong": "low|medium|high",
  "answer_strategy": "cara menjawab secara akurat, tidak dangkal, dan berguna",
  "needs_clarification": true|false,
  "clarifying_questions": ["maksimal dua pertanyaan paling bernilai"]
}}

Aturan: needs_clarification=true hanya jika kekurangan data material dapat mengubah jawaban.
Meski true, strategi harus tetap memberi bantuan awal berbasis data yang ada, bukan hanya menolak menjawab."""
        review = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=700,
            default={**DEFAULT_REVIEW, "interpreted_question": user_message, "user_goal": user_message},
        )
        review = self._normalize(review, user_message)
        return AgentResult(agent=self.name, success=True, output=review, latency_ms=0)

    @staticmethod
    def _normalize(review: dict, user_message: str) -> dict:
        normalized = dict(DEFAULT_REVIEW)
        normalized.update(review or {})
        normalized["interpreted_question"] = str(normalized.get("interpreted_question") or user_message)[:1000]
        normalized["user_goal"] = str(normalized.get("user_goal") or normalized["interpreted_question"])[:1000]
        for key in ("assumptions", "ambiguities", "available_evidence", "missing_information", "alternative_perspectives"):
            value = normalized.get(key)
            normalized[key] = [str(item)[:500] for item in value[:8]] if isinstance(value, list) else []
        risk = str(normalized.get("risk_if_wrong") or "medium").lower()
        normalized["risk_if_wrong"] = risk if risk in RISK_LEVELS else "medium"
        normalized["answer_strategy"] = str(normalized.get("answer_strategy") or DEFAULT_REVIEW["answer_strategy"])[:1500]
        normalized["needs_clarification"] = bool(normalized.get("needs_clarification"))
        questions = normalized.get("clarifying_questions")
        normalized["clarifying_questions"] = [str(item)[:500] for item in questions[:2]] if isinstance(questions, list) else []
        normalized.pop("_llm_unavailable", None)
        return normalized


def format_socratic_brief(review: dict) -> str:
    """Render only decision-relevant conclusions for downstream agents."""
    if not review:
        return ""
    lines = [
        f"Interpretasi pertanyaan: {review.get('interpreted_question') or '-'}",
        f"Tujuan pengguna: {review.get('user_goal') or '-'}",
        f"Risiko jika salah: {review.get('risk_if_wrong') or 'medium'}",
        f"Strategi jawaban: {review.get('answer_strategy') or '-'}",
    ]
    for label, key in (
        ("Asumsi yang harus ditandai", "assumptions"),
        ("Ambiguitas", "ambiguities"),
        ("Bukti tersedia", "available_evidence"),
        ("Data yang belum tersedia", "missing_information"),
        ("Perspektif alternatif", "alternative_perspectives"),
    ):
        values = review.get(key) or []
        if values:
            lines.append(f"{label}: " + "; ".join(str(item) for item in values))
    questions = review.get("clarifying_questions") or []
    if review.get("needs_clarification") and questions:
        lines.append("Pertanyaan klarifikasi bernilai tinggi: " + "; ".join(str(item) for item in questions[:2]))
    return "\n".join(lines)
