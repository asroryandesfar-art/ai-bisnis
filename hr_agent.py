"""
agents/hr_agent.py — HR Agent (AI Workforce Phase 3)

CV screening, candidate scoring, interview question generator, employee
evaluation (draft, butuh finalisasi manusia via hr.approve), training
recommendation, dan performance tracking -- untuk karyawan/kandidat
BISNIS TENANT sendiri (bukan karyawan BotNesia).

Data di sini sensitif (PII kandidat/karyawan, hasil evaluasi performa),
jadi -- sama seperti finance_agent.py/marketing_agent.py -- HRAgent TIDAK
pernah dipasang di jalur chat publik/customer-facing, hanya lewat endpoint
terautentikasi dengan permission hr.write/hr.approve.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import asyncpg

from base import BaseAgent, AgentResult

CANDIDATE_STATUSES = {"new", "screened", "interview", "offered", "hired", "rejected"}
EMPLOYEE_STATUSES = {"active", "on_leave", "terminated"}
TRAINING_STATUSES = {"recommended", "in_progress", "completed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def extract_cv_text(raw: bytes, *, filename: str = "", mime: str = "") -> str:
    """Ekstraksi teks CV mandiri (PDF/DOCX/plain text) -- pola yang sama
    dengan main.py::_process_document_sync, tapi modul berdiri sendiri
    supaya bn_platform tidak perlu `from main import ...` (mencegah
    circular import, konsisten dengan konvensi seluruh bn_platform/*)."""
    filename_l = (filename or "").lower()
    mime_l = (mime or "").lower()
    if "pdf" in mime_l or filename_l.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""
    if "word" in mime_l or "docx" in mime_l or filename_l.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                xml_bytes = z.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            return "\n".join(node.text for node in root.findall(".//w:t", ns) if node.text)
        except Exception:
            return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ─── CANDIDATES ─────────────────────────────────────────────────

async def create_candidate(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None,
                            name: str, email: str | None, phone: str | None,
                            position_applied: str | None, cv_text: str | None,
                            cv_filename: str | None, created_by: str | None) -> dict:
    candidate_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO hr_candidates
               (id, org_id, bot_id, name, email, phone, position_applied, cv_text, cv_filename, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
        candidate_id, org_id, bot_id, name, email, phone, position_applied, cv_text, cv_filename,
        str(created_by) if created_by else None,
    )
    return dict(row)


async def update_candidate_status(pool: asyncpg.Pool, *, org_id: str, candidate_id: str,
                                   status: str) -> dict | None:
    if status not in CANDIDATE_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    row = await pool.fetchrow(
        """UPDATE hr_candidates SET status=$1, updated_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        status, candidate_id, org_id,
    )
    return dict(row) if row else None


async def save_candidate_score(pool: asyncpg.Pool, *, org_id: str, candidate_id: str,
                                score: int, breakdown: dict) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE hr_candidates SET score=$1, score_breakdown=$2::jsonb, status='screened', updated_at=NOW()
           WHERE id=$3 AND org_id=$4 RETURNING *""",
        score, json.dumps(breakdown), candidate_id, org_id,
    )
    return dict(row) if row else None


# ─── EMPLOYEES ──────────────────────────────────────────────────

async def create_employee(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None,
                           full_name: str, email: str | None, position: str | None,
                           department: str | None, hire_date: datetime | None,
                           created_by: str | None) -> dict:
    employee_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO hr_employees (id, org_id, bot_id, full_name, email, position, department, hire_date, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        employee_id, org_id, bot_id, full_name, email, position, department, hire_date,
        str(created_by) if created_by else None,
    )
    return dict(row)


async def update_employee_status(pool: asyncpg.Pool, *, org_id: str, employee_id: str,
                                  status: str) -> dict | None:
    if status not in EMPLOYEE_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    row = await pool.fetchrow(
        """UPDATE hr_employees SET status=$1, updated_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        status, employee_id, org_id,
    )
    return dict(row) if row else None


# ─── EVALUATIONS ────────────────────────────────────────────────

async def create_evaluation(pool: asyncpg.Pool, *, org_id: str, employee_id: str,
                             period_start: datetime | None, period_end: datetime | None,
                             score: int | None, strengths: str | None,
                             areas_to_improve: str | None, evaluator_id: str | None) -> dict:
    evaluation_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO hr_evaluations
               (id, org_id, employee_id, period_start, period_end, score, strengths, areas_to_improve, evaluator_id)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        evaluation_id, org_id, employee_id, period_start, period_end, score, strengths,
        areas_to_improve, str(evaluator_id) if evaluator_id else None,
    )
    return dict(row)


async def finalize_evaluation(pool: asyncpg.Pool, *, org_id: str, evaluation_id: str,
                               finalized_by: str | None) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE hr_evaluations SET status='finalized', finalized_by=$1, finalized_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        str(finalized_by) if finalized_by else None, evaluation_id, org_id,
    )
    return dict(row) if row else None


async def list_employee_evaluations(pool: asyncpg.Pool, org_id: str, employee_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT * FROM hr_evaluations WHERE org_id=$1 AND employee_id=$2 ORDER BY created_at DESC""",
        org_id, employee_id,
    )
    return [dict(r) for r in rows]


async def employee_performance(pool: asyncpg.Pool, org_id: str, employee_id: str) -> dict:
    """Performance tracking: riwayat skor evaluasi + tren sederhana."""
    rows = await pool.fetch(
        """SELECT score, created_at FROM hr_evaluations
           WHERE org_id=$1 AND employee_id=$2 AND status='finalized' AND score IS NOT NULL
           ORDER BY created_at ASC""",
        org_id, employee_id,
    )
    scores = [int(r["score"]) for r in rows]
    trend = "insufficient_data"
    if len(scores) >= 2:
        delta = scores[-1] - scores[0]
        trend = "naik" if delta > 0 else ("turun" if delta < 0 else "stabil")
    return {
        "history": [{"score": int(r["score"]), "created_at": r["created_at"].isoformat()} for r in rows],
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        "latest_score": scores[-1] if scores else None,
        "trend": trend,
    }


# ─── TRAINING ───────────────────────────────────────────────────

async def create_training_record(pool: asyncpg.Pool, *, org_id: str, employee_id: str,
                                  training_name: str, reason: str | None,
                                  recommended_by: str, created_by: str | None) -> dict:
    training_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO hr_training_records (id, org_id, employee_id, training_name, reason, recommended_by, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        training_id, org_id, employee_id, training_name, reason, recommended_by,
        str(created_by) if created_by else None,
    )
    return dict(row)


async def update_training_status(pool: asyncpg.Pool, *, org_id: str, training_id: str,
                                  status: str) -> dict | None:
    if status not in TRAINING_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    extra = ", completed_at=NOW()" if status == "completed" else ""
    row = await pool.fetchrow(
        f"UPDATE hr_training_records SET status=$1{extra} WHERE id=$2 AND org_id=$3 RETURNING *",
        status, training_id, org_id,
    )
    return dict(row) if row else None


async def list_employee_training(pool: asyncpg.Pool, org_id: str, employee_id: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT * FROM hr_training_records WHERE org_id=$1 AND employee_id=$2 ORDER BY created_at DESC",
        org_id, employee_id,
    )
    return [dict(r) for r in rows]


# ─── DASHBOARD ──────────────────────────────────────────────────

async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    candidate_counts = await pool.fetch(
        "SELECT status, COUNT(*) AS cnt FROM hr_candidates WHERE org_id=$1 GROUP BY status", org_id,
    )
    employee_counts = await pool.fetch(
        "SELECT status, COUNT(*) AS cnt FROM hr_employees WHERE org_id=$1 GROUP BY status", org_id,
    )
    avg_score = await pool.fetchval(
        """SELECT ROUND(AVG(score)::numeric, 1) FROM hr_evaluations
           WHERE org_id=$1 AND status='finalized' AND score IS NOT NULL
             AND created_at >= NOW() - INTERVAL '90 days'""",
        org_id,
    )
    pending_training = await pool.fetchval(
        "SELECT COUNT(*) FROM hr_training_records WHERE org_id=$1 AND status='recommended'", org_id,
    )
    return {
        "candidates_by_status": {r["status"]: int(r["cnt"]) for r in candidate_counts},
        "employees_by_status": {r["status"]: int(r["cnt"]) for r in employee_counts},
        "avg_evaluation_score_90d": float(avg_score) if avg_score is not None else None,
        "pending_training_recommendations": int(pending_training or 0),
    }


# ─── AGENT ──────────────────────────────────────────────────────

class HRAgent(BaseAgent):
    name = "hr_agent"
    skills = ["candidate_screening", "interview_question_generation", "employee_evaluation", "training_recommendation"]
    tools: list[str] = ["database_query", "knowledge_search", "memory_lookup"]
    goals = [
        "Membantu proses rekrutmen dan evaluasi karyawan secara objektif berbasis bukti.",
        "Merekomendasikan training yang relevan untuk pengembangan karyawan.",
    ]
    system_prompt = """Kamu adalah HR Agent dalam sistem multi-agent BotNesia (AI Workforce).

Tugas: bantu proses HR bisnis tenant -- screening CV, scoring kandidat,
membuat pertanyaan interview, draft evaluasi karyawan, dan rekomendasi
training. Selalu objektif, berbasis bukti dari teks yang diberikan, dan
hindari diskriminasi berdasarkan usia/gender/agama/suku/disabilitas.

Balas HANYA JSON sesuai instruksi tugas spesifik yang diberikan di
pesan user. Jangan menyertakan penjelasan di luar JSON."""

    async def score_candidate(self, *, cv_text: str, position: str, requirements: str | None) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON dengan field: "
             "score (0-100), skills_match (0-100), experience_match (0-100), education_match (0-100), "
             "summary (ringkasan singkat), recommendation ('lanjut_interview'|'pertimbangkan'|'tidak_sesuai')."},
            {"role": "user", "content": f"Posisi: {position}\nRequirement: {requirements or '-'}\n\nCV:\n{cv_text[:6000]}"},
        ]
        return await self._call_llm_json(messages, temperature=0.2, default={"score": None, "_llm_unavailable": True})

    async def generate_interview_questions(self, *, cv_text: str, position: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON dengan field: "
             "questions (list of string, 5-8 pertanyaan interview yang relevan dengan CV dan posisi)."},
            {"role": "user", "content": f"Posisi: {position}\n\nCV:\n{cv_text[:6000]}"},
        ]
        return await self._call_llm_json(messages, temperature=0.5, default={"questions": [], "_llm_unavailable": True})

    async def generate_evaluation(self, *, employee_name: str, role: str, notes: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON dengan field: "
             "score (0-100), strengths (ringkasan kekuatan), areas_to_improve (ringkasan area perbaikan)."},
            {"role": "user", "content": f"Karyawan: {employee_name}\nRole: {role}\n\nCatatan manajer:\n{notes}"},
        ]
        return await self._call_llm_json(messages, temperature=0.3, default={"score": None, "_llm_unavailable": True})

    async def recommend_training(self, *, role: str, areas_to_improve: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON dengan field: "
             "trainings (list of object {name, reason}, 2-4 rekomendasi training relevan)."},
            {"role": "user", "content": f"Role: {role}\nArea yang perlu ditingkatkan:\n{areas_to_improve}"},
        ]
        return await self._call_llm_json(messages, temperature=0.4, default={"trainings": [], "_llm_unavailable": True})

    async def run(self, context: dict) -> AgentResult:
        """Hanya dipanggil dari permukaan TERAUTENTIKASI. context wajib:
        action ('score_candidate'|'generate_interview_questions'|'generate_evaluation'|'recommend_training'),
        org_id, pool, plus field spesifik per action (lihat method masing-masing)."""
        action = context.get("action")
        org_id = context.get("org_id")
        pool: asyncpg.Pool | None = context.get("pool") or context.get("_observability_pool")
        if not org_id or not pool:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                                error="org_id dan pool wajib diisi")

        if action == "score_candidate":
            result = await self.score_candidate(
                cv_text=context.get("cv_text", ""), position=context.get("position", ""),
                requirements=context.get("requirements"),
            )
        elif action == "generate_interview_questions":
            result = await self.generate_interview_questions(
                cv_text=context.get("cv_text", ""), position=context.get("position", ""),
            )
        elif action == "generate_evaluation":
            result = await self.generate_evaluation(
                employee_name=context.get("employee_name", ""), role=context.get("role", ""),
                notes=context.get("notes", ""),
            )
        elif action == "recommend_training":
            result = await self.recommend_training(
                role=context.get("role", ""), areas_to_improve=context.get("areas_to_improve", ""),
            )
        else:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                                error=f"action tidak dikenali: {action}")

        if result.get("_llm_unavailable"):
            return AgentResult(agent=self.name, success=False, output={"result": result},
                                latency_ms=0, error="LLM tidak tersedia")
        return AgentResult(agent=self.name, success=True, output={"result": result}, latency_ms=0)
