"""First-principles decomposition for root-cause-oriented answers."""
from __future__ import annotations

from base import AgentResult, BaseAgent

DEFAULT_ANALYSIS = {
    "problem_statement": "",
    "fundamental_facts": [],
    "assumptions": [],
    "unknowns": [],
    "root_variables": [],
    "causal_links": [],
    "root_hypotheses": [],
    "disconfirming_tests": [],
    "priority_investigation": [],
}

FIRST_PRINCIPLE_SYSTEM_PROMPT = """Kamu adalah FirstPrincipleAgent internal.
Tugasmu memecah masalah sampai ke komponen dasar sebelum agent lain menjawab.
Jangan mengulang opini umum atau solusi populer. Bedakan dengan tegas:
- fakta yang benar-benar tersedia;
- asumsi yang belum terbukti;
- variabel dasar yang menentukan hasil;
- hubungan sebab-akibat yang masuk akal;
- hipotesis akar masalah dan cara membuktikan atau membantahnya.

Untuk masalah bisnis, periksa minimal bila relevan: nilai/kualitas produk, demand, target pasar,
harga, distribusi/lokasi, awareness/marketing, conversion, retention, kapasitas operasional,
dan faktor eksternal. Jangan menganggap salah satunya penyebab tanpa bukti.
Kamu BUKAN penulis jawaban final. Jangan menulis chain-of-thought atau fakta baru.
Balas HANYA dalam format JSON."""


class FirstPrincipleAgent(BaseAgent):
    name = "first_principle_agent"
    system_prompt = FIRST_PRINCIPLE_SYSTEM_PROMPT

    async def run(self, context: dict) -> AgentResult:
        user_message = str(context.get("user_message") or "").strip()
        knowledge = str(context.get("knowledge_base_context") or "").strip()
        history = context.get("messages") or []
        history_text = "\n".join(
            f"{str(item.get('role') or 'user').upper()}: {str(item.get('content') or '')[:500]}"
            for item in history[-6:]
        ) or "(tidak ada riwayat)"
        prompt = f"""Masalah/pertanyaan pengguna:\n{user_message}\n\nRiwayat relevan:\n{history_text}\n\nData yang tersedia:\n{knowledge[:6000] or '(tidak ada data tambahan)'}\n\nUraikan dalam JSON:
{{
  "problem_statement": "definisi masalah tanpa asumsi solusi",
  "fundamental_facts": ["fakta dasar yang didukung konteks"],
  "assumptions": ["hal yang sering dianggap benar tetapi belum terbukti"],
  "unknowns": ["data penting yang belum diketahui"],
  "root_variables": ["variabel dasar yang dapat menentukan hasil"],
  "causal_links": [{{"cause": "variabel penyebab", "effect": "dampak", "confidence": "low|medium|high", "evidence": "bukti atau belum ada"}}],
  "root_hypotheses": [{{"hypothesis": "kemungkinan akar masalah", "why_plausible": "alasan berbasis fakta", "evidence_needed": "data untuk menguji"}}],
  "disconfirming_tests": ["tes yang dapat membuktikan hipotesis salah"],
  "priority_investigation": ["urutan pemeriksaan paling bernilai"]
}}

Jangan menyimpulkan satu akar masalah bila data belum cukup. Prioritaskan diagnosis sebelum resep."""
        analysis = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=900,
            default={**DEFAULT_ANALYSIS, "problem_statement": user_message},
        )
        normalized = self._normalize(analysis, user_message)
        return AgentResult(agent=self.name, success=True, output=normalized, latency_ms=0)

    @staticmethod
    def _normalize(analysis: dict, user_message: str) -> dict:
        result = dict(DEFAULT_ANALYSIS)
        result.update(analysis or {})
        result["problem_statement"] = str(result.get("problem_statement") or user_message)[:1200]
        for key in (
            "fundamental_facts", "assumptions", "unknowns", "root_variables",
            "disconfirming_tests", "priority_investigation",
        ):
            values = result.get(key)
            result[key] = [str(item)[:600] for item in values[:10]] if isinstance(values, list) else []
        causal_links = []
        for item in result.get("causal_links") or []:
            if not isinstance(item, dict):
                continue
            confidence = str(item.get("confidence") or "low").lower()
            causal_links.append({
                "cause": str(item.get("cause") or "")[:500],
                "effect": str(item.get("effect") or "")[:500],
                "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
                "evidence": str(item.get("evidence") or "belum ada")[:500],
            })
        result["causal_links"] = causal_links[:10]
        hypotheses = []
        for item in result.get("root_hypotheses") or []:
            if not isinstance(item, dict):
                continue
            hypotheses.append({
                "hypothesis": str(item.get("hypothesis") or "")[:600],
                "why_plausible": str(item.get("why_plausible") or "")[:600],
                "evidence_needed": str(item.get("evidence_needed") or "")[:600],
            })
        result["root_hypotheses"] = hypotheses[:8]
        result["causal_links_count"] = len(result["causal_links"])
        result["root_hypotheses_count"] = len(result["root_hypotheses"])
        result.pop("_llm_unavailable", None)
        return result


def format_first_principle_brief(analysis: dict) -> str:
    """Render decision-relevant decomposition, not private free-form reasoning."""
    if not analysis:
        return ""
    lines = [f"Definisi masalah: {analysis.get('problem_statement') or '-'}"]
    for label, key in (
        ("Fakta dasar", "fundamental_facts"),
        ("Asumsi belum terbukti", "assumptions"),
        ("Data belum diketahui", "unknowns"),
        ("Variabel akar", "root_variables"),
        ("Tes pembantah", "disconfirming_tests"),
        ("Prioritas investigasi", "priority_investigation"),
    ):
        values = analysis.get(key) or []
        if values:
            lines.append(f"{label}: " + "; ".join(str(item) for item in values))
    links = analysis.get("causal_links") or []
    if links:
        lines.append("Hubungan sebab-akibat: " + "; ".join(
            f"{item.get('cause')} -> {item.get('effect')} ({item.get('confidence')}, bukti: {item.get('evidence')})"
            for item in links
        ))
    hypotheses = analysis.get("root_hypotheses") or []
    if hypotheses:
        lines.append("Hipotesis akar: " + "; ".join(
            f"{item.get('hypothesis')} [uji dengan: {item.get('evidence_needed')}]"
            for item in hypotheses
        ))
    return "\n".join(lines)
