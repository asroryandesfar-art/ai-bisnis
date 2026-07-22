"""platform_rls.session — tenant GUC per koneksi (step-a rollout RLS M-07).

Migration RLS (`migrations/2026-07-05_row_level_security.sql`) FAIL-CLOSED: policy
`org_id = current_setting('app.current_org', true)::uuid`. Agar aman diadopsi,
aplikasi WAJIB menetapkan GUC `app.current_org` di koneksi yang melayani request
tenant SEBELUM query. Modul ini menyediakan primitive itu (step-a di README rollout)
— TANPA menjalankan migration & TANPA mengubah jalur query lama (opt-in).

Catatan pool: pakai `set_config(..., is_local=false)` = SESSION-scoped, menempel
pada koneksi selama checkout (bukan `SET LOCAL` yang hanya bertahan 1 transaksi —
tak cocok untuk pool autocommit). `tenant_connection` WAJIB me-reset saat release
agar koneksi yang kembali ke pool tak membocorkan org ke penyewa berikutnya
(asyncpg `RESET ALL` saat release juga membersihkan, ini defense-in-depth).

Modul MANDIRI (tak impor app). Superuser & pemilik-tabel-tanpa-FORCE MELEWATI RLS
(lihat README: butuh role DB non-superuser) → primitive ini perlu, tapi belum cukup
sendiri untuk isolasi; itu keputusan rollout, bukan kode.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

_GUC = "app.current_org"


async def set_tenant(conn, org_id: str) -> None:
    """Set GUC tenant pada koneksi (session-scoped). org_id wajib non-kosong."""
    org = str(org_id or "").strip()
    if not org:
        raise ValueError("set_tenant: org_id wajib (kosong → RLS fail-closed = 0 baris)")
    await conn.execute("SELECT set_config($1, $2, false)", _GUC, org)


async def clear_tenant(conn) -> None:
    """Kosongkan GUC tenant (kembali fail-closed)."""
    await conn.execute("SELECT set_config($1, '', false)", _GUC)


async def current_tenant(conn) -> str | None:
    """Baca GUC tenant aktif (None bila tak di-set) — untuk verifikasi/observability."""
    v = await conn.fetchval("SELECT current_setting($1, true)", _GUC)
    return v or None


@asynccontextmanager
async def tenant_connection(pool, org_id: str):
    """Pinjam koneksi dari pool dengan GUC tenant ter-set; reset saat dilepas.

        async with tenant_connection(pool, org_id) as conn:
            rows = await conn.fetch("SELECT ... FROM t")   # RLS memfilter per-org

    Selalu me-reset GUC di `finally` sebelum mengembalikan koneksi ke pool."""
    conn = await pool.acquire()
    try:
        await set_tenant(conn, org_id)
        yield conn
    finally:
        try:
            await clear_tenant(conn)
        except Exception:
            pass
        await pool.release(conn)
