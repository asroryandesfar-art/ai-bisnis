"""
agents/escalation.py — Escalation Agent
Memutuskan kapan percakapan perlu diserahkan ke human agent.
"""

from __future__ import annotations

from base import BaseAgent, AgentResult


class EscalationAgent(BaseAgent):
    name = "escalation_agent"
    system_prompt = """Kamu adalah Escalation Agent dalam sistem multi-agent BotNesia.

Tugas: tentukan apakah percakapan perlu handoff ke human agent (dan tingkat urgensinya).
Catatan: output agent ini hanya untuk internal sistem (tidak ditampilkan ke user)."""

    SENSITIVE_KEYWORDS = [
        "marah",
        "bodoh",
        "brengsek",
        "penipuan",
        "tipu",
        "bohong",
        "lapor",
        "polisi",
        "hukum",
        "pengacara",
        "viral",
        "media",
        "darurat",
        "urgent",
        "harus sekarang",
        "minta manusia",
        "bicara orang",
        "tidak mau bot",
        "refund",
        "uang kembali",
        "kehilangan",
        "hilang",
        "rusak",
        "hancur",
        "error",
    ]

    async def run(self, context: dict) -> AgentResult:
        user_msg = context.get("user_message", "") or ""
        history = context.get("messages", []) or []
        cs_confidence = float(context.get("cs_confidence", 1.0) or 0.0)

        msg_l = user_msg.lower()

        negative_count = sum(
            1
            for m in history[-6:]
            if (m.get("role") == "user")
            and any(kw in (m.get("content", "") or "").lower() for kw in self.SENSITIVE_KEYWORDS)
        )

        low_confidence = cs_confidence < 0.5

        trigger_factors: list[str] = []
        should_escalate = False
        urgency = "low"
        recommended_team = "cs_general"
        reason = None

        def hit(keys: list[str]) -> bool:
            return any(k in msg_l for k in keys)

        # 1) Permintaan eksplisit
        if hit(["minta manusia", "bicara orang", "tidak mau bot", "admin", "cs manusia"]):
            should_escalate = True
            urgency = "medium"
            trigger_factors.append("request_human")
            reason = "User meminta bicara dengan manusia"

        # 2) Legal / publik
        if hit(["polisi", "hukum", "pengacara"]):
            should_escalate = True
            urgency = "high"
            recommended_team = "management"
            trigger_factors.append("legal_threat")
            reason = reason or "Ada indikasi ancaman legal"

        if hit(["viral", "media", "sosmed", "social media"]):
            should_escalate = True
            urgency = "high"
            recommended_team = "management"
            trigger_factors.append("public_threat")
            reason = reason or "User mengancam komplain publik"

        # 3) Urgensi
        if hit(["darurat", "urgent"]):
            trigger_factors.append("urgency")
            urgency = "critical" if should_escalate else "high"

        # 4) Refund / finansial
        if hit(["refund", "uang kembali", "pengembalian", "retur"]):
            trigger_factors.append("refund")
            if negative_count >= 2 or low_confidence:
                should_escalate = True
                urgency = "medium" if urgency == "low" else urgency
                recommended_team = "finance"
                reason = reason or "Permintaan refund dengan indikasi friksi tinggi"

        # 5) Kendala teknis
        if hit(["error", "eror", "bug", "500", "503", "timeout"]):
            trigger_factors.append("technical")
            if low_confidence or negative_count >= 2:
                should_escalate = True
                urgency = "medium" if urgency == "low" else urgency
                recommended_team = "technical"
                reason = reason or "Kendala teknis yang butuh bantuan tim teknis"

        # 6) Banyak negatif berulang
        if negative_count >= 3:
            should_escalate = True
            urgency = "high" if urgency in {"low", "medium"} else urgency
            if recommended_team == "cs_general":
                recommended_team = "senior_cs"
            trigger_factors.append("repeated_negative")
            reason = reason or "Banyak indikator negatif berturut-turut"

        suggested_message = None
        if should_escalate:
            suggested_message = (
                "Baik, saya bantu hubungkan ke tim kami agar ditangani lebih cepat. "
                "Mohon tunggu sebentar ya."
            )

        output = {
            "should_escalate": bool(should_escalate),
            "urgency": urgency,
            "reason": reason,
            "trigger_factors": trigger_factors[:8],
            "recommended_team": recommended_team,
            "suggested_message": suggested_message,
        }

        return AgentResult(
            agent=self.name,
            success=True,
            output=output,
            latency_ms=0,
        )
