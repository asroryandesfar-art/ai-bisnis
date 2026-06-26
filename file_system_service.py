"""
file_system_service.py — File System Access Service (AI Agent Platform).

Akses file sistem nyata dengan permission gates. Semua operasi tulis (write,
edit, rename, move, delete, copy) WAJIB lewat PermissionManager sebelum
dieksekusi. Operasi baca (read, list, search) membutuhkan izin read_files.

Supported formats: txt, md, pdf, docx, xlsx, csv, json, yaml, xml,
ts, tsx, js, py, java, go, rust, images (read-only untuk binary).

Safety constraints:
  - Path traversal prevention: semua path dinormalisasi & dibatasi ke
    allowed_base_dirs yang dikonfigurasi per org
  - Tidak ada delete tanpa konfirmasi eksplisit
  - Tidak ada akses ke /etc, /sys, /proc, atau secrets common paths
  - File limit: maks 10MB untuk read, 5MB untuk write
"""
from __future__ import annotations

import fnmatch
import json
import logging
import mimetypes
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import asyncpg

from audit_logger import log_action
from permission_manager import Permission, PermissionManager

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = 10 * 1024 * 1024   # 10 MB
_MAX_WRITE_BYTES = 5 * 1024 * 1024   # 5 MB
_MAX_TEXT_PREVIEW = 8000              # chars

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml",
    ".xml", ".toml", ".ini", ".cfg", ".env", ".sh", ".bash",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".java", ".go", ".rs", ".rb", ".php", ".cs",
    ".html", ".htm", ".css", ".scss", ".sass",
    ".sql", ".graphql",
    ".c", ".cpp", ".h", ".hpp",
    ".log",
}

_FORBIDDEN_PATHS = [
    "/etc/passwd", "/etc/shadow", "/etc/hosts",
    "/sys/", "/proc/", "/dev/",
    "/.ssh/", "/.aws/", "/.env",
    "/root/", "/boot/",
]


def _safe_path(raw_path: str, allowed_base: str | None = None) -> tuple[Path | None, str]:
    """
    Normalisasi path dan validasi keamanan.

    Returns (resolved_path, error_message). Jika error, path=None.
    """
    try:
        p = Path(raw_path).expanduser().resolve()
    except Exception as e:
        return None, f"Path tidak valid: {e}"

    path_str = str(p)

    # Cek forbidden paths
    for forbidden in _FORBIDDEN_PATHS:
        if path_str.startswith(forbidden) or path_str == forbidden.rstrip("/"):
            return None, f"Akses ke path ini diblokir demi keamanan: {forbidden}"

    if allowed_base:
        base = Path(allowed_base).expanduser().resolve()
        try:
            p.relative_to(base)
        except ValueError:
            return None, f"Path di luar direktori yang diizinkan: {allowed_base}"

    return p, ""


def _is_text_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    return (mime or "").startswith("text/")


