"""cognitive_loop.loop — Planner→Worker→Critic loop (P1-A).

Mengubah eksekusi satu-lintasan menjadi loop iteratif:

    Planner → Worker → Critic → (accept | revise | replan) → ... → Done

- **Planner** menyusun strategi+langkah.
- **Worker** mengeksekusi → jawaban.
- **Critic** menilai (0..1) & memutuskan aksi: accept / revise (Worker ulang dgn
  feedback) / replan (Planner rencana baru).
- **Supervisor** (loop ini) memutuskan berhenti: diterima (score≥threshold),
  budget habis (max_iters / deadline), atau degraded (LLM down → best-effort).

Dependency-injected: `agent` cukup punya `_call_llm_json` (fail-open) → testable
tanpa API. `worker_fn` opsional (mis. tool-loop task_engine) menggantikan Worker
LLM default. Modul MANDIRI (tak impor main/bn_platform).
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable

ACCEPT, REVISE, REPLAN = "accept", "revise", "replan"


class CognitiveLoop:
    def __init__(self, *, max_iters: int = 3, accept_threshold: float = 0.8,
                 deadline_s: float | None = None):
        self.max_iters = max(1, int(max_iters))
        self.accept_threshold = float(accept_threshold)
        self.deadline_s = deadline_s

    async def run(self, agent, goal: str, *, context: dict | None = None,
                  worker_fn: Callable[..., Awaitable[dict]] | None = None) -> dict:
        """Jalankan loop untuk `goal`. Return artefak terstruktur (lihat akhir)."""
        context = context or {}
        started = time.monotonic()
        history: list[dict] = []
        degraded = False

        def over_deadline() -> bool:
            return self.deadline_s is not None and (time.monotonic() - started) >= self.deadline_s

        plan = await self._plan(agent, goal, context)
        degraded |= plan.pop("_deg", False)
        answer, wdeg = await self._work(agent, goal, plan, context, worker_fn)
        degraded |= wdeg

        accepted = False
        final_score = 0.0
        stop_reason = "max_iters"
        for i in range(self.max_iters):
            crit = await self._critique(agent, goal, answer, plan)
            final_score = crit["score"]
            history.append({"iteration": i, "plan": plan, "answer": answer, "critique": crit})
            if crit.pop("_deg", False):
                degraded = True
                accepted = True                       # tak bisa menilai → terima best-effort
                stop_reason = "degraded"
                break
            if crit["accept"] or crit["score"] >= self.accept_threshold:
                accepted = True
                stop_reason = "accepted"
                break
            if i == self.max_iters - 1:
                stop_reason = "max_iters"
                break
            if over_deadline():
                stop_reason = "deadline"
                break
            if crit["action"] == REPLAN:
                plan = await self._plan(agent, goal, context, prior=crit)
                degraded |= plan.pop("_deg", False)
                answer, wdeg = await self._work(agent, goal, plan, context, worker_fn)
            else:                                     # revise
                answer, wdeg = await self._work(agent, goal, plan, context, worker_fn,
                                                feedback=crit["issues"], prior=answer)
            degraded |= wdeg

        return {
            "goal": goal,
            "answer": answer,
            "accepted": accepted,
            "final_score": round(final_score, 3),
            "iterations": len(history),
            "stop_reason": stop_reason,
            "history": history,
            "_degraded": degraded,
        }

    # ── Planner ─────────────────────────────────────────────────────────────
    async def _plan(self, agent, goal, context, prior: dict | None = None) -> dict:
        kb = str(context.get("knowledge_base_context") or "")[:2000]
        user = f"GOAL:\n{goal}\n" + (f"\nKONTEKS:\n{kb}\n" if kb else "")
        if prior:
            user += f"\nKRITIK sebelumnya (buat rencana BARU yang mengatasinya): {prior.get('issues')}\n"
        user += '\nJawab HANYA JSON: {"strategy":"<ringkas>","steps":["..."]}'
        out = await agent._call_llm_json(
            [{"role": "system", "content": "Kamu Planner. Susun strategi + langkah konkret untuk mencapai goal. Balas HANYA JSON."},
             {"role": "user", "content": user}],
            temperature=0.2, max_tokens=600,
            default={"strategy": "", "steps": [goal], "_llm_unavailable": True})
        steps = out.get("steps")
        if not isinstance(steps, list) or not steps:
            steps = [goal]
        return {"strategy": str(out.get("strategy") or ""), "steps": steps,
                "_deg": bool(out.get("_llm_unavailable"))}

    # ── Worker ──────────────────────────────────────────────────────────────
    async def _work(self, agent, goal, plan, context, worker_fn, *,
                    feedback=None, prior=None) -> tuple[str, bool]:
        if worker_fn is not None:
            res = await worker_fn(goal=goal, plan=plan, context=context, feedback=feedback, prior=prior)
            return str(res.get("answer") or ""), bool(res.get("_deg"))
        user = (f"GOAL:\n{goal}\n\nSTRATEGI:\n{plan.get('strategy')}\n"
                f"LANGKAH: {plan.get('steps')}\n")
        if prior and feedback:
            user += f"\nJAWABAN SEBELUMNYA:\n{prior}\n\nPERBAIKI sesuai kritik: {feedback}\n"
        user += '\nJawab HANYA JSON: {"answer":"<jawaban lengkap & final>"}'
        out = await agent._call_llm_json(
            [{"role": "system", "content": "Kamu Worker. Eksekusi rencana & hasilkan jawaban terbaik untuk goal. Balas HANYA JSON."},
             {"role": "user", "content": user}],
            temperature=0.3, max_tokens=1500,
            default={"answer": "", "_llm_unavailable": True})
        return str(out.get("answer") or ""), bool(out.get("_llm_unavailable"))

    # ── Critic ──────────────────────────────────────────────────────────────
    async def _critique(self, agent, goal, answer, plan) -> dict:
        out = await agent._call_llm_json(
            [{"role": "system", "content": (
                "Kamu Critic. Nilai jawaban terhadap goal secara JUJUR & KETAT pada skala 0..1. "
                "Tentukan aksi: accept (cukup baik), revise (Worker perbaiki), atau replan "
                "(Planner butuh strategi baru). Balas HANYA JSON.")},
             {"role": "user", "content": (
                 f"GOAL:\n{goal}\n\nJAWABAN:\n{answer}\n\n"
                 'Jawab HANYA JSON: {"score":0.0,"accept":false,'
                 '"action":"accept|revise|replan","issues":["..."]}')}],
            temperature=0.0, max_tokens=500,
            default={"score": 1.0, "accept": True, "action": ACCEPT, "issues": [], "_llm_unavailable": True})
        try:
            score = max(0.0, min(1.0, float(out.get("score"))))
        except (TypeError, ValueError):
            score = 0.0
        action = out.get("action")
        if action not in (ACCEPT, REVISE, REPLAN):
            action = REVISE
        issues = out.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {"score": score, "accept": bool(out.get("accept")), "action": action,
                "issues": issues, "_deg": bool(out.get("_llm_unavailable"))}
