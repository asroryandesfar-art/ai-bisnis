"""cognitive_loop — Planner→Worker→Critic loop untuk BotNesia (P1-A).

Loop reasoning iteratif: Critic boleh menyuruh Worker mengulang, Planner membuat
rencana baru; Supervisor (loop) memutuskan berhenti (diterima / budget / degraded).

    from cognitive_loop import CognitiveLoop
    out = await CognitiveLoop(max_iters=3, accept_threshold=0.8).run(agent, goal)

Dependency-injected (agent cukup punya `_call_llm_json`), fail-open, mandiri.
Konsumen mengadopsi di belakang feature flag `is_enabled("cognitive_loop")`.
Lihat docs/adr/ADR-0005-cognitive-loop.md.
"""
from cognitive_loop.loop import CognitiveLoop, ACCEPT, REVISE, REPLAN

__all__ = ["CognitiveLoop", "ACCEPT", "REVISE", "REPLAN"]
