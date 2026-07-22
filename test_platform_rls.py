"""Security hardening — platform_rls tenant GUC primitive (step-a rollout RLS M-07).

Dua lapis:
  1) Mekanisme GUC: set/read/clear + tenant_connection reset saat release (anti-leak).
  2) Isolasi RLS NYATA end-to-end: tabel throwaway + policy (persis migration, NULLIF-
     guarded) + role NON-superuser via SET ROLE → buktikan lintas-tenant terfilter &
     fail-closed (GUC kosong → 0 baris, TANPA error cast).

Pola: pool Postgres nyata (app connect sebagai superuser → RLS di-bypass, maka bagian
(2) memakai SET ROLE ke role non-superuser agar policy benar-benar ditegakkan).
"""
import asyncio
import uuid

import asyncpg
import pytest

import main
from platform_rls import set_tenant, clear_tenant, current_tenant, tenant_connection


def _pool():
    return asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))


# ── 1) Mekanisme GUC ──────────────────────────────────────────────────────────
def test_set_read_clear_roundtrip():
    async def run():
        pool = await _pool()
        try:
            async with pool.acquire() as c:
                assert await current_tenant(c) is None            # fresh conn → unset
                await set_tenant(c, "org-abc")
                assert await current_tenant(c) == "org-abc"
                await clear_tenant(c)
                assert await current_tenant(c) is None            # '' → None (helper normalisasi)
        finally:
            await pool.close()
    asyncio.run(run())


def test_set_tenant_rejects_empty():
    async def run():
        pool = await _pool()
        try:
            async with pool.acquire() as c:
                with pytest.raises(ValueError):
                    await set_tenant(c, "")
        finally:
            await pool.close()
    asyncio.run(run())


def test_tenant_connection_sets_and_resets_on_release():
    async def run():
        # pool ukuran 1 → koneksi yang sama dipakai ulang → buktikan tak bocor
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""),
                                         min_size=1, max_size=1)
        try:
            org = str(uuid.uuid4())
            async with tenant_connection(pool, org) as conn:
                assert await current_tenant(conn) == org
            # koneksi kembali ke pool → GUC harus sudah bersih untuk penyewa berikutnya
            async with pool.acquire() as conn2:
                assert await current_tenant(conn2) is None
        finally:
            await pool.close()
    asyncio.run(run())


# ── 2) Isolasi RLS nyata (SET ROLE non-superuser) ─────────────────────────────
def test_rls_enforces_tenant_isolation_end_to_end():
    async def run():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""),
                                         min_size=1, max_size=1)
        sfx = uuid.uuid4().hex[:8]
        tbl = f"_rls_probe_{sfx}"
        role = f"rls_probe_{sfx}"
        orgA, orgB = str(uuid.uuid4()), str(uuid.uuid4())
        try:
            async with pool.acquire() as c:
                await c.execute(f"CREATE TABLE {tbl} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL, note text)")
                await c.execute(f"INSERT INTO {tbl}(org_id,note) VALUES ($1,'a1'),($1,'a2'),($2,'b1')", orgA, orgB)
                # policy PERSIS migration (NULLIF-guarded, fail-closed)
                await c.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
                await c.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
                await c.execute(
                    f"CREATE POLICY tenant_isolation ON {tbl} "
                    f"USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)")
                await c.execute(f"CREATE ROLE {role} NOLOGIN")
                await c.execute(f"GRANT SELECT ON {tbl} TO {role}")

                # (a) GUC = orgA, bertindak sebagai role non-superuser → hanya baris orgA
                await set_tenant(c, orgA)
                await c.execute(f"SET ROLE {role}")
                assert await c.fetchval(f"SELECT COUNT(*) FROM {tbl}") == 2
                notes = [r["note"] for r in await c.fetch(f"SELECT note FROM {tbl}")]
                assert set(notes) == {"a1", "a2"}
                await c.execute("RESET ROLE")

                # (b) GUC = orgB → hanya baris orgB
                await set_tenant(c, orgB)
                await c.execute(f"SET ROLE {role}")
                assert await c.fetchval(f"SELECT COUNT(*) FROM {tbl}") == 1
                await c.execute("RESET ROLE")

                # (c) GUC kosong → fail-closed 0 baris, TANPA error cast (bukti NULLIF)
                await clear_tenant(c)
                await c.execute(f"SET ROLE {role}")
                assert await c.fetchval(f"SELECT COUNT(*) FROM {tbl}") == 0
                await c.execute("RESET ROLE")

                # (d) superuser (login role) MELEWATI RLS → lihat semua (buktikan perlunya role non-owner)
                await clear_tenant(c)
                assert await c.fetchval(f"SELECT COUNT(*) FROM {tbl}") == 3
        finally:
            async with pool.acquire() as c:
                await c.execute("RESET ROLE")
                await c.execute(f"DROP TABLE IF EXISTS {tbl}")
                await c.execute(f"DROP ROLE IF EXISTS {role}")
            await pool.close()
    asyncio.run(run())