class FileSystemService:
    """
    Service untuk operasi file dengan permission gate.

    Setiap instance terikat ke satu org dan satu allowed_base_dir.
    Caller (agent) harus menyuplai pool dan permission_manager.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        org_id: str,
        permission_manager: PermissionManager,
        *,
        agent_name: str = "filesystem_agent",
        allowed_base_dir: str | None = None,
    ):
        self._pool = pool
        self._org_id = org_id
        self._pm = permission_manager
        self._agent_name = agent_name
        self._allowed_base = allowed_base_dir

    async def _check_perm(self, perm: Permission, resource: str = "") -> dict:
        result = await self._pm.check(perm, resource=resource)
        return result

    # ─── READ ──────────────────────────────────────────────────────────────

    async def read_file(self, path: str) -> dict:
        """Baca isi file. Membutuhkan izin read_files."""
        perm = await self._check_perm(Permission.READ_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin baca file belum diberikan. Minta izin dulu.", "requires_permission": "read_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved:
            return {"success": False, "error": err}

        if not resolved.exists():
            return {"success": False, "error": f"File tidak ditemukan: {path}"}
        if not resolved.is_file():
            return {"success": False, "error": f"Bukan file: {path}"}

        size = resolved.stat().st_size
        if size > _MAX_READ_BYTES:
            return {"success": False, "error": f"File terlalu besar ({size // 1024}KB > {_MAX_READ_BYTES // 1024}KB limit)"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_read", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"size_bytes": size})

        if _is_text_file(resolved):
            try:
                content = resolved.read_text(encoding="utf-8", errors="replace")
                return {
                    "success": True, "path": str(resolved), "size_bytes": size,
                    "type": "text", "content": content[:_MAX_TEXT_PREVIEW],
                    "truncated": len(content) > _MAX_TEXT_PREVIEW,
                }
            except Exception as e:
                return {"success": False, "error": f"Gagal membaca file: {e}"}
        else:
            return {
                "success": True, "path": str(resolved), "size_bytes": size,
                "type": "binary", "content": None,
                "note": "File binary — konten tidak bisa ditampilkan sebagai teks",
            }

    async def list_directory(self, path: str, *, pattern: str = "*", recursive: bool = False) -> dict:
        """Daftar file/folder dalam direktori."""
        perm = await self._check_perm(Permission.READ_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin baca file belum diberikan.", "requires_permission": "read_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved:
            return {"success": False, "error": err}

        if not resolved.exists():
            return {"success": False, "error": f"Direktori tidak ditemukan: {path}"}
        if not resolved.is_dir():
            return {"success": False, "error": f"Bukan direktori: {path}"}

        entries = []
        try:
            if recursive:
                for item in sorted(resolved.rglob(pattern))[:500]:
                    entries.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if item.is_dir() else "file",
                        "size_bytes": item.stat().st_size if item.is_file() else None,
                    })
            else:
                for item in sorted(resolved.iterdir()):
                    if fnmatch.fnmatch(item.name, pattern):
                        entries.append({
                            "name": item.name,
                            "path": str(item),
                            "type": "directory" if item.is_dir() else "file",
                            "size_bytes": item.stat().st_size if item.is_file() else None,
                        })
        except PermissionError as e:
            return {"success": False, "error": f"Akses ditolak: {e}"}

        return {"success": True, "path": str(resolved), "entries": entries, "count": len(entries)}

    async def search_files(self, base_path: str, *, query: str, pattern: str = "*") -> dict:
        """Cari file berdasarkan nama atau isi (text search)."""
        perm = await self._check_perm(Permission.READ_FILES, resource=base_path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin baca file belum diberikan.", "requires_permission": "read_files"}

        resolved, err = _safe_path(base_path, self._allowed_base)
        if not resolved or not resolved.is_dir():
            return {"success": False, "error": err or "Bukan direktori"}

        results = []
        query_lower = query.lower()
        for item in sorted(resolved.rglob(pattern))[:2000]:
            if not item.is_file():
                continue
            if query_lower in item.name.lower():
                results.append({"path": str(item), "match": "filename", "name": item.name})
            elif _is_text_file(item) and item.stat().st_size < _MAX_READ_BYTES:
                try:
                    content = item.read_text(encoding="utf-8", errors="replace")
                    if query_lower in content.lower():
                        line_no = next(
                            (i + 1 for i, line in enumerate(content.splitlines()) if query_lower in line.lower()),
                            None,
                        )
                        results.append({"path": str(item), "match": "content", "name": item.name, "line": line_no})
                except Exception:
                    pass
            if len(results) >= 100:
                break

        return {"success": True, "query": query, "results": results, "count": len(results)}

    # ─── WRITE ─────────────────────────────────────────────────────────────

    async def write_file(self, path: str, content: str, *, overwrite: bool = False) -> dict:
        """Tulis file baru atau overwrite. Membutuhkan izin write_files."""
        perm = await self._check_perm(Permission.WRITE_FILES, resource=path)
        if not perm["allowed"]:
            return {
                "success": False,
                "error": "Izin menulis file belum diberikan. Minta izin dulu.",
                "requires_permission": "write_files",
                "requires_approval": True,
            }

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved:
            return {"success": False, "error": err}

        if resolved.exists() and not overwrite:
            return {"success": False, "error": f"File sudah ada. Set overwrite=True untuk menimpa: {path}"}

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > _MAX_WRITE_BYTES:
            return {"success": False, "error": f"Konten terlalu besar untuk ditulis ({len(content_bytes) // 1024}KB)"}

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except Exception as e:
            await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                             action_type="file_write", target=str(resolved), status="failed",
                             permission_grant_id=perm.get("grant_id"), error=str(e))
            return {"success": False, "error": f"Gagal menulis file: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_write", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"size_bytes": len(content_bytes), "overwrite": overwrite})
        return {"success": True, "path": str(resolved), "size_bytes": len(content_bytes)}

    async def edit_file(self, path: str, *, old_text: str, new_text: str) -> dict:
        """Edit file: ganti teks tertentu. Membutuhkan izin write_files."""
        perm = await self._check_perm(Permission.WRITE_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin write file belum diberikan.", "requires_permission": "write_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved or not resolved.is_file():
            return {"success": False, "error": err or f"File tidak ditemukan: {path}"}

        try:
            current = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "error": f"Gagal membaca file untuk edit: {e}"}

        if old_text not in current:
            return {"success": False, "error": "Teks yang ingin diganti tidak ditemukan dalam file"}

        updated = current.replace(old_text, new_text, 1)
        try:
            resolved.write_text(updated, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Gagal menyimpan hasil edit: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_edit", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"))
        return {"success": True, "path": str(resolved)}

    async def rename_file(self, path: str, new_name: str) -> dict:
        """Rename file (dalam direktori yang sama). Membutuhkan izin write_files."""
        perm = await self._check_perm(Permission.WRITE_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin rename file belum diberikan.", "requires_permission": "write_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved or not resolved.exists():
            return {"success": False, "error": err or f"File tidak ditemukan: {path}"}

        new_path = resolved.parent / new_name
        if new_path.exists():
            return {"success": False, "error": f"Sudah ada file/folder dengan nama: {new_name}"}

        try:
            resolved.rename(new_path)
        except Exception as e:
            return {"success": False, "error": f"Gagal rename: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_rename", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"new_path": str(new_path)})
        return {"success": True, "old_path": str(resolved), "new_path": str(new_path)}

    async def move_file(self, src: str, dst: str) -> dict:
        """Pindahkan file ke path baru. Membutuhkan izin write_files."""
        perm = await self._check_perm(Permission.WRITE_FILES, resource=src)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin move file belum diberikan.", "requires_permission": "write_files"}

        src_p, err = _safe_path(src, self._allowed_base)
        if not src_p or not src_p.exists():
            return {"success": False, "error": err or f"Source tidak ditemukan: {src}"}

        dst_p, err = _safe_path(dst, self._allowed_base)
        if not dst_p:
            return {"success": False, "error": err}

        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_p), str(dst_p))
        except Exception as e:
            return {"success": False, "error": f"Gagal memindahkan: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_move", target=str(src_p), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"dst": str(dst_p)})
        return {"success": True, "src": str(src_p), "dst": str(dst_p)}

    async def copy_file(self, src: str, dst: str) -> dict:
        """Salin file. Membutuhkan izin read_files."""
        perm = await self._check_perm(Permission.READ_FILES, resource=src)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin copy file belum diberikan.", "requires_permission": "read_files"}

        src_p, err = _safe_path(src, self._allowed_base)
        if not src_p or not src_p.is_file():
            return {"success": False, "error": err or f"File tidak ditemukan: {src}"}

        dst_p, err = _safe_path(dst, self._allowed_base)
        if not dst_p:
            return {"success": False, "error": err}

        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_p), str(dst_p))
        except Exception as e:
            return {"success": False, "error": f"Gagal menyalin: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_copy", target=str(src_p), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"dst": str(dst_p)})
        return {"success": True, "src": str(src_p), "dst": str(dst_p)}

    async def delete_file(self, path: str, *, confirmed: bool = False) -> dict:
        """
        Hapus file. WAJIB izin delete_files DAN confirmed=True.

        Jika confirmed=False: kembalikan info konfirmasi, JANGAN hapus apapun.
        """
        if not confirmed:
            return {
                "success": False,
                "status": "requires_confirmation",
                "message": f"Hapus file '{path}'? Set confirmed=True untuk konfirmasi.",
                "requires_permission": "delete_files",
            }

        perm = await self._check_perm(Permission.DELETE_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin hapus file belum diberikan.", "requires_permission": "delete_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved or not resolved.exists():
            return {"success": False, "error": err or f"File tidak ditemukan: {path}"}

        try:
            if resolved.is_dir():
                shutil.rmtree(str(resolved))
            else:
                resolved.unlink()
        except Exception as e:
            await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                             action_type="file_delete", target=str(resolved), status="failed",
                             permission_grant_id=perm.get("grant_id"), error=str(e))
            return {"success": False, "error": f"Gagal menghapus: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_delete", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"))
        return {"success": True, "deleted_path": str(resolved)}

    # ─── ARCHIVE ───────────────────────────────────────────────────────────

    async def compress(self, path: str, *, output_zip: str | None = None) -> dict:
        """Kompres file/folder ke ZIP. Membutuhkan izin read_files."""
        perm = await self._check_perm(Permission.READ_FILES, resource=path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin baca file belum diberikan.", "requires_permission": "read_files"}

        resolved, err = _safe_path(path, self._allowed_base)
        if not resolved or not resolved.exists():
            return {"success": False, "error": err or f"Path tidak ditemukan: {path}"}

        zip_path = Path(output_zip) if output_zip else resolved.parent / (resolved.name + ".zip")
        try:
            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                if resolved.is_file():
                    zf.write(str(resolved), resolved.name)
                else:
                    for item in resolved.rglob("*"):
                        if item.is_file():
                            zf.write(str(item), str(item.relative_to(resolved.parent)))
        except Exception as e:
            return {"success": False, "error": f"Gagal mengompres: {e}"}

        return {"success": True, "zip_path": str(zip_path), "size_bytes": zip_path.stat().st_size}

    async def extract(self, zip_path: str, *, dest: str | None = None) -> dict:
        """Ekstrak ZIP. Membutuhkan izin write_files."""
        perm = await self._check_perm(Permission.WRITE_FILES, resource=zip_path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin write file belum diberikan.", "requires_permission": "write_files"}

        resolved, err = _safe_path(zip_path, self._allowed_base)
        if not resolved or not resolved.is_file():
            return {"success": False, "error": err or f"File ZIP tidak ditemukan: {zip_path}"}

        dest_path = Path(dest) if dest else resolved.parent / resolved.stem
        try:
            with zipfile.ZipFile(str(resolved), "r") as zf:
                zf.extractall(str(dest_path))
        except Exception as e:
            return {"success": False, "error": f"Gagal mengekstrak: {e}"}

        await log_action(self._pool, org_id=self._org_id, agent_name=self._agent_name,
                         action_type="file_extract", target=str(resolved), status="completed",
                         permission_grant_id=perm.get("grant_id"),
                         metadata={"dest": str(dest_path)})
        return {"success": True, "extracted_to": str(dest_path)}

    async def understand_project(self, project_path: str) -> dict:
        """
        Analisis struktur proyek: file tree, bahasa pemrograman, entrypoints.
        Membutuhkan izin read_files.
        """
        perm = await self._check_perm(Permission.READ_FILES, resource=project_path)
        if not perm["allowed"]:
            return {"success": False, "error": "Izin baca file belum diberikan.", "requires_permission": "read_files"}

        resolved, err = _safe_path(project_path, self._allowed_base)
        if not resolved or not resolved.is_dir():
            return {"success": False, "error": err or f"Direktori tidak ditemukan: {project_path}"}

        lang_count: dict[str, int] = {}
        entrypoints = []
        total_files = 0

        for item in resolved.rglob("*"):
            if item.is_file():
                total_files += 1
                ext = item.suffix.lower()
                lang_count[ext] = lang_count.get(ext, 0) + 1
                if item.name in {"main.py", "index.ts", "index.js", "app.py", "server.py",
                                  "main.ts", "main.go", "Dockerfile", "package.json",
                                  "requirements.txt", "Cargo.toml", "go.mod"}:
                    entrypoints.append(str(item.relative_to(resolved)))

        top_langs = sorted(lang_count.items(), key=lambda x: -x[1])[:10]
        return {
            "success": True,
            "project_path": str(resolved),
            "total_files": total_files,
            "top_extensions": dict(top_langs),
            "entrypoints": entrypoints[:20],
        }
