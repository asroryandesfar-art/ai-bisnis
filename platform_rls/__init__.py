"""platform_rls — primitive tenant-context untuk rollout Row-Level Security (M-07).

Menyediakan "step-a" yang dibutuhkan `migrations/2026-07-05_row_level_security.sql`:
menetapkan GUC `app.current_org` per koneksi sebelum query tenant, sehingga policy
RLS fail-closed bisa diadopsi tanpa membuat aplikasi "kosong".

    from platform_rls import tenant_connection
    async with tenant_connection(pool, org_id) as conn:
        rows = await conn.fetch("SELECT ... FROM leads")   # difilter per-org oleh RLS

Additive & opt-in: TIDAK mengubah jalur query lama, TIDAK menjalankan migration.
Lihat ADR-0013 & migrations/README_RLS_ROLLOUT.md.
"""
from platform_rls.session import (
    set_tenant, clear_tenant, current_tenant, tenant_connection,
)

__all__ = ["set_tenant", "clear_tenant", "current_tenant", "tenant_connection"]
