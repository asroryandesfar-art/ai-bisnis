"""
bn_platform/action_executor_router.py — REST API untuk Terminal, Sandbox, Permission
dan Action Executor (AI Agent Platform).

Endpoints:
  GET  /permission/grants          — list agent permission grants
  POST /permission/grants          — buat/update grant
  DELETE /permission/grants/{id}   — cabut grant

  POST /terminal/execute           — jalankan shell command
  GET  /terminal/history           — riwayat eksekusi terminal

  GET  /sandbox/sessions           — list sandbox session aktif
  POST /sandbox/sessions           — buat sandbox session baru
  POST /sandbox/sessions/{id}/execute — jalankan command di sandbox
  DELETE /sandbox/sessions/{id}    — cleanup sandbox session

  POST /agent/execute              — jalankan goal (full pipeline)
  GET  /agent/executions           — list eksekusi sebelumnya
  GET  /agent/executions/{id}      — detail satu eksekusi
  GET  /agent/audit-log            — audit trail aksi agent
"""
import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── Request models ──────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    permission: str
    mode: str = "allow_always"   # allow_once | allow_always | deny
    resource: str = ""
    reason: str = ""


class TerminalRequest(BaseModel):
    command: str
    timeout: int = Field(default=60, ge=1, le=300)
    cwd: str | None = None
    approval_granted: bool = False


class SandboxCreateRequest(BaseModel):
    agent_name: str = "sandbox_agent"
    base_dir: str | None = None
    enable_snapshot: bool = False


class SandboxExecuteRequest(BaseModel):
    command: str
    timeout: int = Field(default=60, ge=1, le=300)


class AgentExecuteRequest(BaseModel):
    goal: str
    bot_id: str | None = None


# ─── Factory ─────────────────────────────────────────────────────────────────

