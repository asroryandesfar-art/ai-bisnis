"""Tests for chat orchestration helpers extracted in decomposition step 7:
_build_agent_meta (pure) and _enforce_output_language.
"""
import asyncio
import types

import main


def _result(**over):
    base = dict(
        confidence=0.9, topics=["a"], suggested_followup="f?", should_escalate=False,
        escalation_urgency="none", escalation_message=None, recommended_team=None,
        errors=[], reasoning_mode_used="standard", socratic_review={"risk_if_wrong": "low", "needs_clarification": False},
        devil_advocate_review={"severity": "low"}, devil_revision_applied=False,
        first_principle_analysis={"causal_links_count": 2, "root_hypotheses_count": 1},
        uncertainty_band="High Confidence", uncertainty_score=80.0, uncertainty_reasons=[],
        final_answer="ANS",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_build_agent_meta_maps_result_fields():
    meta = main._build_agent_meta(_result())
    assert meta["confidence"] == 0.9
    assert meta["socratic_risk"] == "low"
    assert meta["devil_advocate_severity"] == "low"
    assert meta["first_principle_causal_links"] == 2
    assert meta["uncertainty_band"] == "High Confidence"


def _enforce(answer, result, supervisor):
    return asyncio.run(main._enforce_output_language(
        answer=answer, result=result, effective_lang="id", system="SYS",
        intelligence_context={}, supervisor=supervisor, conv_id="c", message="m",
    ))


def test_language_ok_is_noop(monkeypatch):
    monkeypatch.setattr(main.language_middleware, "validate_output_language", lambda a, l: True)
    r = _result()
    called = {"n": 0}

    async def _proc(_c):
        called["n"] += 1
        return r

    ans, res = _enforce("ANS", r, types.SimpleNamespace(process=_proc))
    assert ans == "ANS" and res is r
    assert called["n"] == 0  # supervisor not re-run when language is fine


def test_language_mismatch_triggers_retry(monkeypatch):
    # First validation fails (retry), second passes (skip rewrite).
    seq = iter([False, True])
    monkeypatch.setattr(main.language_middleware, "validate_output_language", lambda a, l: next(seq))
    monkeypatch.setattr(main.language_middleware, "language_enforcement_suffix", lambda l: " [ID]")
    fixed = _result(final_answer="Jawaban benar")

    async def _proc(_c):
        return fixed

    ans, res = _enforce("wrong-lang", _result(), types.SimpleNamespace(process=_proc))
    assert ans == "Jawaban benar"
    assert res is fixed
