"""
permission_manager.py — Enterprise Permission Manager (AI Agent Platform).

Model permission bertingkat untuk semua aksi agent: Read Files, Write Files,
Delete Files, Run Terminal, Browser Access, GitHub Access, Database Access,
Email Access, API Access, Clipboard, Camera, Microphone, Screen.

Grant modes:
  allow_once   — izin satu kali, hangus setelah dipakai
  allow_always — izin permanen sampai dicabut
  deny         — ditolak permanen

Semua keputusan di-persist ke tabel `agent_permission_grants` dan dicatat
ke `audit_logger.py`. Tidak ada eksekusi otomatis — modul ini murni
policy enforcement, bukan executor.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    READ_FILES       = "read_files"
    WRITE_FILES      = "write_files"
    DELETE_FILES     = "delete_files"
    RUN_TERMINAL     = "run_terminal"
    BROWSER_ACCESS   = "browser_access"
    BROWSER_WRITE    = "browser_write"
    GITHUB_ACCESS    = "github_access"
    DATABASE_ACCESS  = "database_access"
    EMAIL_ACCESS     = "email_access"
    API_ACCESS       = "api_access"
    CLIPBOARD        = "clipboard"
    CAMERA           = "camera"
    MICROPHONE       = "microphone"
    SCREEN           = "screen"


class GrantMode(str, Enum):
    ALLOW_ONCE   = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY         = "deny"


_DANGEROUS_PERMISSIONS = {
    Permission.DELETE_FILES,
    Permission.RUN_TERMINAL,
    Permission.EMAIL_ACCESS,
    Permission.DATABASE_ACCESS,
}

_TERMINAL_DANGEROUS_PATTERNS = [
    "rm -rf", "rm -r /", "dd if=", "mkfs", "format",
    ":(){:|:&};:", "chmod 777", "sudo rm", ">/dev/",
    "wget.*|.*sh", "curl.*|.*sh", "base64 -d.*|.*sh",
]


class PermissionManager:
    """Singleton-per-org permission cache dengan fallback ke DB."""

    def __init__(self, pool: asyncpg.Pool, org_id: str):
        self._pool = pool
        self._org_id = org_id
        self._cache: dict[str, dict] = {}

    async def check(self, permission: Permission, *, resource: str = "", context: str = "") -> dict:
        """
        Cek apakah permission diizinkan.

        Returns:
          {"allowed": True/False, "mode": "allow_once"|"allow_always"|"deny"|"not_set",
           "grant_id": str|None}
        """
        key = f"{permission.value}:{resource}"

        # Cek DB dulu
        try:
            row = await self._pool.fetchrow(
                """SELECT id, grant_mode, used_at, expires_at
                   FROM agent_permission_grants
                   WHERE org_id=$1 AND permission=$2
                     AND (resource=$3 OR resource='*')
                     AND revoked_at IS NULL
                   ORDER BY granted_at DESC LIMIT 1""",
                self._org_id, permission.value, resource,
            )
        except Exception:
            logger.debug("permission_manager: tabel agent_permission_grants belum ada, default deny")
            return {"allowed": False, "mode": "not_set", "grant_id": None}

        if not row:
            return {"allowed": False, "mode": "not_set", "grant_id": None}

        grant_id = str(row["id"])
        mode = row["grant_mode"]
        expires_at = row["expires_at"]

        if expires_at and expires_at < datetime.now(timezone.utc):
            return {"allowed": False, "mode": "expired", "grant_id": grant_id}

        if mode == GrantMode.DENY:
            return {"allowed": False, "mode": "deny", "grant_id": grant_id}

        if mode == GrantMode.ALLOW_ONCE:
            if row["used_at"] is not None:
                return {"allowed": False, "mode": "used", "grant_id": grant_id}
            # Mark as used
            await self._pool.execute(
                "UPDATE agent_permission_grants SET used_at=NOW() WHERE id=$1",
                row["id"],
            )
            return {"allowed": True, "mode": "allow_once", "grant_id": grant_id}

        # allow_always
        return {"allowed": True, "mode": "allow_always", "grant_id": grant_id}

    async def grant(
        self,
        permission: Permission,
        mode: GrantMode,
        *,
        resource: str = "*",
        granted_by: str = "user",
        expires_at: datetime | None = None,
        context: str = "",
    ) -> str:
        """Buat grant baru. Return grant_id."""
        try:
            row = await self._pool.fetchrow(
                """INSERT INTO agent_permission_grants
                   (org_id, permission, grant_mode, resource, granted_by, context, expires_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   RETURNING id""",
                self._org_id, permission.value, mode.value, resource,
                granted_by, context, expires_at,
            )
            return str(row["id"])
        except Exception as e:
            logger.warning("permission_manager.grant gagal: %s", e)
            return ""

    async def revoke(self, permission: Permission, *, resource: str = "*") -> int:
        """Cabut semua grant aktif untuk permission+resource ini. Return jumlah baris yang dicabut."""
        try:
            result = await self._pool.execute(
                """UPDATE agent_permission_grants
                   SET revoked_at=NOW()
                   WHERE org_id=$1 AND permission=$2 AND resource=$3
                     AND revoked_at IS NULL""",
                self._org_id, permission.value, resource,
            )
            return int((result or "0").split()[-1])
        except Exception as e:
            logger.warning("permission_manager.revoke gagal: %s", e)
            return 0

    async def list_grants(self) -> list[dict]:
        """Daftar semua grant aktif untuk org ini."""
        try:
            rows = await self._pool.fetch(
                """SELECT id, permission, grant_mode, resource, granted_by,
                          context, granted_at, used_at, expires_at, revoked_at
                   FROM agent_permission_grants
                   WHERE org_id=$1 AND revoked_at IS NULL
                   ORDER BY granted_at DESC""",
                self._org_id,
            )
            return [dict(r) for r in rows]
        except Exception:
            return []

    def is_dangerous(self, permission: Permission) -> bool:
        return permission in _DANGEROUS_PERMISSIONS

    @staticmethod
    def is_dangerous_command(command: str) -> tuple[bool, str]:
        """Cek apakah shell command termasuk pola berbahaya."""
        cmd = (command or "").strip().lower()
        for pattern in _TERMINAL_DANGEROUS_PATTERNS:
            if pattern.lower() in cmd:
                return True, f"Pola berbahaya terdeteksi: '{pattern}'"
        return False, ""

    def required_permission(self, action_type: str) -> Permission:
        """Map action type ke permission yang dibutuhkan."""
        mapping = {
            "file_read": Permission.READ_FILES,
            "file_write": Permission.WRITE_FILES,
            "file_delete": Permission.DELETE_FILES,
            "file_edit": Permission.WRITE_FILES,
            "file_rename": Permission.WRITE_FILES,
            "file_move": Permission.WRITE_FILES,
            "file_copy": Permission.READ_FILES,
            "terminal": Permission.RUN_TERMINAL,
            "browser_read": Permission.BROWSER_ACCESS,
            "browser_write": Permission.BROWSER_WRITE,
            "github": Permission.GITHUB_ACCESS,
            "database": Permission.DATABASE_ACCESS,
            "email": Permission.EMAIL_ACCESS,
            "api": Permission.API_ACCESS,
            "screen": Permission.SCREEN,
        }
        return mapping.get(action_type, Permission.API_ACCESS)


# ─── Schema DDL (append ke schema_platform.sql saat init) ─────────────────────

SCHEMA_SQL = """
-- Agent Permission Grants (enterprise permission model)
CREATE TABLE IF NOT EXISTS agent_permission_grants (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    permission    TEXT NOT NULL,
    grant_mode    TEXT NOT NULL CHECK (grant_mode IN ('allow_once','allow_always','deny')),
    resource      TEXT NOT NULL DEFAULT '*',
    granted_by    TEXT NOT NULL DEFAULT 'user',
    context       TEXT,
    granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at       TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_permission_grants_org
    ON agent_permission_grants(org_id, permission, revoked_at);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Pastikan tabel agent_permission_grants ada (idempotent)."""
    try:
        await pool.execute(SCHEMA_SQL)
    except Exception as e:
        logger.warning("permission_manager.ensure_schema: %s", e)
