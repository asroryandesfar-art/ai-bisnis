"""storage_backend.py — abstraksi penyimpanan file media & dokumen.

Backend aktif: local disk di bawah `data/media/` (path sama dengan `_MEDIA_DIR`
yang sudah dipakai endpoint `/media/image` lama di main.py, dan diserve oleh
`serve_media()` di main.py untuk path apa pun di bawahnya). `save_bytes()`
adalah satu-satunya titik tulis — kalau nanti perlu S3/Supabase Storage,
cukup ganti isi fungsi ini, semua caller tidak perlu berubah.
"""
from __future__ import annotations

import uuid
from pathlib import Path

MEDIA_DIR = Path("data/media").resolve()


def save_bytes(subdir: str, data: bytes, *, ext: str = "", filename: str | None = None) -> tuple[Path, str]:
    """Simpan bytes ke `data/media/{subdir}/{filename}`.

    Returns (absolute_path, public_url) — public_url cocok dengan rute
    `GET /media/{path:path}` yang sudah ada di main.py.
    """
    out_dir = MEDIA_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = filename or f"{uuid.uuid4().hex}{ext}"
    path = out_dir / name
    path.write_bytes(data)
    rel = path.relative_to(MEDIA_DIR).as_posix()
    return path, f"/media/{rel}"
