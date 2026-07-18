"""bn_platform/hr.py — HR Center router (AI Workforce Phase 3).

CV screening, candidate scoring, interview question generator, employee
evaluation (draft + finalisasi manusia), training recommendation, dan
performance tracking. Data sensitif (PII kandidat/karyawan) -- semua
endpoint org-scoped, RBAC-gated (hr.read/hr.write/hr.approve), audit-logged.
Mengikuti pola persis bn_platform/finance.py."""
from datetime import datetime
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

import hr_agent as hr
from .security import _check_rate_limit, write_audit_log
from .agent_toggles import require_agent_enabled

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]

MAX_CV_BYTES = 5 * 1024 * 1024


class CandidateCreateRequest(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    position_applied: str | None = None
    bot_id: str | None = None


class CandidateCVUploadResponse(BaseModel):
    id: str
    cv_filename: str | None
    cv_text_length: int


class CandidateStatusRequest(BaseModel):
    status: str


class CandidateScoreRequest(BaseModel):
    position: str
    requirements: str | None = None


class EmployeeCreateRequest(BaseModel):
    full_name: str
    email: str | None = None
    position: str | None = None
    department: str | None = None
    hire_date: datetime | None = None
    bot_id: str | None = None


class EmployeeStatusRequest(BaseModel):
    status: str


class EvaluationGenerateRequest(BaseModel):
    role: str
    notes: str
    period_start: datetime | None = None
    period_end: datetime | None = None


class TrainingRecommendRequest(BaseModel):
    role: str
    areas_to_improve: str


class TrainingCreateRequest(BaseModel):
    training_name: str
    reason: str | None = None


class RunTaskRequest(BaseModel):
    goal: str
    bot_id: str | None = None


class TrainingStatusRequest(BaseModel):
    status: str


def build_hr_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                     require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/hr", tags=["hr"])
    cfg = get_agent_config()
    agent = hr.HRAgent(api_key=cfg.get("api_key"), model=cfg.get("model"),
                        base_url=cfg.get("base_url"), deepseek_api_key=cfg.get("deepseek_api_key", ""), openrouter_api_key=cfg.get("openrouter_api_key", ""), app_url=cfg.get("app_url", "https://botnesia.id"))

    async def _get_employee(pool: asyncpg.Pool, employee_id: str, org_id: str) -> dict:
        row = await pool.fetchrow("SELECT * FROM hr_employees WHERE id=$1 AND org_id=$2", employee_id, org_id)
        if not row:
            raise HTTPException(404, "Karyawan tidak ditemukan")
        return dict(row)

    # ── Dashboard ───────────────────────────────────────────────

    @router.get("/dashboard")
    async def dashboard(
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await hr.dashboard_summary(pool, user["org_id"])

    # ── Candidates ───────────────────────────────────────────────

    @router.get("/candidates")
    async def list_candidates(
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        if status:
            rows = await pool.fetch(
                "SELECT * FROM hr_candidates WHERE org_id=$1 AND status=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, status, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM hr_candidates WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2", org_id, limit,
            )
        return {"candidates": [dict(r) for r in rows]}

    @router.post("/candidates", status_code=201)
    async def create_candidate_route(
        body: CandidateCreateRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        candidate = await hr.create_candidate(
            pool, org_id=org_id, bot_id=body.bot_id, name=body.name, email=body.email, phone=body.phone,
            position_applied=body.position_applied, cv_text=None, cv_filename=None,
            created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="hr_candidate", resource_id=candidate["id"],
            metadata={"name": body.name, "position_applied": body.position_applied},
        )
        return candidate

    @router.post("/candidates/{candidate_id}/cv", response_model=CandidateCVUploadResponse)
    async def upload_candidate_cv_route(
        candidate_id: str,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        cv_file: UploadFile = File(...),
    ):
        org_id = user["org_id"]
        candidate = await pool.fetchrow(
            "SELECT id FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, org_id,
        )
        if not candidate:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        raw = await cv_file.read()
        if len(raw) > MAX_CV_BYTES:
            raise HTTPException(413, "File CV terlalu besar (maks 5MB)")
        cv_text = hr.extract_cv_text(raw, filename=cv_file.filename or "", mime=cv_file.content_type or "")
        await pool.execute(
            "UPDATE hr_candidates SET cv_text=$1, cv_filename=$2, updated_at=NOW() WHERE id=$3 AND org_id=$4",
            cv_text, cv_file.filename, candidate_id, org_id,
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_candidate", resource_id=candidate_id,
            metadata={"cv_filename": cv_file.filename, "cv_text_length": len(cv_text)},
        )
        return {"id": candidate_id, "cv_filename": cv_file.filename, "cv_text_length": len(cv_text)}

    @router.get("/candidates/{candidate_id}")
    async def get_candidate(
        candidate_id: str,
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        row = await pool.fetchrow(
            "SELECT * FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, user["org_id"],
        )
        if not row:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        return dict(row)

    @router.patch("/candidates/{candidate_id}/status")
    async def update_candidate_status_route(
        candidate_id: str,
        body: CandidateStatusRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await hr.update_candidate_status(pool, org_id=org_id, candidate_id=candidate_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_candidate", resource_id=candidate_id,
            metadata={"status": body.status},
        )
        return row

    @router.post("/candidates/{candidate_id}/score")
    async def score_candidate_route(
        candidate_id: str,
        body: CandidateScoreRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        candidate = await pool.fetchrow(
            "SELECT * FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, org_id,
        )
        if not candidate:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        result = await agent.safe_run({
            "action": "score_candidate", "org_id": org_id, "pool": pool,
            "cv_text": candidate["cv_text"] or "", "position": body.position, "requirements": body.requirements,
        })
        if not result.success:
            raise HTTPException(422, result.error or "Gagal scoring kandidat")
        score_data = result.output["result"]
        score = score_data.get("score")
        if score is None:
            raise HTTPException(422, "AI tidak menghasilkan skor yang valid")
        updated = await hr.save_candidate_score(pool, org_id=org_id, candidate_id=candidate_id,
                                                  score=int(score), breakdown=score_data)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_candidate", resource_id=candidate_id,
            metadata={"score": score, "ai_generated": True},
        )
        return updated

    @router.post("/candidates/{candidate_id}/interview-questions")
    async def generate_interview_questions_route(
        candidate_id: str,
        body: CandidateScoreRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        candidate = await pool.fetchrow(
            "SELECT * FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, org_id,
        )
        if not candidate:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        result = await agent.safe_run({
            "action": "generate_interview_questions", "org_id": org_id, "pool": pool,
            "cv_text": candidate["cv_text"] or "", "position": body.position,
        })
        if not result.success:
            raise HTTPException(422, result.error or "Gagal generate pertanyaan interview")
        return result.output["result"]

    @router.delete("/candidates/{candidate_id}")
    async def delete_candidate(
        candidate_id: str,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await pool.fetchrow("SELECT id FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, org_id)
        if not row:
            raise HTTPException(404, "Kandidat tidak ditemukan")
        await pool.execute("DELETE FROM hr_candidates WHERE id=$1 AND org_id=$2", candidate_id, org_id)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="delete", resource_type="hr_candidate", resource_id=candidate_id, metadata={},
        )
        return {"deleted": True}

    # ── Employees ────────────────────────────────────────────────

    @router.get("/employees")
    async def list_employees(
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
        limit: int = 50,
    ):
        org_id = user["org_id"]
        limit = max(1, min(limit, 200))
        if status:
            rows = await pool.fetch(
                "SELECT * FROM hr_employees WHERE org_id=$1 AND status=$2 ORDER BY created_at DESC LIMIT $3",
                org_id, status, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM hr_employees WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2", org_id, limit,
            )
        return {"employees": [dict(r) for r in rows]}

    @router.post("/employees", status_code=201)
    async def create_employee_route(
        body: EmployeeCreateRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        employee = await hr.create_employee(
            pool, org_id=org_id, bot_id=body.bot_id, full_name=body.full_name, email=body.email,
            position=body.position, department=body.department, hire_date=body.hire_date,
            created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="hr_employee", resource_id=employee["id"],
            metadata={"full_name": body.full_name},
        )
        return employee

    @router.get("/employees/{employee_id}")
    async def get_employee(
        employee_id: str,
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await _get_employee(pool, employee_id, user["org_id"])

    @router.patch("/employees/{employee_id}/status")
    async def update_employee_status_route(
        employee_id: str,
        body: EmployeeStatusRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await hr.update_employee_status(pool, org_id=org_id, employee_id=employee_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Karyawan tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_employee", resource_id=employee_id,
            metadata={"status": body.status},
        )
        return row

    @router.delete("/employees/{employee_id}")
    async def delete_employee(
        employee_id: str,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        await pool.execute("DELETE FROM hr_employees WHERE id=$1 AND org_id=$2", employee_id, org_id)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="delete", resource_type="hr_employee", resource_id=employee_id, metadata={},
        )
        return {"deleted": True}

    # ── Evaluations ──────────────────────────────────────────────

    @router.get("/employees/{employee_id}/evaluations")
    async def list_evaluations_route(
        employee_id: str,
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        return {"evaluations": await hr.list_employee_evaluations(pool, org_id, employee_id)}

    @router.post("/employees/{employee_id}/evaluations/generate", status_code=201)
    async def generate_evaluation_route(
        employee_id: str,
        body: EvaluationGenerateRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        employee = await _get_employee(pool, employee_id, org_id)
        result = await agent.safe_run({
            "action": "generate_evaluation", "org_id": org_id, "pool": pool,
            "employee_name": employee["full_name"], "role": body.role, "notes": body.notes,
        })
        if not result.success:
            raise HTTPException(422, result.error or "Gagal generate evaluasi")
        draft = result.output["result"]
        evaluation = await hr.create_evaluation(
            pool, org_id=org_id, employee_id=employee_id, period_start=body.period_start,
            period_end=body.period_end, score=draft.get("score"), strengths=draft.get("strengths"),
            areas_to_improve=draft.get("areas_to_improve"), evaluator_id=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="hr_evaluation", resource_id=evaluation["id"],
            metadata={"employee_id": employee_id, "ai_generated": True},
        )
        return evaluation

    @router.patch("/evaluations/{evaluation_id}/finalize")
    async def finalize_evaluation_route(
        evaluation_id: str,
        user: Annotated[dict, Depends(require_permission("hr.approve"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        row = await hr.finalize_evaluation(pool, org_id=org_id, evaluation_id=evaluation_id, finalized_by=user["id"])
        if not row:
            raise HTTPException(404, "Evaluasi tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_evaluation", resource_id=evaluation_id,
            metadata={"status": "finalized"},
        )
        return row

    @router.get("/employees/{employee_id}/performance")
    async def employee_performance_route(
        employee_id: str,
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        return await hr.employee_performance(pool, org_id, employee_id)

    # ── Training ─────────────────────────────────────────────────

    @router.get("/employees/{employee_id}/training")
    async def list_training_route(
        employee_id: str,
        user: Annotated[dict, Depends(require_permission("hr.read"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        return {"training": await hr.list_employee_training(pool, org_id, employee_id)}

    @router.post("/employees/{employee_id}/training", status_code=201)
    async def create_training_route(
        employee_id: str,
        body: TrainingCreateRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        training = await hr.create_training_record(
            pool, org_id=org_id, employee_id=employee_id, training_name=body.training_name,
            reason=body.reason, recommended_by="manual", created_by=user["id"],
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="hr_training", resource_id=training["id"],
            metadata={"training_name": body.training_name},
        )
        return training

    @router.post("/employees/{employee_id}/training/recommend", status_code=201)
    async def recommend_training_route(
        employee_id: str,
        body: TrainingRecommendRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_employee(pool, employee_id, org_id)
        result = await agent.safe_run({
            "action": "recommend_training", "org_id": org_id, "pool": pool,
            "role": body.role, "areas_to_improve": body.areas_to_improve,
        })
        if not result.success:
            raise HTTPException(422, result.error or "Gagal generate rekomendasi training")
        trainings = result.output["result"].get("trainings") or []
        created = []
        for t in trainings:
            record = await hr.create_training_record(
                pool, org_id=org_id, employee_id=employee_id, training_name=t.get("name", "Training"),
                reason=t.get("reason"), recommended_by="ai", created_by=user["id"],
            )
            created.append(record)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="hr_training", metadata={"employee_id": employee_id, "ai_generated": True, "count": len(created)},
        )
        return {"training": created}

    @router.patch("/training/{training_id}/status")
    async def update_training_status_route(
        training_id: str,
        body: TrainingStatusRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        try:
            row = await hr.update_training_status(pool, org_id=org_id, training_id=training_id, status=body.status)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not row:
            raise HTTPException(404, "Training tidak ditemukan")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="hr_training", resource_id=training_id,
            metadata={"status": body.status},
        )
        return row

    # ── Task Engine: goal bebas multi-step lewat HR Agent's tools ──
    @router.post("/run-task")
    async def run_task(
        body: RunTaskRequest,
        user: Annotated[dict, Depends(require_permission("hr.write"))],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        _check_rate_limit(f"hr-run-task:{user['org_id']}", 5)
        await require_agent_enabled(pool, str(user["org_id"]), "hr")
        result = await agent.run_task(body.goal, pool=pool, org_id=user["org_id"], bot_id=body.bot_id)
        await write_audit_log(
            pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="agent_task_execution",
            metadata={"goal": body.goal, "status": result.get("status")},
        )
        return result

    return router
