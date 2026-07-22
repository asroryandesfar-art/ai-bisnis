"""
terminal_service.py — Terminal Execution Service (AI Agent Platform).

Eksekusi perintah shell dengan permission gates dan sandboxing.

Capabilities:
  run shell commands, git, docker, npm/pnpm/bun, python/uv,
  cargo, go, node, build/deploy, install packages, run tests,
  lint/format, read logs, kill/monitor process

Safety model:
  - Semua command butuh izin RUN_TERMINAL
  - Command malformed (control-char/NUL, >16KB) DITOLAK keras (tak dieksekusi)
  - Command BERBAHAYA butuh approval: daftar substring + lapis regex robust
    (rm -fr/-Rf, fork bomb, curl|sh, tulis ke /dev/sdX, mkfs/fdisk, shutdown,
    chmod/chown -R /) — reversible via env TERMINAL_STRICT_GUARDS=off
  - Timeout wajib (default 60s, maks 300s)
  - Working directory di-jail ke allowed_base_dir BILA di-set (opt-in; default
    tanpa jail = perilaku lama). Bila di-set, cwd di luar base ditolak.
  - Environment variable difilter (tidak ada secret dari host env yang bocor)
  - Output dibatasi 50KB

Setiap eksekusi menghasilkan baris di agent_audit_log:
  {stdout, stderr, exit_code, command, duration_ms}
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

import asyncpg

from audit_logger import log_action
from permission_manager import Permission, PermissionManager

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300
_MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB
_MAX_COMMAND_CHARS = 16 * 1024  # 16 KB — command lebih panjang ditolak (abuse guard)

# Karakter kontrol non-printable (kecuali tab/LF/CR) & NUL → command malformed →
# DITOLAK keras (tak dieksekusi walau approval): sering dipakai menyelundupkan
# perintah / merusak logging/audit.
_ALLOWED_CONTROL = {9, 10, 13}
_CONTROL_CHARS = (set(range(0, 32)) | {127}) - _ALLOWED_CONTROL

# Whitelist env vars yang aman diteruskan ke subprocess
_SAFE_ENV_VARS = {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
    "PYTHONPATH", "GOPATH", "GOROOT", "CARGO_HOME", "RUSTUP_HOME",
    "NODE_PATH", "NVM_DIR",
    "VIRTUAL_ENV", "CONDA_PREFIX",
}

# Command yang SELALU perlu approval (berbahaya) — daftar substring (backward-compat).
_ALWAYS_REQUIRE_APPROVAL = [
    "rm -rf", "rm -r /", "rmdir /", "dd ", "mkfs", "fdisk",
    "format ", "del /", "shutdown", "reboot", "halt",
    "chmod 777 /", "chown -R root",
    "DROP DATABASE", "DROP TABLE", "TRUNCATE",
    "kubectl delete", "docker rm -f",
]

# Lapis kedua (robust): pola regex yang sulit di-bypass oleh varian spasi/flag.
# Menutup lubang substring: `rm -fr`, `rm  -Rf`, fork bomb, pipe unduhan→shell,
# tulis ke device blok, tool disk destruktif, kontrol daya, chmod/chown -R pada /.
# Reversible via env TERMINAL_STRICT_GUARDS=off (kembali ke substring saja).
_DANGEROUS_REGEX = [
    (re.compile(r":\s*\(\s*\)\s*\{.*[|&].*\}\s*;\s*:"),                         "fork bomb"),
    (re.compile(r"\brm\b[^\n]*\s-\w*r\w*f|\brm\b[^\n]*\s-\w*f\w*r", re.I),       "rm rekursif+force"),
    (re.compile(r"\brm\b\s+(?:-\S+\s+)*(?:/|~|\*|\$HOME)(?:\s|$)"),             "rm target sensitif (/, ~, *)"),
    (re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python\d?)\b", re.I), "pipe unduhan ke shell"),
    (re.compile(r">\s*/dev/(?:sd|nvme|hd|mmcblk|vd)\w*", re.I),                  "tulis ke device blok"),
    (re.compile(r"\b(?:mkfs\w*|fdisk|parted|wipefs)\b", re.I),                   "tool disk destruktif"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b|\binit\s+[06]\b", re.I), "power/kontrol sistem"),
    (re.compile(r"\b(?:chmod|chown)\b\s+-\w*R\w*\b[^\n]*\s/(?:\s|$)", re.I), "chmod/chown rekursif pada /"),
]


def _strict_guards_enabled() -> bool:
    return os.environ.get("TERMINAL_STRICT_GUARDS", "on").strip().lower() not in (
        "off", "0", "false", "no", "disabled")


def _needs_approval(command: str) -> tuple[bool, str]:
    cmd = command.strip()
    for pattern in _ALWAYS_REQUIRE_APPROVAL:
        if pattern.lower() in cmd.lower():
            return True, f"Command mengandung pola berbahaya: '{pattern}'"
    if _strict_guards_enabled():
        for rx, label in _DANGEROUS_REGEX:
            if rx.search(cmd):
                return True, f"Command mengandung pola berbahaya: {label}"
    return False, ""


def _reject_reason(command: str) -> str | None:
    """Command malformed yang DITOLAK keras (tak dieksekusi walau approval)."""
    if len(command) > _MAX_COMMAND_CHARS:
        return f"Command melebihi batas {_MAX_COMMAND_CHARS} karakter."
    if any((ord(ch) in _CONTROL_CHARS) for ch in command):
        return "Command mengandung karakter kontrol/NUL yang tidak diizinkan."
    return None


def _jail_cwd(effective_cwd: str | None, allowed_base: str | None) -> tuple[str | None, str | None]:
    """Pastikan cwd berada di dalam allowed_base (bila di-set). Default (base None)
    → tak ada jail (perilaku lama byte-identik). Mencegah path-traversal keluar base."""
    if not allowed_base:
        return effective_cwd, None
    base = os.path.realpath(allowed_base)
    target = os.path.realpath(effective_cwd) if effective_cwd else base
    if target == base or target.startswith(base + os.sep):
        return target, None
    return None, f"Working directory di luar area yang diizinkan ({allowed_base})."


def _build_safe_env(extra: dict | None = None) -> dict[str, str]:
    """Bangun env yang aman: hanya SAFE_ENV_VARS dari host + extra dari caller."""
    safe = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_VARS}
    if extra:
        safe.update({k: str(v) for k, v in extra.items()})
    return safe


class TerminalResult:
    def __init__(self, command: str, stdout: str, stderr: str, exit_code: int, duration_ms: int):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.success = exit_code == 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
        }


class TerminalService:
    """
    Service untuk eksekusi shell command dengan permission gate.

    Setiap instance terikat ke satu org dan optional working directory.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        org_id: str,
        permission_manager: PermissionManager,
        *,
        agent_name: str = "terminal_agent",
        working_dir: str | None = None,
        allowed_base_dir: str | None = None,
    ):
        self._pool = pool
        self._org_id = org_id
        self._pm = permission_manager
        self._agent_name = agent_name
        self._working_dir = working_dir
        # Jail direktori kerja (opt-in). Bila di-set, semua cwd WAJIB di dalamnya
        # (mencegah agen keluar ke path sistem). Default None = tanpa jail (lama).
        self._allowed_base_dir = allowed_base_dir
        self._history: list[dict] = []  # in-memory session history

    async def execute(
        self,
        command: str,
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        cwd: str | None = None,
        env: dict | None = None,
        approval_granted: bool = False,
    ) -> dict:
        """
        Eksekusi shell command.

        Jika command BERBAHAYA dan approval_granted=False:
          → kembalikan status pending_approval, TIDAK dieksekusi.

        Returns dict dengan: success, command, stdout, stderr, exit_code,
          duration_ms, requires_approval (jika belum di-approve)
        """
        command = (command or "").strip()
        if not command:
            return {"success": False, "error": "Command kosong"}

        # ── 0. Tolak keras command malformed (control-char/NUL/terlalu panjang) ─
        reject = _reject_reason(command)
        if reject:
            return {"success": False, "error": reject, "blocked": True, "command": command[:200]}

        # ── 1. Cek permission ──────────────────────────────────────────
        perm = await self._pm.check(Permission.RUN_TERMINAL, resource=command[:100])
        if not perm["allowed"]:
            return {
                "success": False,
                "error": "Izin menjalankan terminal belum diberikan.",
                "requires_permission": "run_terminal",
                "requires_approval": True,
                "command": command,
            }

        # ── 2. Cek apakah butuh approval tambahan ─────────────────────
        needs_appr, reason = _needs_approval(command)
        if needs_appr and not approval_granted:
            log_id = await log_action(
                self._pool, org_id=self._org_id, agent_name=self._agent_name,
                action_type="terminal_execute", target=command[:500],
                status="pending_approval",
                permission_grant_id=perm.get("grant_id"),
                metadata={"reason": reason},
            )
            return {
                "success": False,
                "status": "pending_approval",
                "requires_approval": True,
                "danger_reason": reason,
                "command": command,
                "log_id": log_id,
                "message": f"Command ini memerlukan approval eksplisit: {reason}",
            }

        # ── 3. Klamp timeout + tegakkan jail cwd (bila di-set) ────────
        timeout = max(1, min(timeout, _MAX_TIMEOUT))
        effective_cwd, jail_err = _jail_cwd(cwd or self._working_dir, self._allowed_base_dir)
        if jail_err:
            await log_action(
                self._pool, org_id=self._org_id, agent_name=self._agent_name,
                action_type="terminal_execute", target=command[:500],
                status="blocked", error=jail_err,
            )
            return {"success": False, "error": jail_err, "blocked": True, "command": command}

        # ── 4. Eksekusi ───────────────────────────────────────────────
        started = time.perf_counter()
        log_id = await log_action(
            self._pool, org_id=self._org_id, agent_name=self._agent_name,
            action_type="terminal_execute", target=command[:500],
            status="running",
            permission_grant_id=perm.get("grant_id"),
        )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=effective_cwd,
                env=_build_safe_env(env),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                duration_ms = int((time.perf_counter() - started) * 1000)
                await log_action(
                    self._pool, org_id=self._org_id, agent_name=self._agent_name,
                    action_type="terminal_execute", target=command[:500],
                    status="failed", duration_ms=duration_ms,
                    error=f"Timeout setelah {timeout}s",
                )
                return {
                    "success": False, "command": command,
                    "error": f"Command timeout setelah {timeout} detik",
                    "exit_code": -1, "stdout": "", "stderr": "",
                    "duration_ms": duration_ms,
                }

            duration_ms = int((time.perf_counter() - started) * 1000)
            stdout = stdout_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = stderr_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

            # ── 5. Simpan ke history ───────────────────────────────────
            entry = {
                "command": command, "exit_code": exit_code,
                "stdout_preview": stdout[:500], "duration_ms": duration_ms,
            }
            self._history.append(entry)
            if len(self._history) > 100:
                self._history.pop(0)

            status = "completed" if exit_code == 0 else "failed"
            await log_action(
                self._pool, org_id=self._org_id, agent_name=self._agent_name,
                action_type="terminal_execute", target=command[:500],
                status=status, duration_ms=duration_ms,
                permission_grant_id=perm.get("grant_id"),
                metadata={"exit_code": exit_code, "stdout_len": len(stdout), "stderr_len": len(stderr)},
                error=stderr[:500] if exit_code != 0 else None,
            )

            result = TerminalResult(command, stdout, stderr, exit_code, duration_ms)
            return result.to_dict()

        except Exception as e:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await log_action(
                self._pool, org_id=self._org_id, agent_name=self._agent_name,
                action_type="terminal_execute", target=command[:500],
                status="failed", duration_ms=duration_ms, error=str(e),
            )
            return {"success": False, "command": command, "error": str(e), "exit_code": -1, "stdout": "", "stderr": ""}

    async def git(self, args: str, *, cwd: str | None = None) -> dict:
        """Shortcut untuk git command."""
        return await self.execute(f"git {args}", cwd=cwd)

    async def run_python(self, script_path: str, *, args: str = "", cwd: str | None = None) -> dict:
        """Jalankan script Python."""
        return await self.execute(f"python {script_path} {args}".strip(), cwd=cwd, timeout=120)

    async def npm(self, args: str, *, cwd: str | None = None) -> dict:
        return await self.execute(f"npm {args}", cwd=cwd, timeout=120)

    async def pnpm(self, args: str, *, cwd: str | None = None) -> dict:
        return await self.execute(f"pnpm {args}", cwd=cwd, timeout=120)

    async def docker(self, args: str, *, approval_granted: bool = False) -> dict:
        return await self.execute(f"docker {args}", approval_granted=approval_granted, timeout=180)

    async def read_log(self, log_path: str, *, lines: int = 100) -> dict:
        """Baca N baris terakhir dari file log."""
        return await self.execute(f"tail -n {lines} {shlex.quote(log_path)}")

    async def kill_process(self, pid: int, *, approval_granted: bool = False) -> dict:
        """Kill process by PID. Butuh approval."""
        return await self.execute(f"kill {pid}", approval_granted=approval_granted)

    async def list_processes(self, *, filter_name: str = "") -> dict:
        if filter_name:
            return await self.execute(f"ps aux | grep {shlex.quote(filter_name)}")
        return await self.execute("ps aux")

    def get_history(self) -> list[dict]:
        """Return session terminal history (in-memory)."""
        return list(self._history)
