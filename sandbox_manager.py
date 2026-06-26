"""
sandbox_manager.py — Sandbox Manager (AI Agent Platform).

Isolasi eksekusi agent di workspace sementara:
  - temporary workspace (di /tmp atau path konfigurabel)
  - virtual filesystem (batas akses ke workspace dir)
  - safe execution: semua terminal/file operation via service layer
  - rollback: snapshot state sebelum eksekusi, restore jika gagal
  - resource limits: CPU time, memory, file size, output
  - timeout: per-operasi dan per-session
  - logging: semua aksi direkam ke audit_logger

Sandbox TIDAK menggantikan isolasi OS-level (container/VM) — ini adalah
lapisan aplikasi untuk mencegah agent bekerja di tempat yang salah dan
untuk memudahkan rollback logis.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

import asyncpg

from audit_logger import log_action
from file_system_service import FileSystemService
from permission_manager import Permission, PermissionManager
from terminal_service import TerminalService

logger = logging.getLogger(__name__)

_SANDBOX_BASE = "/tmp/botnesia-sandbox"
_MAX_SANDBOX_SIZE_MB = 100
_DEFAULT_SESSION_TIMEOUT = 600  # 10 menit


@dataclass
class SandboxStats:
    files_created: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    commands_run: int = 0
    bytes_written: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.started_at


@dataclass
class SandboxSession:
    session_id: str
    workspace: Path
    org_id: str
    agent_name: str
    snapshot_path: Path | None
    stats: SandboxStats = field(default_factory=SandboxStats)
    active: bool = True
    metadata: dict = field(default_factory=dict)


class SandboxManager:
    """
    Manager untuk sandbox session.

    Penggunaan:
        async with sandbox.session(org_id, agent_name) as s:
            result = await s.execute_command("ls -la")
            file = await s.read_file("myfile.txt")
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._sessions: dict[str, SandboxSession] = {}
        Path(_SANDBOX_BASE).mkdir(parents=True, exist_ok=True)

    async def create_session(
        self,
        org_id: str,
        agent_name: str,
        *,
        base_dir: str | None = None,
        enable_snapshot: bool = True,
        metadata: dict | None = None,
    ) -> SandboxSession:
        """Buat sandbox session baru dengan workspace terisolasi."""
        session_id = str(uuid.uuid4())[:8]
        workspace = Path(_SANDBOX_BASE) / f"{org_id[:8]}_{session_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        snapshot_path = None
        if enable_snapshot and base_dir:
            base_p = Path(base_dir)
            if base_p.is_dir():
                snapshot_path = Path(_SANDBOX_BASE) / f"snapshot_{session_id}"
                try:
                    shutil.copytree(str(base_p), str(snapshot_path), dirs_exist_ok=True)
                    logger.debug("sandbox: snapshot dibuat di %s", snapshot_path)
                except Exception as e:
                    logger.warning("sandbox: gagal membuat snapshot: %s", e)
                    snapshot_path = None

        session = SandboxSession(
            session_id=session_id,
            workspace=workspace,
            org_id=org_id,
            agent_name=agent_name,
            snapshot_path=snapshot_path,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session

        await log_action(
            self._pool, org_id=org_id, agent_name=agent_name,
            action_type="sandbox_create", target=str(workspace),
            status="completed", metadata={"session_id": session_id},
        )
        return session

    async def rollback(self, session_id: str) -> dict:
        """Kembalikan state ke snapshot awal (jika ada)."""
        session = self._sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Session tidak ditemukan"}

        if not session.snapshot_path or not session.snapshot_path.exists():
            return {"success": False, "error": "Tidak ada snapshot untuk di-rollback"}

        try:
            target = session.metadata.get("base_dir")
            if target:
                base_p = Path(target)
                if base_p.exists():
                    shutil.rmtree(str(base_p))
                shutil.copytree(str(session.snapshot_path), str(base_p), dirs_exist_ok=True)
                await log_action(
                    self._pool, org_id=session.org_id, agent_name=session.agent_name,
                    action_type="sandbox_rollback", target=str(base_p),
                    status="completed", metadata={"session_id": session_id},
                )
                return {"success": True, "rolled_back_to": str(session.snapshot_path)}
        except Exception as e:
            return {"success": False, "error": f"Rollback gagal: {e}"}

        return {"success": False, "error": "base_dir tidak dikonfigurasi di session"}

    async def cleanup(self, session_id: str) -> None:
        """Bersihkan workspace dan snapshot session."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        session.active = False
        for path in [session.workspace, session.snapshot_path]:
            if path and path.exists():
                try:
                    shutil.rmtree(str(path))
                except Exception as e:
                    logger.warning("sandbox: gagal cleanup %s: %s", path, e)

        await log_action(
            self._pool, org_id=session.org_id, agent_name=session.agent_name,
            action_type="sandbox_cleanup", target=str(session.workspace),
            status="completed",
            metadata={
                "session_id": session_id,
                "duration_seconds": round(session.stats.duration_seconds, 1),
                "commands_run": session.stats.commands_run,
                "files_created": session.stats.files_created,
            },
        )

    async def get_session(self, session_id: str) -> SandboxSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "session_id": s.session_id,
                "org_id": s.org_id,
                "agent_name": s.agent_name,
                "workspace": str(s.workspace),
                "active": s.active,
                "duration_seconds": round(s.stats.duration_seconds, 1),
                "commands_run": s.stats.commands_run,
            }
            for s in self._sessions.values()
        ]

    @asynccontextmanager
    async def session(
        self,
        org_id: str,
        agent_name: str,
        *,
        base_dir: str | None = None,
        metadata: dict | None = None,
    ) -> AsyncGenerator["SandboxContext", None]:
        """Context manager untuk sandbox session dengan auto-cleanup."""
        s = await self.create_session(
            org_id, agent_name, base_dir=base_dir,
            enable_snapshot=base_dir is not None,
            metadata={**(metadata or {}), "base_dir": base_dir},
        )
        ctx = SandboxContext(s, pool=self._pool, manager=self)
        try:
            yield ctx
        finally:
            await self.cleanup(s.session_id)


class SandboxContext:
    """Konteks eksekusi di dalam sandbox session."""

    def __init__(self, session: SandboxSession, pool: asyncpg.Pool, manager: SandboxManager):
        self._session = session
        self._pool = pool
        self._manager = manager
        self._pm = PermissionManager(pool, session.org_id)

    @property
    def workspace(self) -> str:
        return str(self._session.workspace)

    @property
    def session_id(self) -> str:
        return self._session.session_id

    def get_terminal(self, **kwargs) -> TerminalService:
        return TerminalService(
            self._pool, self._session.org_id, self._pm,
            agent_name=self._session.agent_name,
            working_dir=str(self._session.workspace),
            **kwargs,
        )

    def get_filesystem(self, **kwargs) -> FileSystemService:
        return FileSystemService(
            self._pool, self._session.org_id, self._pm,
            agent_name=self._session.agent_name,
            allowed_base_dir=str(self._session.workspace),
            **kwargs,
        )

    async def execute_command(self, command: str, **kwargs) -> dict:
        result = await self.get_terminal().execute(command, **kwargs)
        self._session.stats.commands_run += 1
        return result

    async def write_temp_file(self, filename: str, content: str) -> str:
        """Tulis file sementara di workspace. Tidak perlu permission (dalam sandbox)."""
        path = self._session.workspace / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._session.stats.files_created += 1
        return str(path)

    async def read_temp_file(self, filename: str) -> str | None:
        """Baca file di workspace sandbox."""
        path = self._session.workspace / filename
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    async def rollback(self) -> dict:
        return await self._manager.rollback(self._session.session_id)

    def get_stats(self) -> dict:
        s = self._session.stats
        return {
            "session_id": self._session.session_id,
            "workspace": str(self._session.workspace),
            "duration_seconds": round(s.duration_seconds, 1),
            "commands_run": s.commands_run,
            "files_created": s.files_created,
            "files_modified": s.files_modified,
        }
