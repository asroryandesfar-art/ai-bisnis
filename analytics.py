"""
agents/analytics.py — Analytics Agent
Menganalisa percakapan dan menghasilkan insight untuk dashboard.
"""

from __future__ import annotations

from base import BaseAgent, AgentResult
from text_insights import (
    infer_topics,
    intent_from_text,
    sentiment_from_text,
    summarize_conversation,
)


class AnalyticsAgent(BaseAgent):
    name = "analytics_agent"
    system_prompt = """Kamu adalah Analytics Agent dalam sistem multi-agent BotNesia.

Tugasmu: Ekstrak insight bisnis dari percakapan pelanggan.
Catatan: output agent ini hanya untuk internal sistem (dashboard/metrics), tidak ditampilkan ke user."""

    async def run(self, context: dict) -> AgentResult:
        user_msg = context.get("user_message", "")
        history = context.get("messages", [])
        bot_response = context.get("bot_response", "")
        cs_confidence = float(context.get("cs_confidence", 1.0) or 0.0)
        resolved = bool(context.get("resolved", False))

        history_text = "\n".join(
            f"{(m.get('role') or '').upper()}: {m.get('content','')}"
            for m in history[-10:]
        )
        joined_text = "\n".join([history_text, user_msg, bot_response]).strip()

        sentiment = sentiment_from_text(joined_text)
        intent = intent_from_text(joined_text)
        topics = infer_topics(joined_text)

        friction_points: list[str] = []
        lt = joined_text.lower()
        if any(k in lt for k in ["error 500", "500", "server error"]):
            friction_points.append("Terjadi error server (500)")
        if any(
            k in lt
            for k in [
                "tidak bisa",
                "nggak bisa",
                "gak bisa",
                "ga bisa",
                "refused to connect",
                "cannot be reached",
            ]
        ):
            friction_points.append("Aplikasi tidak bisa diakses/terhubung")
        if any(k in lt for k in ["login", "masuk"]):
            friction_points.append("Kendala login")
        if any(k in lt for k in ["daftar", "register"]):
            friction_points.append("Kendala pendaftaran")

        product_insights: list[str] = []
        if any(k in lt for k in ["tracking", "lacak", "resi"]):
            product_insights.append("Pengguna membutuhkan pelacakan status yang lebih jelas")
        if any(k in lt for k in ["otp", "verifikasi", "email"]):
            product_insights.append("Perlu UX verifikasi akun yang lebih jelas")

        quality = max(0.0, min(1.0, cs_confidence))
        if sentiment.get("label") == "negative" and quality < 0.75:
            quality = max(0.0, quality - 0.15)

        output = {
            "sentiment": sentiment,
            "intent": intent,
            "topics": topics,
            "bot_quality_score": float(quality),
            "friction_points": friction_points[:6],
            "product_insights": product_insights[:6],
            "conversation_resolved": resolved,
            "resolution_turns": int(len(history)),
            "summary": summarize_conversation(user_msg, bot_response),
        }

        return AgentResult(
            agent=self.name,
            success=True,
            output=output,
            latency_ms=0,
        )
