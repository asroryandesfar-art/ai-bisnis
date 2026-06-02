"""
agents/trainer.py — Trainer Agent
Evaluasi kualitas jawaban bot dan beri saran perbaikan untuk training.
"""

from __future__ import annotations

from base import BaseAgent, AgentResult


class TrainerAgent(BaseAgent):
    name = "trainer_agent"
    system_prompt = """Kamu adalah Trainer Agent dalam sistem multi-agent BotNesia.

Mode heuristik: skor dan rekomendasi berbasis aturan internal.
"""

    async def run(self, context: dict) -> AgentResult:
        user_msg = (context.get("user_message", "") or "").strip()
        bot_response = (context.get("bot_response", "") or "").strip()
        cs_confidence = float(context.get("cs_confidence", 1.0) or 0.0)
        history = context.get("messages", []) or []

        if not bot_response:
            return AgentResult(
                agent=self.name,
                success=True,
                output={"skipped": True, "reason": "Tidak ada respons bot untuk dievaluasi"},
                latency_ms=0,
            )

        base_score = max(0.0, min(10.0, cs_confidence * 10.0))
        issues: list[str] = []

        # Penalti/bonus sederhana
        if len(bot_response) < 40:
            base_score = max(0.0, base_score - 1.0)
            issues.append("Jawaban terlalu singkat")
        if len(bot_response) > 900:
            base_score = max(0.0, base_score - 0.8)
            issues.append("Jawaban terlalu panjang")

        br_l = bot_response.lower()
        if any(k in br_l for k in ["saya tidak tahu", "gak tahu", "nggak tahu", "tidak bisa"]):
            base_score = max(0.0, base_score - 1.2)
            issues.append("Jawaban kurang membantu (terlalu banyak penolakan)")

        if any(k in br_l for k in ["hubungkan", "tim kami", "human", "cs"]):
            # biasanya relevan saat kasus sulit; tidak selalu buruk
            base_score = min(10.0, base_score + 0.3)

        # Skor sub-dimensi (heuristik)
        scores = {
            "accuracy": max(0.0, min(10.0, base_score)),
            "relevance": max(0.0, min(10.0, base_score)),
            "completeness": max(0.0, min(10.0, base_score - (0.5 if len(history) <= 2 else 0.0))),
            "tone": 9.0,
            "clarity": max(0.0, min(10.0, base_score)),
            "efficiency": max(0.0, min(10.0, 10.0 - (len(bot_response) / 200.0))),
        }

        overall_score = round(
            (scores["accuracy"]
             + scores["relevance"]
             + scores["completeness"]
             + scores["tone"]
             + scores["clarity"]
             + scores["efficiency"]) / 6.0,
            2,
        )

        improved_response = None
        training_examples: list[dict] = []
        prompt_suggestions: list[str] = []
        priority = "low"

        if overall_score < 7.0 or issues:
            priority = "medium" if overall_score < 7.0 else "low"
            improved_response = (
                "Saya bantu ya.\n\n"
                "Agar saya bisa cek dengan tepat, boleh kirim:\n"
                "- detail masalah yang terjadi\n"
                "- error code/screenshot (kalau ada)\n"
                "- email atau ID terkait (jika relevan)\n\n"
                "Setelah itu, saya akan arahkan langkah berikutnya."
            )
            if user_msg:
                training_examples.append({"input": user_msg, "ideal_output": improved_response})
            prompt_suggestions.append("Selalu minta detail (error code/ID) jika konteks kurang jelas.")

        output = {
            "overall_score": overall_score,
            "scores": scores,
            "issues": issues,
            "improved_response": improved_response,
            "training_examples": training_examples,
            "system_prompt_suggestions": prompt_suggestions,
            "priority": priority,
        }

        return AgentResult(agent=self.name, success=True, output=output, latency_ms=0)
