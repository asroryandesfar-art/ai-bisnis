"""Tests untuk HR Agent (AI Workforce Phase 3): hr_agent.py (persistence
helpers + CV extraction + HRAgent NLP) dan bn_platform/hr.py (router RBAC
gating + endpoint behavior).

Mengikuti pola FakePool + _route dari test_finance_agent.py -- tidak ada
panggilan Groq atau database sungguhan."""
import asyncio
import zipfile
import io
import xml.etree.ElementTree as ET

import pytest
from fastapi import HTTPException

import hr_agent as hr
from bn_platform.hr import build_hr_router, CandidateCreateRequest, EmployeeCreateRequest, RunTaskRequest


def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakePool:
    def __init__(self, fetchval_results=None, fetchrow_results=None, fetch_results=None):
        self.calls = []
        self._fetchval_results = list(fetchval_results or [])
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetch_results = list(fetch_results or [])

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._fetchval_results.pop(0) if self._fetchval_results else None

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


# ─── CV text extraction ─────────────────────────────────────────

def test_extract_cv_text_plain():
    assert hr.extract_cv_text(b"Halo, saya kandidat.", filename="cv.txt") == "Halo, saya kandidat."


def test_extract_cv_text_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        xml = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Pengalaman 5 tahun</w:t></w:r></w:p></w:body></w:document>'
        )
        z.writestr("word/document.xml", xml)
    text = hr.extract_cv_text(buf.getvalue(), filename="cv.docx")
    assert "Pengalaman 5 tahun" in text


def test_extract_cv_text_invalid_pdf_returns_empty():
    assert hr.extract_cv_text(b"not a real pdf", filename="cv.pdf") == ""


# ─── Persistence helpers ────────────────────────────────────────

def test_create_candidate_inserts():
    pool = FakePool(fetchrow_results=[{"id": "cand-1", "name": "Budi", "status": "new"}])
    candidate = asyncio.run(hr.create_candidate(
        pool, org_id="org-1", bot_id=None, name="Budi", email=None, phone=None,
        position_applied="Sales", cv_text=None, cv_filename=None, created_by="user-1",
    ))
    assert candidate["name"] == "Budi"
    assert any("INSERT INTO hr_candidates" in c[1] for c in pool.calls)


def test_update_candidate_status_rejects_invalid():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(hr.update_candidate_status(pool, org_id="org-1", candidate_id="cand-1", status="bogus"))


def test_save_candidate_score():
    pool = FakePool(fetchrow_results=[{"id": "cand-1", "score": 85, "status": "screened"}])
    result = asyncio.run(hr.save_candidate_score(
        pool, org_id="org-1", candidate_id="cand-1", score=85, breakdown={"skills_match": 90},
    ))
    assert result["score"] == 85
    assert any("UPDATE hr_candidates" in c[1] for c in pool.calls)


def test_create_employee_inserts():
    pool = FakePool(fetchrow_results=[{"id": "emp-1", "full_name": "Siti", "status": "active"}])
    employee = asyncio.run(hr.create_employee(
        pool, org_id="org-1", bot_id=None, full_name="Siti", email=None, position="CS",
        department="Operations", hire_date=None, created_by="user-1",
    ))
    assert employee["full_name"] == "Siti"


def test_create_evaluation_and_finalize():
    pool = FakePool(fetchrow_results=[
        {"id": "eval-1", "status": "draft", "score": 80},
        {"id": "eval-1", "status": "finalized", "score": 80},
    ])
    evaluation = asyncio.run(hr.create_evaluation(
        pool, org_id="org-1", employee_id="emp-1", period_start=None, period_end=None,
        score=80, strengths="Komunikasi baik", areas_to_improve="Manajemen waktu", evaluator_id="user-1",
    ))
    assert evaluation["status"] == "draft"
    finalized = asyncio.run(hr.finalize_evaluation(pool, org_id="org-1", evaluation_id="eval-1", finalized_by="user-1"))
    assert finalized["status"] == "finalized"


