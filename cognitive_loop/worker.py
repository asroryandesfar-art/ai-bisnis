"""cognitive_loop.worker — Worker berbasis TOOL untuk CognitiveLoop (P1-A.2).

`make_tool_worker` menghasilkan `worker_fn` yang memakai tool-loop agent
(`agent._call_llm_with_tools`) sehingga Worker bisa MENGEKSEKUSI (baca data nyata /
tool) — bukan hanya bernalar. Disuntikkan ke `CognitiveLoop.run(..., worker_fn=...)`.
Fail-open: kegagalan tool-loop → answer kosong + _deg True (loop menanganinya).
"""
from __future__ import annotations

from typing import Awaitable, Callable


def make_tool_worker(agent, *, tool_ctx: dict, tools: list) -> Callable[..., Awaitable[dict]]:
    """Return worker_fn(goal, plan, context, feedback, prior) → {answer, tool_calls, _deg}."""
    async def worker_fn(*, goal, plan, context, feedback=None, prior=None) -> dict:
        user = (f"Goal keseluruhan: {goal}\n\nSTRATEGI: {plan.get('strategy')}\n"
                f"LANGKAH: {plan.get('steps')}\n")
        if prior and feedback:
            user += f"\nJawaban sebelumnya:\n{prior}\n\nPERBAIKI sesuai kritik: {feedback}\n"
        try:
            res = await agent._call_llm_with_tools(
                [{"role": "system", "content": (
                    f"Kamu Worker ({getattr(agent, 'name', 'agent')}). Gunakan tools bila perlu data "
                    "nyata, lalu hasilkan jawaban terbaik untuk goal (kalimat biasa).")},
                 {"role": "user", "content": user}],
                tools=tools, tool_ctx=tool_ctx)
        except Exception:
            return {"answer": "", "tool_calls": [], "_deg": True}
        return {"answer": str(res.get("final_answer") or ""),
                "tool_calls": res.get("tool_calls") or [], "_deg": False}

    return worker_fn
