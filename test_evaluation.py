"""P1-D — Evaluation Framework (deterministik + LLM-judge stub + store)."""
import asyncio
import uuid

import asyncpg

import main
from evaluation import Evaluator, ensure_eval_schema


def _run_async(coro):
    return asyncio.run(coro)


def _run_db(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_eval_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "EvalTest", f"eval-{org[:8]}")
            try:
                await body(pool, org)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_deterministic_metrics():
    out = _run_async(Evaluator().evaluate(
        goal="g", answer="jawaban",
        tool_calls=[{"tool": "a"}, {"tool": "b", "error": "x"}], verified=True, confidence=0.9))
    s = out["scores"]
    assert s["tool_success"] == 0.5 and s["answered"] == 1.0
    assert s["verified"] == 1.0 and s["confidence"] == 0.9
    assert out["judged"] is False and 0.0 <= out["overall"] <= 1.0


def test_empty_answer_and_unverified_score_zero():
    out = _run_async(Evaluator().evaluate(goal="g", answer="  ", verified=False))
    assert out["scores"]["answered"] == 0.0 and out["scores"]["verified"] == 0.0


def test_llm_judge_stub_adds_dimensions():
    class Judge:
        async def _call_llm_json(self, messages, **kw):
            return {"accuracy": 0.9, "hallucination_free": 0.8,
                    "reasoning_quality": 0.7, "citation": 0.5}
    out = _run_async(Evaluator(judge_agent=Judge()).evaluate(
        goal="g", answer="a", verified=True, confidence=0.8))
    s = out["scores"]
    assert out["judged"] is True
    assert s["accuracy"] == 0.9 and s["hallucination"] == 0.8 and s["reasoning_quality"] == 0.7


def test_llm_judge_failopen():
    class Judge:
        async def _call_llm_json(self, messages, **kw):
            return {"_llm_unavailable": True}
    out = _run_async(Evaluator(judge_agent=Judge()).evaluate(goal="g", answer="a"))
    assert out["judged"] is False and "accuracy" not in out["scores"]   # deterministik saja


def test_store_persists_row():
    def body_wrap():
        async def body(pool, org):
            ev = Evaluator()
            res = await ev.evaluate_and_store(pool, org_id=org, goal="g", answer="a",
                                              verified=True, confidence=0.9, agent_name="x")
            assert res["id"] is not None
            row = await pool.fetchrow(
                "SELECT agent_name, overall, judged FROM task_evaluations WHERE id=$1",
                uuid.UUID(res["id"]))
            assert row["agent_name"] == "x" and row["overall"] is not None and row["judged"] is False
        return body
    _run_db(body_wrap())