def test_employee_performance_trend():
    from datetime import datetime, timezone
    pool = FakePool(fetch_results=[[
        {"score": 70, "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc)},
        {"score": 85, "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc)},
    ]])
    result = asyncio.run(hr.employee_performance(pool, "org-1", "emp-1"))
    assert result["trend"] == "naik"
    assert result["average_score"] == 77.5
    assert result["latest_score"] == 85


def test_employee_performance_insufficient_data():
    pool = FakePool(fetch_results=[[]])
    result = asyncio.run(hr.employee_performance(pool, "org-1", "emp-1"))
    assert result["trend"] == "insufficient_data"
    assert result["average_score"] is None


def test_create_training_record_and_update_status():
    pool = FakePool(fetchrow_results=[
        {"id": "train-1", "status": "recommended"},
        {"id": "train-1", "status": "completed"},
    ])
    training = asyncio.run(hr.create_training_record(
        pool, org_id="org-1", employee_id="emp-1", training_name="Public Speaking",
        reason="Komunikasi", recommended_by="ai", created_by="user-1",
    ))
    assert training["status"] == "recommended"
    updated = asyncio.run(hr.update_training_status(pool, org_id="org-1", training_id="train-1", status="completed"))
    assert updated["status"] == "completed"


def test_update_training_status_rejects_invalid():
    pool = FakePool()
    with pytest.raises(ValueError):
        asyncio.run(hr.update_training_status(pool, org_id="org-1", training_id="train-1", status="bogus"))


def test_dashboard_summary_aggregates():
    pool = FakePool(
        fetch_results=[
            [{"status": "new", "cnt": 3}, {"status": "screened", "cnt": 2}],
            [{"status": "active", "cnt": 10}],
        ],
        fetchval_results=[78.5, 4],
    )
    summary = asyncio.run(hr.dashboard_summary(pool, "org-1"))
    assert summary["candidates_by_status"]["new"] == 3
    assert summary["employees_by_status"]["active"] == 10
    assert summary["avg_evaluation_score_90d"] == 78.5
    assert summary["pending_training_recommendations"] == 4


# ─── HRAgent (NLP) ──────────────────────────────────────────────

def test_hr_agent_requires_org_id_and_pool():
    agent = hr.HRAgent(api_key="test-key")
    result = asyncio.run(agent.run({"action": "score_candidate"}))
    assert result.success is False
    assert "org_id" in result.error


def test_hr_agent_rejects_unknown_action():
    agent = hr.HRAgent(api_key="test-key")
    pool = FakePool()
    result = asyncio.run(agent.run({"action": "bogus", "org_id": "org-1", "pool": pool}))
    assert result.success is False


def test_hr_agent_score_candidate(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return {"score": 88, "skills_match": 90, "experience_match": 85, "education_match": 80,
                "summary": "Kandidat kuat", "recommendation": "lanjut_interview"}

    monkeypatch.setattr(hr.HRAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool()
    agent = hr.HRAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "action": "score_candidate", "org_id": "org-1", "pool": pool,
        "cv_text": "5 tahun pengalaman sales", "position": "Sales Manager", "requirements": None,
    }))
    assert result.success is True
    assert result.output["result"]["score"] == 88


def test_hr_agent_fails_when_llm_unavailable(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        out = dict(default or {})
        out["_llm_unavailable"] = True
        return out

    monkeypatch.setattr(hr.HRAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool()
    agent = hr.HRAgent(api_key="test-key")
    result = asyncio.run(agent.run({
        "action": "generate_interview_questions", "org_id": "org-1", "pool": pool,
        "cv_text": "...", "position": "Sales",
    }))
    assert result.success is False


# ─── Router: RBAC gating ────────────────────────────────────────

def test_router_gates_every_route_with_hr_permission():
    requested_keys = []

    def recording_require_permission(key):
        requested_keys.append(key)
        async def _checker(user=None, pool=None):
            return user
        return _checker

    async def get_pool():
        return FakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    build_hr_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=recording_require_permission,
        get_agent_config=lambda: {"api_key": ""},
    )

    assert requested_keys.count("hr.read") == 8
    assert requested_keys.count("hr.write") == 14
    assert requested_keys.count("hr.approve") == 1
    assert set(requested_keys) == {"hr.read", "hr.write", "hr.approve"}


def _build_router(pool):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}

    def require_permission(_key):
        return get_current_user

    return build_hr_router(
        get_pool=get_pool, get_current_user=get_current_user,
        require_permission=require_permission, get_agent_config=lambda: {"api_key": ""},
    )


def test_run_task_route_delegates_to_task_engine_and_writes_audit_log(monkeypatch):
    captured = {}

    async def fake_run_agent_task(agent, goal, *, pool, org_id, bot_id=None, ctx=None):
        captured["goal"] = goal
        captured["org_id"] = org_id
        return {"status": "completed", "report": "ok"}

    import task_engine
    monkeypatch.setattr(task_engine, "run_agent_task", fake_run_agent_task)

    pool = FakePool()
    router = _build_router(pool)
    handler = _route(router, "/run-task", "POST")
    result = asyncio.run(handler(
        body=RunTaskRequest(goal="Screening kandidat baru untuk posisi Sales"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["status"] == "completed"
    assert captured["goal"] == "Screening kandidat baru untuk posisi Sales"
    assert captured["org_id"] == "org-1"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_create_candidate_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "cand-1", "name": "Budi", "status": "new"}])
    router = _build_router(pool)
    handler = _route(router, "/candidates", "POST")
    result = asyncio.run(handler(
        body=CandidateCreateRequest(name="Budi", position_applied="Sales"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["name"] == "Budi"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_create_employee_route_writes_audit_log():
    pool = FakePool(fetchrow_results=[{"id": "emp-1", "full_name": "Siti", "status": "active"}])
    router = _build_router(pool)
    handler = _route(router, "/employees", "POST")
    result = asyncio.run(handler(
        body=EmployeeCreateRequest(full_name="Siti", position="CS"),
        user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
    ))
    assert result["full_name"] == "Siti"
    assert any("INSERT INTO audit_logs" in c[1] for c in pool.calls)


def test_score_candidate_route_returns_404_when_not_found():
    pool = FakePool(fetchrow_results=[None])
    router = _build_router(pool)
    handler = _route(router, "/candidates/{candidate_id}/score", "POST")
    from bn_platform.hr import CandidateScoreRequest
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            candidate_id="cand-1", body=CandidateScoreRequest(position="Sales"),
            user={"org_id": "org-1", "id": "user-1", "email": "owner@example.com"}, pool=pool,
        ))
    assert exc.value.status_code == 404
