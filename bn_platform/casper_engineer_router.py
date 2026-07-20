"""bn_platform/casper_engineer_router.py — Casper Engineer router.

Endpoint tenant untuk menjalankan Casper Engineer (agen software-engineer
otonom: planning → repo analysis → self-verification → self-critique). Modul
TERPISAH dari Casper Blockchain (casper/workflow.py) — tidak saling mengubah.

RBAC-gated (workforce.read/write — menjalankan task agent otonom), rate-limited,
hasil dipersist per-tenant ke `casper_engineer_runs`. Mengikuti pola persis
bn_platform/research.py + agent_center.py (factory DI, tanpa import dari main).
"""
import json
from typing import Annotated, Awaitable, Callable, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from casper_engineer import CasperEngineerAgent, EXECUTABLE_TOOLS, WRITE_TOOLS
from .security import _check_rate_limit

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]


class EngineerRunRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=4000)
    repo_context: Optional[str] = Field(None, max_length=12000)
    # Phase 2a: baca repo asli otomatis dari Local Agent (read-only) sebelum analisis.
    auto_repo: bool = False
    device_id: Optional[str] = None
    repo_path: str = Field(".", max_length=500)


class ExecuteStepRequest(BaseModel):
    tool: str = Field(..., max_length=40)
    args: dict = Field(default_factory=dict)
    rationale: Optional[str] = Field(None, max_length=400)
    device_id: Optional[str] = None
    timeout: int = Field(60, ge=5, le=120)


class InvestigateRequest(BaseModel):
    device_id: Optional[str] = None
    max_rounds: int = Field(5, ge=1, le=10)


