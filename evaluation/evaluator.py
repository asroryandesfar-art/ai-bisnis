"""evaluation.evaluator — Evaluator (P1-D).

Skor kualitas otomatis pasca-task:
  • DETERMINISTIK (tanpa LLM): tool_success, answered, verified, confidence.
  • LLM-JUDGE (opsional, `judge_agent` diinjeksi, fail-open): accuracy,
    hallucination(inversi→lebih tinggi lebih baik), reasoning_quality, citation.
`overall` = rata-rata tertimbang dimensi yang tersedia (0..1). Disimpan ke
`task_evaluations`. Modul mandiri (tak impor main/bn_platform)."""
from __future__ import annotations

import json

import asyncpg

_JUDGE_DIMS = ("accuracy", "hallucination", "reasoning_quality", "citation")
# Bobot untuk overall (dimensi yang tak ada diabaikan & bobotnya dinormalisasi).
_WEIGHTS = {
    "accuracy": 0.30, "hallucination": 0.20, "reasoning_quality": 0.15,
    "citation": 0.05, "verified": 0.10, "tool_success": 0.10,
    "answered": 0.05, "confidence": 0.05,
}


def _weighted_overall(scores: dict) -> float | None:
    num = den = 0.0
    for k, w in _WEIGHTS.items():
        v = scores.get(k)
        if isinstance(v, (int, float)):
            num += w * float(v)
            den += w
    return round(num / den, 4) if den else None


class Evaluator:
    def __init__(self, *, judge_agent=None):
        """`judge_agent` = objek ber-`_call_llm_json` untuk LLM-judge (opsional)."""
        self._judge = judge_agent

    async def evaluate(self, *, goal: str, answer: str, tool_calls=None,
                       verified: bool | None = None, confidence: float | None = None) -> dict:
        scores: dict = {}
        tc = tool_calls or []
        if tc:
            ok = sum(1 for c in tc if not (isinstance(c, dict) and c.get("error")))
            scores["tool_success"] = round(ok / len(tc), 3)
        scores["answered"] = 1.0 if str(answer or "").strip() else 0.0
        if verified is not None:
            scores["verified"] = 1.0 if verified else 0.0
        if isinstance(confidence, (int, float)):
            scores["confidence"] = max(0.0, min(1.0, float(confidence)))

        judged = False
        if self._judge is not None:
            j = await self._judge_llm(goal, answer)
            if j:
                scores.update(j)
                judged = True

        return {"scores": scores, "overall": _weighted_overall(scores), "judged": judged}

    async def _judge_llm(self, goal: str, answer: str) -> dict | None:
        try:
            out = await self._judge._call_llm_json(
                [{"role": "system", "content": (
                    "Kamu evaluator kualitas. Nilai jawaban terhadap goal pada skala 0..1 untuk: "
                    "accuracy (benar/relevan), hallucination_free (1=tak ada klaim mengada-ada), "
                    "reasoning_quality, citation (dukungan sumber). Balas HANYA JSON.")},
                 {"role": "user", "content": (
                     f"GOAL:\n{goal}\n\nJAWABAN:\n{answer}\n\n"
                     'Jawab HANYA JSON: {"accuracy":0.0,"hallucination_free":0.0,'
                     '"reasoning_quality":0.0,"citation":0.0}')}],
                temperature=0.0, max_tokens=300,
                default={"_llm_unavailable": True})
        except Exception:
            return None
        if not out or out.get("_llm_unavailable"):
            return None

        def _s(k):
            try:
                return max(0.0, min(1.0, float(out.get(k))))
            except (TypeError, ValueError):
                return None
        res = {}
        for src, dst in (("accuracy", "accuracy"), ("hallucination_free", "hallucination"),
                         ("reasoning_quality", "reasoning_quality"), ("citation", "citation")):
            v = _s(src)
            if v is not None:
                res[dst] = v
        return res or None

    async def store(self, pool: asyncpg.Pool, *, org_id: str, evaluation: dict,
                    agent_name: str = "", goal: str = "",
                    execution_id: str | None = None, job_id: str | None = None) -> str | None:
        try:
            row = await pool.fetchrow(
                """INSERT INTO task_evaluations
                   (org_id, execution_id, job_id, agent_name, goal, scores, overall, judged)
                   VALUES ($1,$2::uuid,$3::uuid,$4,$5,$6::jsonb,$7,$8)
                   RETURNING id""",
                org_id, execution_id, job_id, agent_name, goal[:2000],
                json.dumps(evaluation.get("scores") or {}), evaluation.get("overall"),
                bool(evaluation.get("judged")))
            return str(row["id"])
        except Exception:
            return None

    async def evaluate_and_store(self, pool: asyncpg.Pool, *, org_id: str, goal: str, answer: str,
                                 tool_calls=None, verified=None, confidence=None,
                                 agent_name: str = "", execution_id=None, job_id=None) -> dict:
        ev = await self.evaluate(goal=goal, answer=answer, tool_calls=tool_calls,
                                 verified=verified, confidence=confidence)
        ev["id"] = await self.store(pool, org_id=org_id, evaluation=ev, agent_name=agent_name,
                                    goal=goal, execution_id=execution_id, job_id=job_id)
        return ev
