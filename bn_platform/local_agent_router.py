"""
bn_platform/local_agent_router.py — BotNesia Local Agent

Mengizinkan tenant menginstall agen lokal di PC mereka sehingga AI BotNesia
bisa mengakses file, terminal, dan browser di komputer user.

Arsitektur:
  User chat → BotNesia cloud (AI reasoning) → WebSocket → Local Agent (PC user)
                                                             ├── file read/write
                                                             ├── terminal shell
                                                             └── browser lokal

WebSocket endpoint: WS /api/local-agent/ws?token=<jwt>
REST endpoints:
  GET  /api/local-agent/status              — apakah local agent terhubung
  POST /api/local-agent/execute             — kirim perintah ke local agent
  GET  /api/local-agent/history             — riwayat perintah (filter opsional ?status=)
  POST /api/local-agent/disconnect          — putus koneksi
  POST /api/local-agent/commands/{id}/approve — setujui & jalankan aksi berisiko yang pending
  POST /api/local-agent/commands/{id}/reject  — tolak aksi berisiko yang pending
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .security import write_audit_log

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS local_agent_connections (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    hostname     TEXT,
    platform     TEXT,
    username     TEXT,
    agent_version TEXT DEFAULT '1.0.0',
    connected_at  TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ DEFAULT NOW(),
    disconnected_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_local_agent_conn_org ON local_agent_connections(org_id);

CREATE TABLE IF NOT EXISTS local_agent_commands (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    connection_id UUID,
    tool         TEXT NOT NULL,
    args         TEXT DEFAULT '{}',
    result       TEXT,
    status       TEXT DEFAULT 'pending',
    initiated_by TEXT,
    duration_ms  INTEGER,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    rejected_reason TEXT,
    approved_by  TEXT,
    approved_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_local_agent_cmd_org ON local_agent_commands(org_id, created_at DESC);
ALTER TABLE local_agent_commands ADD COLUMN IF NOT EXISTS rejected_reason TEXT;
ALTER TABLE local_agent_commands ADD COLUMN IF NOT EXISTS approved_by TEXT;
ALTER TABLE local_agent_commands ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for stmt in SCHEMA_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                await conn.execute(s)


# ─── Connection Manager ────────────────────────────────────────────────────────

class LocalAgentManager:
    """Singleton yang mengelola WebSocket connections per org_id."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}       # org_id → ws
        self._meta: dict[str, dict] = {}                   # org_id → metadata
        self._futures: dict[str, asyncio.Future] = {}      # command_id → future
        self._conn_ids: dict[str, str] = {}                # org_id → connection_id (DB)

    def is_connected(self, org_id: str) -> bool:
        return org_id in self._connections

    def get_meta(self, org_id: str) -> dict:
        return self._meta.get(org_id, {})

    async def connect(self, org_id: str, ws: WebSocket, meta: dict, pool: asyncpg.Pool):
        await ws.accept()
        self._connections[org_id] = ws
        self._meta[org_id] = meta
        try:
            row = await pool.fetchrow(
                """INSERT INTO local_agent_connections (org_id, hostname, platform, username, agent_version)
                   VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                org_id, meta.get("hostname"), meta.get("platform"),
                meta.get("username"), meta.get("version", "1.0.0"),
            )
            if row:
                self._conn_ids[org_id] = str(row["id"])
        except Exception:
            logger.warning("local_agent: gagal simpan koneksi ke DB")

    async def disconnect(self, org_id: str, pool: asyncpg.Pool):
        conn_id = self._conn_ids.pop(org_id, None)
        self._connections.pop(org_id, None)
        self._meta.pop(org_id, None)
        # Fail semua futures yang pending untuk org ini
        to_cancel = [cid for cid, f in self._futures.items() if not f.done()]
        for cid in to_cancel:
            fut = self._futures.pop(cid, None)
            if fut and not fut.done():
                fut.set_exception(RuntimeError("Local agent terputus"))
        if conn_id:
            try:
                await pool.execute(
                    "UPDATE local_agent_connections SET disconnected_at=NOW() WHERE id=$1",
                    conn_id,
                )
            except Exception:
                pass

    async def execute(
        self, org_id: str, tool: str, args: dict, *,
        initiated_by: str = "", timeout: int = 30, pool: asyncpg.Pool,
    ) -> dict:
        if not self.is_connected(org_id):
            raise HTTPException(503, "Local agent tidak terhubung. Jalankan botnesia-agent di komputer Anda.")

        command_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._futures[command_id] = future

        conn_id = self._conn_ids.get(org_id)
        cmd_db_id = None
        try:
            row = await pool.fetchrow(
                """INSERT INTO local_agent_commands (org_id, connection_id, tool, args, status, initiated_by)
                   VALUES ($1,$2,$3,$4,'running',$5) RETURNING id""",
                org_id, conn_id, tool, json.dumps(args), initiated_by,
            )
            if row:
                cmd_db_id = str(row["id"])
        except Exception:
            pass

        ws = self._connections[org_id]
        t0 = time.monotonic()
        try:
            await ws.send_json({"type": "execute", "command_id": command_id, "tool": tool, "args": args})
            result = await asyncio.wait_for(future, timeout=timeout)
            duration = int((time.monotonic() - t0) * 1000)
            if cmd_db_id:
                await pool.execute(
                    """UPDATE local_agent_commands SET result=$2, status=$3,
                       duration_ms=$4, completed_at=NOW() WHERE id=$1""",
                    cmd_db_id, json.dumps(result), "completed" if result.get("success") else "failed", duration,
                )
            return result
        except asyncio.TimeoutError:
            self._futures.pop(command_id, None)
            if cmd_db_id:
                await pool.execute(
                    "UPDATE local_agent_commands SET status='timeout', completed_at=NOW() WHERE id=$1", cmd_db_id
                )
            raise HTTPException(504, f"Local agent tidak merespons dalam {timeout} detik")
        finally:
            self._futures.pop(command_id, None)

    async def handle_result(self, command_id: str, result: dict):
        fut = self._futures.get(command_id)
        if fut and not fut.done():
            fut.set_result(result)

    async def update_last_seen(self, org_id: str, pool: asyncpg.Pool):
        conn_id = self._conn_ids.get(org_id)
        if conn_id:
            try:
                await pool.execute(
                    "UPDATE local_agent_connections SET last_seen_at=NOW() WHERE id=$1", conn_id
                )
            except Exception:
                pass


# Singleton global
_manager = LocalAgentManager()


def get_manager() -> LocalAgentManager:
    return _manager


# ─── Request models ────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    tool: str = Field(description="read_file | write_file | list_dir | run_command | find_files | get_info | search_text | tree | scan_project")
    args: dict = Field(default_factory=dict)
    timeout: int = Field(default=30, ge=5, le=120)


class ComputerAgentRequest(BaseModel):
    goal: str = Field(description="Natural language goal for the computer agent")
    timeout: int = Field(default=30, ge=5, le=120)


class LocalAgentRejectRequest(BaseModel):
    reason: str | None = None


# Tools yang aman dijalankan langsung (read-only)
READONLY_TOOLS = frozenset({"get_info", "list_dir", "read_file", "find_files", "search_text", "tree", "scan_project"})
# Tools yang butuh approval
RISKY_TOOLS = frozenset({"run_command", "write_file", "edit_file", "delete_file"})

_COMPUTER_AGENT_SYSTEM = """Kamu adalah Computer Agent yang mengendalikan komputer lokal melalui tools.

Info sistem komputer yang terhubung:
{system_context}

Tools yang tersedia (read-only, langsung aman):
- get_info: Info sistem (hostname, OS, disk). Args: {{}}
- list_dir: Isi folder. Args: {{"path": "~/"}}
- read_file: Baca file. Args: {{"path": "~/file.txt"}}
- find_files: Cari file by pattern. Args: {{"pattern": "*.py", "dir": "~/"}}
- search_text: Cari teks di dalam file. Args: {{"pattern": "keyword", "dir": "~/", "file_ext": ".py"}}
- tree: Struktur direktori. Args: {{"path": "~/project", "max_depth": 3}}
- scan_project: Scan project (deteksi jenis, file kunci). Args: {{"path": "~/project"}}

Tools yang butuh approval (akan masuk antrian):
- run_command: Jalankan shell. Args: {{"command": "npm run build"}}
- write_file / edit_file / delete_file: Modifikasi file

Goal user: {goal}

ATURAN PENTING:
- Selalu gunakan "~/" untuk home directory (JANGAN "/home/user" atau path hardcoded)
- Untuk mencari project, gunakan find_files dengan dir "~/" dan pattern yang relevan
- Balas HANYA dengan JSON array of steps (tanpa teks lain):

[
  {{"tool": "list_dir", "args": {{"path": "~/"}}, "reason": "Lihat isi home directory"}},
  {{"tool": "find_files", "args": {{"pattern": "*botnesia*", "dir": "~/"}}, "reason": "Cari folder BotNesia"}}
]

Maksimal 5 steps. Prioritaskan read-only tools. Beri reason singkat tiap step."""


async def _plan_with_llm(goal: str, call_llm, meta: dict | None = None) -> list[dict]:
    """Gunakan LLM untuk membuat rencana tool calls dari natural language goal."""
    system_ctx = ""
    if meta:
        system_ctx = f"Hostname: {meta.get('hostname','unknown')}, Platform: {meta.get('platform','unknown')}, User: {meta.get('username','unknown')}"
    else:
        system_ctx = "Tidak diketahui — gunakan ~/ untuk semua path"
    prompt = _COMPUTER_AGENT_SYSTEM.format(goal=goal, system_context=system_ctx)
    try:
        raw = await call_llm(prompt)
        # Ekstrak JSON dari respons
        import re
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("LLM tidak mengembalikan JSON array")
        steps = json.loads(match.group(0))
        if not isinstance(steps, list):
            raise ValueError("Bukan list")
        validated = []
        for s in steps[:6]:
            tool = s.get("tool", "")
            if tool in READONLY_TOOLS or tool in RISKY_TOOLS:
                validated.append({"tool": tool, "args": s.get("args", {}), "reason": s.get("reason", "")})
        return validated
    except Exception as e:
        logger.warning("computer_agent: LLM plan error: %s", e)
        # Fallback sederhana: get_info + list_dir
        return [
            {"tool": "get_info", "args": {}, "reason": "Cek info sistem"},
            {"tool": "list_dir", "args": {"path": "~/"}, "reason": "Lihat isi home directory"},
        ]


# ─── Router factory ───────────────────────────────────────────────────────────

def build_local_agent_router(*, get_pool, get_current_user, require_permission, decode_token, call_llm=None):
    router = APIRouter(tags=["Local Agent"])

    # ── WebSocket endpoint ─────────────────────────────────────────────────────

    @router.websocket("/local-agent/ws")
    async def local_agent_ws(websocket: WebSocket, token: str = ""):
        """
        Local agent connects here. Auth via ?token=<jwt>.
        Protocol:
          Agent → Server: {"type":"ready","hostname":...,"platform":...,"username":...,"version":...}
          Server → Agent: {"type":"execute","command_id":...,"tool":...,"args":{...}}
          Agent → Server: {"type":"result","command_id":...,"success":true,"output":...}
          Server → Agent: {"type":"ping"}
          Agent → Server: {"type":"pong"}
        """
        pool = get_pool()
        mgr = get_manager()

        # Accept dulu — harus dilakukan sebelum close/send apapun
        await websocket.accept()

        # Validasi token
        org_id: str | None = None
        try:
            payload = decode_token(token)
            org_id = str(payload["org"])
        except Exception:
            await websocket.send_json({"type": "error", "message": "Token tidak valid atau kadaluarsa"})
            await websocket.close(code=4001)
            return

        # Tunggu pesan "ready" dari agent
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            msg = json.loads(raw)
        except Exception:
            await websocket.close(code=4002)
            return

        if msg.get("type") != "ready":
            await websocket.close(code=4003)
            return

        meta = {
            "hostname": msg.get("hostname", "unknown"),
            "platform": msg.get("platform", "unknown"),
            "username": msg.get("username", "unknown"),
            "version": msg.get("version", "1.0.0"),
        }

        # Daftarkan koneksi
        mgr._connections[org_id] = websocket
        mgr._meta[org_id] = meta
        try:
            row = await pool.fetchrow(
                """INSERT INTO local_agent_connections (org_id, hostname, platform, username, agent_version)
                   VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                org_id, meta["hostname"], meta["platform"], meta["username"], meta["version"],
            )
            if row:
                mgr._conn_ids[org_id] = str(row["id"])
        except Exception:
            logger.warning("local_agent: gagal simpan koneksi ke DB")

        logger.info("Local agent terhubung: org=%s host=%s", org_id, meta["hostname"])
        await websocket.send_json({"type": "connected", "message": f"Terhubung ke BotNesia sebagai {meta['hostname']}"})

        try:
            while True:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "pong":
                    await mgr.update_last_seen(org_id, pool)
                elif msg_type == "result":
                    await mgr.handle_result(msg.get("command_id", ""), msg)
                elif msg_type == "approval_required":
                    # Agent meminta approval user lokal — teruskan sebagai event
                    await mgr.handle_result(msg.get("command_id", ""), {
                        "success": False,
                        "approval_required": True,
                        "message": msg.get("message", "Approval diperlukan di terminal lokal"),
                    })
                else:
                    logger.debug("local_agent unknown message type: %s", msg_type)

        except asyncio.TimeoutError:
            # Kirim ping, kalau tidak ada respons → putus
            try:
                await websocket.send_json({"type": "ping"})
                await asyncio.wait_for(websocket.receive_text(), timeout=10)
            except Exception:
                pass
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("local_agent ws error org=%s: %s", org_id, e)
        finally:
            await mgr.disconnect(org_id, pool)
            logger.info("Local agent terputus: org=%s", org_id)

    # ── REST: status ───────────────────────────────────────────────────────────

    @router.get("/local-agent/status")
    async def local_agent_status(
        user=Depends(require_permission("local_agent.manage")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        mgr = get_manager()
        connected = mgr.is_connected(org_id)
        meta = mgr.get_meta(org_id) if connected else {}
        last_conn = await pool.fetchrow(
            """SELECT hostname, platform, username, agent_version, connected_at, last_seen_at
               FROM local_agent_connections WHERE org_id=$1
               ORDER BY connected_at DESC LIMIT 1""",
            org_id,
        )
        return {
            "connected": connected,
            "meta": meta,
            "last_connection": dict(last_conn) if last_conn else None,
        }

    # ── REST: execute ──────────────────────────────────────────────────────────

    @router.post("/local-agent/execute")
    async def local_agent_execute(
        body: ExecuteRequest,
        user=Depends(require_permission("local_agent.execute")),
        pool=Depends(get_pool),
    ):
        """Kirim perintah ke local agent yang terhubung."""
        org_id = str(user["org_id"])
        mgr = get_manager()
        result = await mgr.execute(
            org_id, body.tool, body.args,
            initiated_by=str(user.get("user_id", "")),
            timeout=body.timeout,
            pool=pool,
        )
        return result

    # ── REST: history ──────────────────────────────────────────────────────────

    @router.get("/local-agent/history")
    async def local_agent_history(
        limit: int = 50,
        status: str | None = None,
        user=Depends(require_permission("local_agent.read")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        if status:
            rows = await pool.fetch(
                """SELECT id, tool, args, status, duration_ms, initiated_by, created_at, completed_at,
                          rejected_reason, approved_by, approved_at
                   FROM local_agent_commands WHERE org_id=$1 AND status=$2
                   ORDER BY created_at DESC LIMIT $3""",
                org_id, status, min(limit, 200),
            )
        else:
            rows = await pool.fetch(
                """SELECT id, tool, args, status, duration_ms, initiated_by, created_at, completed_at,
                          rejected_reason, approved_by, approved_at
                   FROM local_agent_commands WHERE org_id=$1
                   ORDER BY created_at DESC LIMIT $2""",
                org_id, min(limit, 200),
            )
        return {"commands": [dict(r) for r in rows], "total": len(rows)}

    # ── REST: approve / reject pending risky action ─────────────────────────────

    @router.post("/local-agent/commands/{command_id}/approve")
    async def local_agent_approve_command(
        command_id: str,
        user=Depends(require_permission("local_agent.execute")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        cmd = await pool.fetchrow(
            "SELECT * FROM local_agent_commands WHERE id=$1 AND org_id=$2", command_id, org_id,
        )
        if not cmd or cmd["status"] != "pending_approval":
            raise HTTPException(404, "Perintah tidak ditemukan atau tidak menunggu approval")

        mgr = get_manager()
        args = json.loads(cmd["args"] or "{}")
        approver = str(user["id"])
        try:
            result = await mgr.execute(
                org_id, cmd["tool"], args, initiated_by=approver, pool=pool,
            )
            new_status = "completed" if result.get("success") else "failed"
        except HTTPException as e:
            result = {"success": False, "error": e.detail}
            new_status = "failed"

        row = await pool.fetchrow(
            """UPDATE local_agent_commands
               SET status=$1, result=$2, approved_by=$3, approved_at=NOW(), completed_at=NOW()
               WHERE id=$4 AND org_id=$5
               RETURNING id, tool, args, status, result, initiated_by, created_at, completed_at""",
            new_status, json.dumps(result), approver, command_id, org_id,
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user.get("id"), actor_email=user.get("email"),
            action="update", resource_type="local_agent_command", resource_id=command_id,
            metadata={"approved": True, "tool": cmd["tool"]},
        )
        return dict(row)

    @router.post("/local-agent/commands/{command_id}/reject")
    async def local_agent_reject_command(
        command_id: str,
        body: LocalAgentRejectRequest,
        user=Depends(require_permission("local_agent.execute")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        approver = str(user["id"])
        row = await pool.fetchrow(
            """UPDATE local_agent_commands
               SET status='rejected', rejected_reason=$1, approved_by=$2, approved_at=NOW()
               WHERE id=$3 AND org_id=$4 AND status='pending_approval'
               RETURNING id, tool, args, status, initiated_by, created_at, rejected_reason""",
            body.reason, approver, command_id, org_id,
        )
        if not row:
            raise HTTPException(404, "Perintah tidak ditemukan atau tidak menunggu approval")
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user.get("id"), actor_email=user.get("email"),
            action="update", resource_type="local_agent_command", resource_id=command_id,
            metadata={"approved": False, "reason": body.reason},
        )
        return dict(row)

    # ── REST: disconnect ───────────────────────────────────────────────────────

    @router.post("/local-agent/disconnect")
    async def local_agent_disconnect(
        user=Depends(require_permission("local_agent.manage")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        mgr = get_manager()
        if not mgr.is_connected(org_id):
            raise HTTPException(404, "Tidak ada local agent yang terhubung")
        ws = mgr._connections.get(org_id)
        if ws:
            try:
                await ws.send_json({"type": "shutdown"})
                await ws.close()
            except Exception:
                pass
        await mgr.disconnect(org_id, pool)
        return {"success": True, "message": "Local agent diputus"}

    # ── Computer Agent: natural language → tool execution ──────────────────────

    @router.post("/computer-agent/run-local")
    async def computer_agent_run_local(
        body: ComputerAgentRequest,
        user=Depends(require_permission("local_agent.execute")),
        pool=Depends(get_pool),
    ):
        """Terima goal dalam bahasa Indonesia → rencanakan langkah → eksekusi via Local Agent."""
        org_id = str(user["org_id"])
        mgr = get_manager()

        if not mgr.is_connected(org_id):
            raise HTTPException(503, "Local Agent tidak terhubung. Jalankan botnesia_local_agent.py di komputer Anda terlebih dulu.")

        # 1. Rencanakan langkah via LLM (atau fallback ke plan sederhana)
        agent_meta = mgr.get_meta(org_id)
        if call_llm:
            steps = await _plan_with_llm(body.goal, call_llm, meta=agent_meta)
        else:
            steps = [
                {"tool": "get_info", "args": {}, "reason": "Cek info sistem"},
                {"tool": "list_dir", "args": {"path": "~/"}, "reason": "Lihat home directory"},
            ]

        # 2. Eksekusi setiap langkah
        results: list[dict] = []
        needs_approval: list[dict] = []
        _found_project_paths: list[str] = []  # track paths dari find_files untuk auto-scan

        async def _exec_step(tool: str, args: dict, reason: str) -> dict:
            if tool in RISKY_TOOLS:
                # Simpan sebagai baris pending_approval nyata di local_agent_commands
                # supaya benar-benar muncul di "Antrian Izin — Local Agent" -- sebelum
                # perbaikan ini, item needs_approval hanya dikembalikan di response HTTP
                # dan tidak pernah disimpan, jadi antrian yang ditunjuk di UI tidak
                # pernah menampilkannya (dead end).
                cmd_id = None
                try:
                    row = await pool.fetchrow(
                        """INSERT INTO local_agent_commands (org_id, connection_id, tool, args, status, initiated_by)
                           VALUES ($1,$2,$3,$4,'pending_approval',$5) RETURNING id""",
                        org_id, mgr._conn_ids.get(org_id), tool, json.dumps(args),
                        str(user["id"]),
                    )
                    if row:
                        cmd_id = str(row["id"])
                except Exception:
                    logger.warning("local_agent: gagal simpan pending_approval untuk org=%s tool=%s", org_id, tool)
                needs_approval.append({"id": cmd_id, "tool": tool, "args": args, "reason": reason})
                return {"tool": tool, "args": args, "reason": reason,
                        "status": "needs_approval", "command_id": cmd_id,
                        "message": f"Tool '{tool}' memerlukan approval sebelum dijalankan"}
            try:
                result = await mgr.execute(
                    org_id, tool, args,
                    initiated_by=str(user.get("user_id", "computer_agent")),
                    timeout=body.timeout, pool=pool,
                )
                # Cek apakah tool tidak dikenal di sisi agent
                if not result.get("success") and "tidak dikenal" in str(result.get("error", "")):
                    return {"tool": tool, "args": args, "reason": reason,
                            "status": "error",
                            "message": f"Tool '{tool}' belum tersedia. Restart botnesia_local_agent.py untuk mengaktifkan.",
                            "result": result}
                return {"tool": tool, "args": args, "reason": reason,
                        "status": "ok" if result.get("success") else "error",
                        "result": result}
            except HTTPException as e:
                return {"tool": tool, "args": args, "reason": reason, "status": "error", "message": e.detail}
            except Exception as e:
                return {"tool": tool, "args": args, "reason": reason, "status": "error", "message": str(e)}

        for step in steps:
            tool = step["tool"]
            args = step.get("args", {})
            reason = step.get("reason", "")

            # Jika LLM berencana scan_project dengan path hardcoded yang salah,
            # tapi kita punya path project dari find_files sebelumnya → pakai itu
            if tool in ("scan_project", "tree", "list_dir") and _found_project_paths:
                best_path = _found_project_paths[0]
                if args.get("path", "~/") in ("~/", "~", "/home/user", ""):
                    args = {**args, "path": best_path}

            entry = await _exec_step(tool, args, reason)
            results.append(entry)

            # Track direktori project dari find_files yang berhasil
            if tool == "find_files" and entry.get("status") == "ok":
                for match_path in (entry.get("result", {}).get("matches") or [])[:5]:
                    import os as _os
                    parent = _os.path.dirname(match_path)
                    if parent not in _found_project_paths and _os.path.isdir(parent):
                        _found_project_paths.append(parent)

        # 3. Auto-follow-up: jika ada project ditemukan tapi belum di-scan, scan otomatis
        scanned_paths = {r.get("args", {}).get("path") for r in results if r.get("tool") == "scan_project"}
        for proj_path in _found_project_paths[:2]:
            if proj_path not in scanned_paths:
                entry = await _exec_step("scan_project", {"path": proj_path}, f"Auto-scan project di {proj_path}")
                results.append(entry)

        return {
            "goal": body.goal,
            "steps": results,
            "needs_approval": needs_approval,
            "total_steps": len(results),
            "ok_steps": sum(1 for r in results if r["status"] == "ok"),
        }

    return router
