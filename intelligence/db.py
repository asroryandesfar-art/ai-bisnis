"""
intelligence/db.py — Pool asyncpg & helper query untuk modul Intelligence.

Pool terpisah dari main.py (modul ini bisa "menumpang" di proses agent_api.py
ataupun dijalankan oleh Celery worker), tapi menunjuk ke DATABASE_URL yang sama
sehingga semua proses melihat data yang konsisten.

Juga mendaftarkan codec untuk tipe `vector` (pgvector) supaya asyncpg bisa
kirim/terima `list[float]` secara langsung — tanpa ini, asyncpg memperlakukan
`vector` sebagai tipe tak dikenal dan akan error.
"""
from __future__ import annotations

import asyncio

import asyncpg

from .config import cfg

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


def _encode_vector(value: list[float]) -> str:
    """list[float] -> literal teks pgvector, mis. '[0.1,0.2,0.3]'."""
    return "[" + ",".join(f"{float(v):.8f}" for v in value) + "]"


def _decode_vector(raw: str) -> list[float]:
    """literal teks pgvector -> list[float]."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if not raw:
        return []
    return [float(x) for x in raw.split(",")]


async def _init_connection(conn: asyncpg.Connection) -> None:
    try:
        await conn.set_type_codec(
            "vector",
            encoder=_encode_vector,
            decoder=_decode_vector,
            schema="public",
            format="text",
        )
    except Exception:
        # Ekstensi pgvector belum ter-install — modul tetap bisa jalan untuk
        # bagian non-vector (FAQ listing, sales patterns, dsb). Operasi yang
        # butuh embedding akan gagal dengan pesan jelas saat dipanggil.
        pass


async def get_pool() -> asyncpg.Pool:
    """Pool singleton (lazy, thread/async-safe)."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            dsn = cfg.database_url.replace("+asyncpg", "")
            _pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=10,
                init=_init_connection,
            )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def vector_literal(values: list[float]) -> str:
    """Helper publik dipakai saat butuh literal vector di raw SQL (mis. ORDER BY <-> $1::vector)."""
    return _encode_vector(values)
