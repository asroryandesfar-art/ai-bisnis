"""Confidence banding and uncertainty handling for final answers."""
from __future__ import annotations

from base import AgentResult, BaseAgent

CONFIDENCE_BANDS = ("High Confidence", "Medium Confidence", "Low Confidence")

DEFAULT_UNCERTAINTY = {
    "band": "Medium Confidence",
    "score": 50,
    "reasons": [],
    "signals": [],
    "should_prefix": False,
    "message": "",
}


class UncertaintyEngine(BaseAgent):
    name = "uncertainty_engine"
    system_prompt = "Uncertainty engine internal. Deterministic confidence banding."

    async def run(self, context: dict) -> AgentResult:
        review = self.assess(context)
        return AgentResult(agent=self.name, success=True, output=review, latency_ms=0)

    @staticmethod
    def _normalize_score(value: object) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        score = float(value)
        if 0.0 <= score <= 1.5:
            return round(score * 100.0, 2)
        if score < 0:
            return 0.0
        if score > 100:
            return 100.0
        return round(score, 2)

    @staticmethod
    def _risk_rank(value: str | None) -> int:
        risk = str(value or "medium").strip().lower()
        return {"low": 1, "medium": 2, "high": 3}.get(risk, 2)

    @staticmethod
    def _pick_band(score: float, penalties: int) -> str:
        effective = max(0.0, min(100.0, score - penalties))
        if effective >= 80.0 and penalties < 20:
            return "High Confidence"
        if effective >= 55.0 and penalties < 40:
            return "Medium Confidence"
        return "Low Confidence"

    @staticmethod
    def _join_reason(parts: list[str]) -> str:
        parts = [part.strip() for part in parts if part and str(part).strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return "; ".join(parts[:3])

    def assess(self, context: dict) -> dict:
        base_score = self._normalize_score(
            context.get("uncertainty_score")
            if context.get("uncertainty_score") is not None
            else context.get("confidence_score")
        )
        if base_score is None:
            base_score = self._normalize_score(context.get("confidence"))
        if base_score is None:
            base_score = 50.0

        verification_passed = context.get("verification_passed")
        verification_issues = context.get("verification_issues") or []
        if not isinstance(verification_issues, list):
            verification_issues = []

        socratic_review = context.get("socratic_review") or {}
        devil_review = context.get("devil_advocate_review") or {}
        first_principle = context.get("first_principle_analysis") or {}
        meta_scores = context.get("meta_scores") or {}

        penalty = 0
        reasons: list[str] = []
        signals: list[str] = []

        if verification_passed is False:
            penalty += 30
            reasons.append("verifikasi belum lolos")
            signals.append("verification_failed")
        elif verification_passed is None:
            signals.append("verification_unknown")

        issue_count = len([item for item in verification_issues if str(item).strip()])
        if issue_count:
            penalty += min(20, issue_count * 6)
            reasons.append("masih ada isu verifikasi yang perlu diperbaiki")
            signals.append(f"verification_issues:{issue_count}")

        risk_label = str(socratic_review.get("risk_if_wrong") or "medium").lower()
        risk_rank = self._risk_rank(risk_label)
        if risk_rank >= 3:
            penalty += 15
            reasons.append("risiko salah dinilai tinggi")
            signals.append("socratic_risk_high")
        elif risk_rank == 2:
            signals.append("socratic_risk_medium")

        if socratic_review.get("needs_clarification"):
            penalty += 10
            reasons.append("data penting masih kurang")
            signals.append("needs_clarification")

        devil_severity = str(devil_review.get("severity") or "none").lower()
        if devil_severity == "high":
            penalty += 15
            reasons.append("kritik objektivitas masih berat")
            signals.append("devil_high")
        elif devil_severity == "medium":
            penalty += 8
            reasons.append("masih ada klaim yang perlu diturunkan tingkat kepastiannya")
            signals.append("devil_medium")

        if devil_review.get("overstatement_risk"):
            penalty += 10
            reasons.append("ada risiko overclaim")
            signals.append("overstatement_risk")

        missing_information = socratic_review.get("missing_information") or []
        if isinstance(missing_information, list):
            missing_count = len([item for item in missing_information if str(item).strip()])
            if missing_count >= 2:
                penalty += 6
                signals.append(f"missing_information:{missing_count}")
            if missing_count >= 4:
                penalty += 4
        else:
            missing_count = 0

        root_hypotheses = int(first_principle.get("root_hypotheses_count", 0) or 0)
        if root_hypotheses >= 3:
            penalty += 5
            signals.append(f"root_hypotheses:{root_hypotheses}")
        causal_links = int(first_principle.get("causal_links_count", 0) or 0)
        if causal_links == 0 and root_hypotheses:
            penalty += 4
            reasons.append("hubungan sebab-akibat belum kuat")
            signals.append("weak_causal_links")

        retry_count = int(context.get("retry_count", 0) or 0)
        if retry_count:
            penalty += min(10, retry_count * 4)
            signals.append(f"retry_count:{retry_count}")

        if bool(meta_scores.get("needs_rewrite")):
            penalty += 10
            reasons.append("jawaban meta perlu diturunkan kepastiannya")
            signals.append("meta_rewrite")

        band = self._pick_band(base_score, penalty)
        effective_score = max(0.0, min(100.0, round(base_score - penalty, 2)))

        if band == "High Confidence":
            reasons = [reason for reason in reasons if "verifikasi" not in reason]
        elif band == "Medium Confidence" and not reasons:
            reasons.append("data cukup untuk jawaban awal, tetapi masih ada batasan")

        should_prefix = band == "Low Confidence"
        message = str(context.get("final_answer") or context.get("bot_response") or "").strip()
        if should_prefix:
            rationale = self._join_reason(reasons) or "informasi yang tersedia masih belum cukup kuat"
            if message:
                message = (
                    "Saya belum cukup yakin.\n\n"
                    f"Alasannya: {rationale}.\n\n"
                    f"Berdasarkan data yang ada, ini jawaban terbaik sementara: {message}"
                )
            else:
                message = f"Saya belum cukup yakin. Alasannya: {rationale}."

        review = dict(DEFAULT_UNCERTAINTY)
        review.update(
            {
                "band": band if band in CONFIDENCE_BANDS else "Medium Confidence",
                "score": effective_score,
                "reasons": reasons[:5],
                "signals": signals[:10],
                "should_prefix": should_prefix,
                "message": message,
            }
        )
        return review