def build_action_executor_router(
    *,
    get_pool,
    get_current_user,
    require_permission,
    get_agent_config,
):
    router = APIRouter(tags=["Action Executor"])

    # ── Helper untuk buat PermissionManager ──────────────────────────────────
    def _get_pm(pool, org_id):
        from permission_manager import PermissionManager
        return PermissionManager(pool, str(org_id))

    # ════════════════════════════════════════════════════════════════════════
    # PERMISSION GRANTS
    # ════════════════════════════════════════════════════════════════════════

    @router.get("/permission/grants")
    async def list_permission_grants(
        permission: str | None = None,
        user=Depends(require_permission("permission_grants.manage")),
        pool=Depends(get_pool),
    ):
        """Lihat semua agent permission grant untuk org ini."""
        org_id = user["org_id"]
        try:
            conditions = ["org_id=$1", "revoked_at IS NULL"]
            params: list[Any] = [org_id]
            if permission:
                params.append(permission)
                conditions.append(f"permission=${len(params)}")
            rows = await pool.fetch(
                f"""SELECT id, permission, grant_mode, resource, context AS reason, granted_by,
                           granted_at AS created_at, expires_at
                    FROM agent_permission_grants
                    WHERE {' AND '.join(conditions)}
                    ORDER BY granted_at DESC LIMIT 100""",
                *params,
            )
            return {"grants": [dict(r) for r in rows]}
        except Exception as e:
            raise HTTPException(500, f"Gagal mengambil grants: {e}")

    @router.post("/permission/grants", status_code=201)
    async def create_permission_grant(
        body: GrantRequest,
        user=Depends(require_permission("permission_grants.manage")),
        pool=Depends(get_pool),
    ):
        """Buat atau perbarui permission grant untuk agent action."""
        from permission_manager import Permission, GrantMode
        org_id = user["org_id"]
        pm = _get_pm(pool, org_id)
        try:
            perm_enum = Permission(body.permission)
        except ValueError:
            raise HTTPException(400, f"Permission tidak valid: '{body.permission}'. Gunakan salah satu: {[p.value for p in Permission]}")
        try:
            mode_enum = GrantMode(body.mode)
        except ValueError:
            raise HTTPException(400, f"Mode tidak valid: '{body.mode}'. Gunakan: allow_once, allow_always, atau deny")
        try:
            grant_id = await pm.grant(
                perm_enum,
                mode_enum,
                resource=body.resource or "*",
                granted_by=user.get("user_id", ""),
                context=body.reason,
            )
            return {"success": True, "grant_id": grant_id, "permission": body.permission, "mode": body.mode}
        except Exception as e:
            raise HTTPException(400, f"Gagal membuat grant: {e}")

    @router.delete("/permission/grants/{grant_id}", status_code=200)
    async def revoke_permission_grant(
        grant_id: str,
        user=Depends(require_permission("permission_grants.manage")),
        pool=Depends(get_pool),
    ):
        """Cabut permission grant."""
        org_id = user["org_id"]
        try:
            row = await pool.fetchrow(
                "SELECT id FROM agent_permission_grants WHERE id=$1 AND org_id=$2 AND revoked_at IS NULL",
                grant_id, org_id,
            )
            if not row:
                raise HTTPException(404, "Grant tidak ditemukan")
            await pool.execute(
                "UPDATE agent_permission_grants SET revoked_at=NOW() WHERE id=$1",
                grant_id,
            )
            return {"success": True, "revoked_grant_id": grant_id}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Gagal mencabut grant: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # TERMINAL
    # ════════════════════════════════════════════════════════════════════════

    @router.post("/terminal/execute")
    async def terminal_execute(
        body: TerminalRequest,
        user=Depends(require_permission("terminal.execute")),
        pool=Depends(get_pool),
    ):
        """Jalankan shell command melalui terminal agent dengan permission gate."""
        from terminal_service import TerminalService
        org_id = str(user["org_id"])
        pm = _get_pm(pool, org_id)
        svc = TerminalService(
            pool, org_id, pm,
            agent_name=f"terminal_api:{user.get('user_id', '')[:8]}",
            working_dir=body.cwd,
        )
        result = await svc.execute(
            body.command,
            timeout=body.timeout,
            cwd=body.cwd,
            approval_granted=body.approval_granted,
        )
        return result

    @router.get("/terminal/history")
    async def terminal_history(
        limit: int = 50,
        user=Depends(require_permission("terminal.read")),
        pool=Depends(get_pool),
    ):
        """Riwayat eksekusi terminal (dari audit log)."""
        from audit_logger import list_logs
        org_id = user["org_id"]
        logs = await list_logs(pool, org_id=org_id, action_type="terminal_execute", limit=min(limit, 200))
        return {"history": logs, "total": len(logs)}

    @router.post("/terminal/approve/{log_id}")
    async def terminal_approve(
        log_id: str,
        body: TerminalRequest,
        user=Depends(require_permission("terminal.approve")),
        pool=Depends(get_pool),
    ):
        """Approve dan eksekusi command terminal yang sebelumnya pending_approval."""
        from terminal_service import TerminalService
        from audit_logger import update_log
        org_id = user["org_id"]

        row = await pool.fetchrow(
            "SELECT * FROM agent_audit_log WHERE id=$1 AND org_id=$2 AND status='pending_approval'",
            log_id, org_id,
        )
        if not row:
            raise HTTPException(404, "Log pending_approval tidak ditemukan")

        await update_log(pool, log_id, status="approved", approved_by=user.get("user_id", ""))

        pm = _get_pm(pool, org_id)
        svc = TerminalService(pool, org_id, pm, agent_name="terminal_api_approved")
        result = await svc.execute(body.command, timeout=body.timeout, approval_granted=True)
        return result

    # ════════════════════════════════════════════════════════════════════════
    # SANDBOX
    # ════════════════════════════════════════════════════════════════════════

    _sandbox_managers: dict[str, Any] = {}

    def _get_sandbox_manager(pool, org_id: str):
        from sandbox_manager import SandboxManager
        org_id = str(org_id)
        if org_id not in _sandbox_managers:
            _sandbox_managers[org_id] = SandboxManager(pool)
        return _sandbox_managers[org_id]

    @router.get("/sandbox/sessions")
    async def list_sandbox_sessions(
        user=Depends(require_permission("sandbox.manage")),
        pool=Depends(get_pool),
    ):
        """Lihat daftar sandbox session aktif untuk org ini."""
        org_id = str(user["org_id"])
        mgr = _get_sandbox_manager(pool, org_id)
        sessions = [s for s in mgr.list_sessions() if s["org_id"] == org_id]
        return {"sessions": sessions, "total": len(sessions)}

    @router.post("/sandbox/sessions", status_code=201)
    async def create_sandbox_session(
        body: SandboxCreateRequest,
        user=Depends(require_permission("sandbox.manage")),
        pool=Depends(get_pool),
    ):
        """Buat sandbox session baru dengan workspace terisolasi."""
        org_id = str(user["org_id"])
        mgr = _get_sandbox_manager(pool, org_id)
        session = await mgr.create_session(
            org_id, body.agent_name,
            base_dir=body.base_dir,
            enable_snapshot=body.enable_snapshot,
            metadata={"created_by": str(user.get("user_id", ""))},
        )
        return {
            "session_id": session.session_id,
            "workspace": str(session.workspace),
            "org_id": session.org_id,
            "agent_name": session.agent_name,
        }

    @router.post("/sandbox/sessions/{session_id}/execute")
    async def sandbox_execute(
        session_id: str,
        body: SandboxExecuteRequest,
        user=Depends(require_permission("sandbox.manage")),
        pool=Depends(get_pool),
    ):
        """Jalankan command di dalam sandbox session yang sudah ada."""
        org_id = str(user["org_id"])
        mgr = _get_sandbox_manager(pool, org_id)
        session = await mgr.get_session(session_id)
        if not session or session.org_id != org_id:
            raise HTTPException(404, "Sandbox session tidak ditemukan")

        from sandbox_manager import SandboxContext
        ctx = SandboxContext(session, pool, mgr)
        result = await ctx.execute_command(body.command, timeout=body.timeout)
        stats = ctx.get_stats()
        return {**result, "sandbox_stats": stats}

    @router.delete("/sandbox/sessions/{session_id}")
    async def cleanup_sandbox_session(
        session_id: str,
        user=Depends(require_permission("sandbox.manage")),
        pool=Depends(get_pool),
    ):
        """Hapus sandbox session dan bersihkan workspace."""
        org_id = str(user["org_id"])
        mgr = _get_sandbox_manager(pool, org_id)
        session = await mgr.get_session(session_id)
        if not session or session.org_id != org_id:
            raise HTTPException(404, "Sandbox session tidak ditemukan")
        await mgr.cleanup(session_id)
        return {"success": True, "session_id": session_id, "message": "Sandbox dibersihkan"}

    # ════════════════════════════════════════════════════════════════════════
    # ACTION EXECUTOR (Full Pipeline)
    # ════════════════════════════════════════════════════════════════════════

    @router.post("/agent/execute")
    async def agent_execute(
        body: AgentExecuteRequest,
        user=Depends(require_permission("action_executor.execute")),
        pool=Depends(get_pool),
    ):
        """
        Jalankan goal multi-langkah via Action Executor pipeline.

        Pipeline: Understand → Plan → Execute (per step) → Verify → Summarize
        """
        from action_executor import ActionExecutor, ensure_schema
        from base import BaseAgent

        org_id = str(user["org_id"])
        agent_cfg = get_agent_config(pool)

        await ensure_schema(pool)

        agent = BaseAgent(**agent_cfg)
        executor = ActionExecutor(agent, pool, org_id)

        result = await executor.execute(body.goal, bot_id=body.bot_id)
        return result.to_dict()

    @router.get("/agent/executions")
    async def list_agent_executions(
        status: str | None = None,
        limit: int = 20,
        user=Depends(require_permission("action_executor.read")),
        pool=Depends(get_pool),
    ):
        """Lihat riwayat eksekusi goal agent."""
        org_id = str(user["org_id"])
        try:
            conditions = ["org_id=$1"]
            params: list[Any] = [org_id]
            if status:
                params.append(status)
                conditions.append(f"status=${len(params)}")
            params.append(max(1, min(limit, 100)))
            rows = await pool.fetch(
                f"""SELECT id, goal, status, summary, duration_ms, created_at
                    FROM agent_action_executions
                    WHERE {' AND '.join(conditions)}
                    ORDER BY created_at DESC LIMIT ${len(params)}""",
                *params,
            )
            return {"executions": [dict(r) for r in rows], "total": len(rows)}
        except Exception as e:
            raise HTTPException(500, f"Gagal mengambil executions: {e}")

    @router.get("/agent/executions/{execution_id}")
    async def get_agent_execution(
        execution_id: str,
        user=Depends(require_permission("action_executor.read")),
        pool=Depends(get_pool),
    ):
        """Detail satu eksekusi goal agent (termasuk plan, observations, verification)."""
        org_id = user["org_id"]
        row = await pool.fetchrow(
            """SELECT id, goal, status, plan, observations, verification, summary, duration_ms, created_at
               FROM agent_action_executions WHERE id=$1 AND org_id=$2""",
            execution_id, org_id,
        )
        if not row:
            raise HTTPException(404, "Execution tidak ditemukan")
        result = dict(row)
        for field in ("plan", "observations", "verification"):
            if result.get(field) and isinstance(result[field], str):
                try:
                    result[field] = json.loads(result[field])
                except Exception:
                    pass
        return result

    @router.get("/agent/audit-log")
    async def agent_audit_log(
        action_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        user=Depends(require_permission("terminal.read")),
        pool=Depends(get_pool),
    ):
        """Audit trail semua aksi agent (terminal, file, browser, dll)."""
        from audit_logger import list_logs
        org_id = user["org_id"]
        logs = await list_logs(
            pool, org_id=org_id,
            action_type=action_type,
            status=status,
            limit=min(limit, 200),
        )
        return {"logs": logs, "total": len(logs)}

    return router
