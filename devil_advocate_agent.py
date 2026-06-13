"""Adversarial answer review that reduces bias without exposing internal debate."""
from __future__ import annotations

from base import AgentResult, BaseAgent

SEVERITIES = {"none", "low", "medium", "high"}

DEFAULT_CRITIQUE = {
    "needs_revision": False,
    "severity": "none",
    "unsupported_claims": [],
    "missing_evidence": [],
    "ignored_weaknesses": [],
    "counterarguments": [],
    "competitor_advantages": [],
    "overstatement_risk": False,
    "challenge_questions": [],
    "revision_instructions": [],
}

DEVIL_ADVOCATE_SYSTEM_PROMPT = """Kamu adalah DevilAdvocateAgent internal untuk quality control jawaban AI.
Tugasmu menentang draft jawaban secara objektif, bukan menjadi negatif tanpa dasar. Uji:
- berdasarkan bukti apa setiap klaim dibuat;
- apakah ada klaim absolut, bias marketing, atau keunggulan produk yang tidak terbukti;
- kelemahan, trade-off, dan kondisi ketika rekomendasi gagal;
- counterargument atau interpretasi alternatif yang masuk akal;
- kemungkinan kompetitor atau opsi lain lebih unggul dalam kondisi tertentu.

Kamu BUKAN penulis jawaban final. Hasilkan kritik terstruktur, ringkas, dan actionable.
Jangan membuat fakta baru tentang kompetitor. Jika tidak ada masalah material, needs_revision=false.
Jangan menulis chain-of-thought atau dialog debat. Balas HANYA dalam format JSON."""


class DevilAdvocateAgent(BaseAgent):
    name = "devil_advocate_agent"
    system_prompt = DEVIL_ADVOCATE_SYSTEM_PROMPT

    async def run(self, context: dict) -> AgentResult:
        user_message = str(context.get("user_message") or "").strip()
        answer = str(context.get("bot_response") or "").strip()
        knowledge = str(context.get("knowledge_base_context") or "").strip()
        specialist_results = context.get("specialist_results") or {}
        specialist_evidence = "\n".join(
            f"- {name}: {str((output or {}).get('conclusion') or '')[:700]}"
            for name, output in specialist_results.items()
            if isinstance(output, dict) and output.get("conclusion")
        ) or "(tidak ada kesimpulan spesialis)"
        prompt = f"""Pertanyaan pengguna:\n{user_message}\n\nDraft jawaban:\n{answer}\n\nKnowledge/data tersedia:\n{knowledge[:5000] or '(tidak ada data tambahan)'}\n\nKesimpulan spesialis:\n{specialist_evidence}\n\nEvaluasi dalam JSON:
{{
  "needs_revision": true|false,
  "severity": "none|low|medium|high",
  "unsupported_claims": ["klaim yang tidak ditopang data"],
  "missing_evidence": ["bukti yang seharusnya ada"],
  "ignored_weaknesses": ["kelemahan atau trade-off yang diabaikan"],
  "counterarguments": ["sudut pandang penentang yang masuk akal"],
  "competitor_advantages": ["kondisi hipotetis ketika alternatif/kompetitor mungkin lebih unggul; jangan mengarang fakta"],
  "overstatement_risk": true|false,
  "challenge_questions": ["pertanyaan seperti: berdasarkan apa?, apa buktinya?, kapan ini tidak berlaku?"],
  "revision_instructions": ["instruksi konkret untuk membuat jawaban lebih objektif"]
}}

needs_revision=true hanya untuk masalah yang dapat menyesatkan, terlalu absolut, tidak didukung,
atau mengabaikan trade-off penting. Kritik gaya kecil tidak perlu memicu revisi."""
        critique = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=700,
            default=dict(DEFAULT_CRITIQUE),
        )
        critique = self._normalize(critique)
        return AgentResult(agent=self.name, success=True, output=critique, latency_ms=0)

    @staticmethod
    def _normalize(critique: dict) -> dict:
        normalized = dict(DEFAULT_CRITIQUE)
        normalized.update(critique or {})
        normalized["needs_revision"] = bool(normalized.get("needs_revision"))
        severity = str(normalized.get("severity") or "none").lower()
        normalized["severity"] = severity if severity in SEVERITIES else "medium"
        for key in (
            "unsupported_claims", "missing_evidence", "ignored_weaknesses",
            "counterarguments", "competitor_advantages", "challenge_questions",
            "revision_instructions",
        ):
            value = normalized.get(key)
            normalized[key] = [str(item)[:500] for item in value[:8]] if isinstance(value, list) else []
        normalized["overstatement_risk"] = bool(normalized.get("overstatement_risk"))
        normalized.pop("_llm_unavailable", None)
        if normalized["severity"] == "none":
            normalized["needs_revision"] = False
        return normalized


def format_devil_critique(critique: dict) -> str:
    """Render actionable conclusions only, not hidden deliberation."""
    if not critique:
        return ""
    lines = [
        f"Severity: {critique.get('severity') or 'none'}",
        f"Risiko overstatement: {'ya' if critique.get('overstatement_risk') else 'tidak'}",
    ]
    for label, key in (
        ("Klaim tanpa dukungan", "unsupported_claims"),
        ("Bukti yang kurang", "missing_evidence"),
        ("Kelemahan/trade-off terabaikan", "ignored_weaknesses"),
        ("Counterargument", "counterarguments"),
        ("Kondisi alternatif lebih unggul", "competitor_advantages"),
        ("Instruksi revisi", "revision_instructions"),
    ):
        values = critique.get(key) or []
        if values:
            lines.append(f"{label}: " + "; ".join(str(item) for item in values))
    return "\n".join(lines)
