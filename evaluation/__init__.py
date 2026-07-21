"""evaluation — Evaluation Framework untuk BotNesia (P1-D).

Skor otomatis pasca-task (deterministik + LLM-judge opsional) → tabel
`task_evaluations`. Melengkapi Critic loop (P1-A) & observability.

    from evaluation import Evaluator
    ev = Evaluator(judge_agent=agent)   # judge opsional
    await ev.evaluate_and_store(pool, org_id=org, goal=g, answer=a, verified=True, confidence=0.9)

Additive, konsumen gate `is_enabled("evaluation")`. Lihat ADR-0007.
"""
from evaluation.schema import ensure_eval_schema, EVAL_SCHEMA_SQL
from evaluation.evaluator import Evaluator

__all__ = ["ensure_eval_schema", "EVAL_SCHEMA_SQL", "Evaluator"]
