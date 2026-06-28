"""
bn_platform/local_agent_router.py — BotNesia Local Agent

Mengizinkan tenant menginstall agen lokal di PC mereka sehingga AI BotNesia
bisa mengakses file, terminal, dan browser di komputer user — seperti Claude Code.

Arsitektur:
  User chat → BotNesia cloud (AI reasoning) → WebSocket → Local Agent (PC user)
                                                             ├── file read/write
                                                             ├── terminal shell
                                                             └── browser lokal

WebSocket endpoint: WS /api/local-agent/ws?token=<jwt>
REST endpoints:
  GET  /api/local-agent/status          — apakah local agent terhubung
  POST /api/local-agent/execute         — kirim perintah ke local agent
  GET  /api/local-agent/history         — riwayat perintah
  POST /api/local-agent/disconnect      — putus koneksi
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
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_local_agent_cmd_org ON local_agent_commands(org_id, created_at DESC);
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
    tool: str = Field(description="read_file | write_file | list_dir | run_command | find_files | get_info")
    args: dict = Field(default_factory=dict)
    timeout: int = Field(default=30, ge=5, le=120)


# ─── Router factory ───────────────────────────────────────────────────────────

def build_local_agent_router(*, get_pool, get_current_user, require_permission, decode_token):
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

        # Validasi token
        org_id: str | None = None
        try:
            payload = decode_token(token)
            org_id = str(payload["org"])
        except Exception:
            await websocket.close(code=4001, reason="Token tidak valid")
            return

        # Tunggu pesan "ready" dari agent
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            msg = json.loads(raw)
        except Exception:
            await websocket.close(code=4002, reason="Handshake timeout")
            return

        if msg.get("type") != "ready":
            await websocket.close(code=4003, reason="Expected ready message")
            return

        meta = {
            "hostname": msg.get("hostname", "unknown"),
            "platform": msg.get("platform", "unknown"),
            "username": msg.get("username", "unknown"),
            "version": msg.get("version", "1.0.0"),
        }

        # Sudah accept di atas, perlu koneksi yang sudah accept
        # Daftarkan koneksi (tanpa accept lagi)
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
        user=Depends(require_permission("local_agent.read")),
        pool=Depends(get_pool),
    ):
        org_id = str(user["org_id"])
        rows = await pool.fetch(
            """SELECT id, tool, args, status, duration_ms, initiated_by, created_at, completed_at
               FROM local_agent_commands WHERE org_id=$1
               ORDER BY created_at DESC LIMIT $2""",
            org_id, min(limit, 200),
        )
        return {"commands": [dict(r) for r in rows], "total": len(rows)}

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

    return router
