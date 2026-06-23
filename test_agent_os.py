"""
test_agent_os.py — Agent OS Layer: build_execution_report() harus membaca
ulang field SupervisorResult yang sudah ada (tanpa mengubah apapun) dan
menyusunnya jadi laporan 6-stage.
"""
from types import SimpleNamespace

import agent_os


def _fake_result(**overrides):
    base = dict(
        plan={"lenses": ["financial", "marketing"]},
        specialist_results={"financial": {"answer": "x"}},
        reasoning_mode_used="pro",
        reasoning_brief={"knowledge_routing": {"sources_considered": ["kb"], "needs_fresh_data": False}},
        verification_passed=True,
        verification_issues=[],
        confidence_score=82.5,
        retry_count=1,
        reflection_review={"flags": []},
        uncertainty_band="High Confidence",
        uncertainty_score=82.5,
        uncertainty_reasons=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_execution_report_has_all_six_stages():
    report = agent_os.build_execution_report(_fake_result())
    assert set(report.keys()) == {
        "planning", "tool_selection", "execution", "verification", "retry", "reporting",
    }


def test_build_execution_report_reads_planning_and_tool_selection():
    result = _fake_result()
    report = agent_os.build_execution_report(result)
    assert report["planning"]["data"] == result.plan
    assert report["tool_selection"]["data"] == result.reasoning_brief["knowledge_routing"]


def test_build_execution_report_reads_execution_and_verification():
    result = _fake_result()
    report = agent_os.build_execution_report(result)
    assert report["execution"]["data"]["reasoning_mode_used"] == "pro"
    assert report["execution"]["data"]["specialist_results"] == result.specialist_results
    assert report["verification"]["data"]["verification_passed"] is True
    assert report["verification"]["data"]["confidence_score"] == 82.5


def test_build_execution_report_reads_retry_and_reporting():
    result = _fake_result(retry_count=3, uncertainty_band="Low Confidence")
    report = agent_os.build_execution_report(result)
    assert report["retry"]["data"]["retry_count"] == 3
    assert report["reporting"]["data"]["uncertainty_band"] == "Low Confidence"
    assert report["reporting"]["data"]["reflection_review"] == result.reflection_review


def test_build_execution_report_does_not_mutate_result():
    result = _fake_result()
    snapshot = dict(vars(result))
    agent_os.build_execution_report(result)
    assert vars(result) == snapshot


def test_build_execution_report_handles_missing_fields_gracefully():
    minimal = SimpleNamespace()
    report = agent_os.build_execution_report(minimal)
    assert report["planning"]["data"] is None
    assert report["tool_selection"]["data"] is None
    assert report["retry"]["data"]["retry_count"] is None


def test_describe_stage_known_and_unknown():
    assert agent_os.describe_stage("planning")["implementation"]
    unknown = agent_os.describe_stage("does_not_exist")
    assert unknown["implementation"] == "-"