def build_casper_engineer_router(*, get_pool: GetPool, get_current_user: GetCurrentUser,
                                  require_permission, get_agent_config: Callable[[], dict]) -> APIRouter:
    router = APIRouter(prefix="/casper/engineer", tags=["casper-engineer"])
    cfg = get_agent_config()
    agent = CasperEngineerAgent(
        api_key=cfg.get("api_key"), model=cfg.get("model"), base_url=cfg.get("base_url"),
        deepseek_api_key=cfg.get("deepseek_api_key", ""),
        openrouter_api_key=cfg.get("openrouter_api_key", ""),
        gemini_api_key=cfg.get("gemini_api_key", ""),
        app_url=cfg.get("app_url", "https://botnesia.id"),
    )

    @router.post("/run")
    async def run_engineer(
        body: EngineerRunRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        _check_rate_limit(f"casper_engineer:{user['org_id']}", 10)
        repo_context = body.repo_context or ""
        repo_meta = None
        if body.auto_repo:
            # Baca repo asli dari mesin user via Local Agent (read-only). Kalau
            # perangkat tak terhubung, LocalAgentManager.execute meng-raise 503 —
            # biarkan naik supaya user tahu harus menjalankan botnesia-agent.
            from bn_platform.local_agent_router import get_manager
            from casper_engineer_exec import gather_repo_context
            auto_ctx, repo_meta = await gather_repo_context(
                get_manager().execute, str(user["org_id"]), pool,
                device_id=body.device_id, path=body.repo_path,
            )
            repo_context = (repo_context + "\n\n" + auto_ctx).strip() if repo_context else auto_ctx
        context = {
            "goal": body.goal,
            "repo_context": repo_context,
            "org_id": str(user["org_id"]),
            "_observability_pool": pool,   # supaya run tercatat di observability
        }
        result = await agent.safe_run(context)
        out = result.output or {}

        row = await pool.fetchrow(
            """INSERT INTO casper_engineer_runs
               (org_id, user_id, goal, repo_context, planning, repository_analysis,
                self_verification, self_critique, status, confidence)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10)
               RETURNING id, created_at""",
            user["org_id"], user["id"], body.goal, repo_context or None,
            json.dumps(out.get("planning", {})),
            json.dumps(out.get("repository_analysis", {})),
            json.dumps(out.get("self_verification", {})),
            json.dumps(out.get("self_critique", {})),
            out.get("status", "needs_review"),
            out.get("confidence"),
        )
        return {
            "id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
            "goal": body.goal,
            "status": out.get("status", "needs_review"),
            "confidence": out.get("confidence"),
            "needs_repo_context": out.get("needs_repo_context", False),
            "repo_ingest": repo_meta,
            "planning": out.get("planning", {}),
            "repository_analysis": out.get("repository_analysis", {}),
            "self_verification": out.get("self_verification", {}),
            "self_critique": out.get("self_critique", {}),
        }

    @router.get("/runs")
    async def list_runs(
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        limit: int = 20,
    ):
        rows = await pool.fetch(
            """SELECT id, goal, status, confidence, created_at
               FROM casper_engineer_runs WHERE org_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            user["org_id"], min(max(limit, 1), 100),
        )
        return [
            {
                "id": str(r["id"]), "goal": r["goal"], "status": r["status"],
                "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    @router.get("/run/{run_id}")
    async def get_run(
        run_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        row = await pool.fetchrow(
            """SELECT id, goal, repo_context, planning, repository_analysis,
                      self_verification, self_critique, status, confidence, created_at,
                      deploy_hash, session_hash, proof_mode, explorer_url, anchored_at
               FROM casper_engineer_runs WHERE id = $1 AND org_id = $2""",
            _as_uuid(run_id), user["org_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        # Pool utama tidak punya jsonb codec -> kolom JSONB kembali sebagai string.
        return {
            "id": str(row["id"]), "goal": row["goal"], "repo_context": row["repo_context"],
            "planning": _load_json(row["planning"]),
            "repository_analysis": _load_json(row["repository_analysis"]),
            "self_verification": _load_json(row["self_verification"]),
            "self_critique": _load_json(row["self_critique"]),
            "status": row["status"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "created_at": row["created_at"].isoformat(),
            "casper": {
                "deploy_hash": row["deploy_hash"], "session_hash": row["session_hash"],
                "proof_mode": row["proof_mode"], "explorer_url": row["explorer_url"],
                "anchored_at": row["anchored_at"].isoformat() if row["anchored_at"] else None,
            } if row["deploy_hash"] else None,
        }

    @router.post("/run/{run_id}/propose-steps")
    async def propose_steps(
        run_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        row = await pool.fetchrow(
            "SELECT goal, repo_context, self_critique FROM casper_engineer_runs WHERE id=$1 AND org_id=$2",
            _as_uuid(run_id), user["org_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        _check_rate_limit(f"casper_engineer_propose:{user['org_id']}", 10)
        improved = _load_json(row["self_critique"]).get("improved_plan", {})
        proposed = await agent.propose_steps(row["goal"], improved, row["repo_context"] or "")
        saved = []
        for i, s in enumerate(proposed.get("steps", [])):
            r = await pool.fetchrow(
                """INSERT INTO casper_engineer_steps (run_id, org_id, seq, tool, args, rationale, status)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6,'proposed') RETURNING id""",
                _as_uuid(run_id), user["org_id"], i, s["tool"], json.dumps(s["args"]), s.get("rationale"),
            )
            saved.append({**s, "id": str(r["id"]), "status": "proposed"})
        return {"steps": saved, "degraded": bool(proposed.get("_llm_unavailable"))}

    @router.post("/run/{run_id}/execute-step")
    async def execute_step(
        run_id: str,
        body: ExecuteStepRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        # Allowlist server-side (batas pertama). Keamanan nyata (denylist destruktif,
        # secret-guard, approval user) ditegakkan di perangkat oleh botnesia_local_agent.
        if body.tool not in EXECUTABLE_TOOLS:
            raise HTTPException(status_code=400, detail=f"Tool '{body.tool}' tidak diizinkan untuk Casper Engineer.")
        run = await pool.fetchrow(
            "SELECT id FROM casper_engineer_runs WHERE id=$1 AND org_id=$2", _as_uuid(run_id), user["org_id"],
        )
        if not run:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        _check_rate_limit(f"casper_engineer_exec:{user['org_id']}", 20)
        # Dispatch ke Local Agent (mesin user). 503 bila tak ada perangkat -> naikkan apa adanya.
        from bn_platform.local_agent_router import get_manager
        result = await get_manager().execute(
            str(user["org_id"]), body.tool, body.args,
            device_id=body.device_id, initiated_by=f"casper_engineer:{user['id']}",
            timeout=body.timeout, pool=pool,
        )
        status = "completed" if isinstance(result, dict) and result.get("success") else "failed"
        r = await pool.fetchrow(
            """INSERT INTO casper_engineer_steps (run_id, org_id, tool, args, rationale, status, result, device_id)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7::jsonb,$8) RETURNING id, created_at""",
            _as_uuid(run_id), user["org_id"], body.tool, json.dumps(body.args), body.rationale,
            status, json.dumps(result, default=str), body.device_id,
        )
        return {
            "id": str(r["id"]), "tool": body.tool, "status": status,
            "requires_approval": body.tool in WRITE_TOOLS, "result": result,
            "created_at": r["created_at"].isoformat(),
        }

    @router.post("/run/{run_id}/investigate")
    async def investigate_repo(
        run_id: str,
        body: InvestigateRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        row = await pool.fetchrow(
            "SELECT goal, repo_context FROM casper_engineer_runs WHERE id=$1 AND org_id=$2",
            _as_uuid(run_id), user["org_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        _check_rate_limit(f"casper_engineer_investigate:{user['org_id']}", 5)
        from bn_platform.local_agent_router import get_manager
        mgr = get_manager()
        # Pre-check perangkat (sama seperti execute) -> 503 jelas kalau tak ada.
        _did, conn = mgr._pick(str(user["org_id"]), body.device_id)
        if not conn:
            raise HTTPException(status_code=503, detail="Local agent tidak terhubung. Jalankan botnesia-agent di komputer Anda.")
        out = await agent.investigate(
            row["goal"], mgr.execute, str(user["org_id"]), pool,
            device_id=body.device_id, max_rounds=body.max_rounds,
        )
        findings = out.get("findings") or ""
        if findings:
            merged = ((row["repo_context"] or "") + "\n\n[AUTONOMOUS INVESTIGATION]\n" + findings).strip()[:12000]
            await pool.execute(
                "UPDATE casper_engineer_runs SET repo_context=$2 WHERE id=$1", _as_uuid(run_id), merged,
            )
        return {"findings": findings, "trace": out.get("trace", []), "rounds": out.get("rounds", 0)}

    @router.get("/run/{run_id}/steps")
    async def list_steps(
        run_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        rows = await pool.fetch(
            """SELECT id, seq, tool, args, rationale, status, result, created_at
               FROM casper_engineer_steps WHERE run_id=$1 AND org_id=$2 ORDER BY created_at""",
            _as_uuid(run_id), user["org_id"],
        )
        return [
            {
                "id": str(r["id"]), "seq": r["seq"], "tool": r["tool"],
                "args": _load_json(r["args"]), "rationale": r["rationale"],
                "status": r["status"], "result": _load_json(r["result"]),
                "requires_approval": r["tool"] in WRITE_TOOLS,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    @router.post("/run/{run_id}/anchor")
    async def anchor_run(
        run_id: str,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        """Unifikasi Casper: anchor artefak run Casper Engineer ke Casper Blockchain
        (bukti immutable & terverifikasi pihak ketiga bahwa keputusan engineering AI
        ini benar dibuat). Real-mode via casper_anchor; fallback demo-hash bila
        CASPER_* env belum diset — pola identik casper/workflow.py."""
        import hashlib
        row = await pool.fetchrow(
            """SELECT goal, status, confidence, planning, self_critique
               FROM casper_engineer_runs WHERE id=$1 AND org_id=$2""",
            _as_uuid(run_id), user["org_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run tidak ditemukan")
        _check_rate_limit(f"casper_engineer_anchor:{user['org_id']}", 10)
        org_id = str(user["org_id"])
        artifact = {
            "run_id": run_id, "goal": row["goal"], "status": row["status"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "planning": _load_json(row["planning"]), "critique": _load_json(row["self_critique"]),
        }
        session_hash = hashlib.sha256(
            json.dumps(artifact, sort_keys=True, default=str).encode()
        ).hexdigest()
        summary = f"Casper Engineer run: {(row['goal'] or '')[:120]}"
        try:
            import casper_anchor as _ca
            result = await _ca.anchor_session(
                org_id=org_id, session_id=run_id, summary=summary,
                ai_action_hash=session_hash,
                workflow_hash=hashlib.sha256(f"engineer:{run_id}".encode()).hexdigest(),
            )
            deploy_hash = result.get("deploy_hash")
            explorer_url = result.get("explorer_url")
            proof_mode, casper_status = "real", "confirmed"
        except Exception as exc:
            # Fallback demo (CASPER_* belum diset) — jujur dilabeli proof_mode=demo.
            deploy_hash = "demo-" + hashlib.sha256(f"{run_id}:{session_hash}".encode()).hexdigest()[:56]
            explorer_url = f"https://testnet.cspr.live/deploy/{deploy_hash}"
            proof_mode, casper_status = "demo", "demo"
        await pool.execute(
            """UPDATE casper_engineer_runs
               SET deploy_hash=$2, session_hash=$3, proof_mode=$4, explorer_url=$5, anchored_at=NOW()
               WHERE id=$1""",
            _as_uuid(run_id), deploy_hash, session_hash, proof_mode, explorer_url,
        )
        return {
            "deploy_hash": deploy_hash, "session_hash": session_hash,
            "proof_mode": proof_mode, "status": casper_status, "explorer_url": explorer_url,
        }

    return router


def _load_json(value):
    """JSONB dari pool utama (tanpa codec) kembali sebagai string -> parse aman."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


def _as_uuid(value: str):
    import uuid
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="ID tidak valid") from exc
