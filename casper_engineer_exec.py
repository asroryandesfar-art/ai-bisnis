"""
casper_engineer_exec.py — jembatan Casper Engineer -> Local Agent (Phase 2a).

Membangun `repo_context` OTOMATIS dari repo di mesin user lewat Local Agent yang
sudah ada (bn_platform/local_agent_router.LocalAgentManager). HANYA tool READ-ONLY
(scan_project + tree) di slice ini — tidak menulis/menjalankan perintah. Eksekusi
tulis (write_file/run_command/testing/deploy) adalah slice berikutnya di belakang
approval + command-guard yang sudah ada.

`execute` diinjeksi (LocalAgentManager.execute) supaya bisa diuji tanpa perangkat.
"""
from __future__ import annotations

from typing import Awaitable, Callable

# Batas ukuran konteks supaya tidak meledakkan prompt LLM.
_MAX_FILE_PREVIEW = 1500
_MAX_TREE = 3000
_MAX_CONTEXT = 12000

ExecuteFn = Callable[..., Awaitable[dict]]


async def gather_repo_context(
    execute: ExecuteFn, org_id: str, pool, *,
    device_id: str | None = None, path: str = ".", timeout: int = 30,
) -> tuple[str, dict]:
    """Rakit repo_context dari Local Agent (read-only). Return (context, meta).

    Tidak menelan HTTPException "perangkat tidak terhubung" — dibiarkan naik agar
    caller bisa memberi pesan jelas ke user. Kegagalan tool per-item (mis. path
    salah) tidak fatal: bagian itu dilewati."""
    parts: list[str] = []
    meta: dict = {"scanned": False, "project_type": None, "total_files": None, "path": path}

    scan = await execute(org_id, "scan_project", {"path": path},
                         device_id=device_id, initiated_by="casper_engineer", timeout=timeout, pool=pool)
    if isinstance(scan, dict) and scan.get("success"):
        meta.update(scanned=True, project_type=scan.get("project_type"), total_files=scan.get("total_files"))
        parts.append(f"PROJECT TYPE: {scan.get('project_type', 'unknown')}")
        if scan.get("total_files") is not None:
            parts.append(f"TOTAL FILES: {scan.get('total_files')}")
        if scan.get("ext_count"):
            top = sorted(scan["ext_count"].items(), key=lambda kv: kv[1], reverse=True)[:8]
            parts.append("FILE TYPES: " + ", ".join(f"{ext or '(none)'}={n}" for ext, n in top))
        for fname, info in (scan.get("found_files") or {}).items():
            preview = str((info or {}).get("preview") or "")[:_MAX_FILE_PREVIEW]
            if preview:
                parts.append(f"\n--- {fname} ---\n{preview}")

    tree = await execute(org_id, "tree", {"path": path},
                        device_id=device_id, initiated_by="casper_engineer", timeout=timeout, pool=pool)
    if isinstance(tree, dict) and tree.get("success") and tree.get("tree"):
        parts.append(f"\n--- STRUCTURE ---\n{str(tree['tree'])[:_MAX_TREE]}")

    context = "\n".join(parts)[:_MAX_CONTEXT]
    return context, meta
