-- ============================================================================
-- M-07 — Row-Level Security (RLS) tenant isolation (DEFENSE-IN-DEPTH)
-- ============================================================================
-- STATUS: SIAP-REVIEW, JANGAN JALANKAN OTOMATIS DI PRODUKSI.
-- Baca migrations/README_RLS_ROLLOUT.md dulu — urutan rollout SALAH bisa
-- membuat aplikasi tidak melihat baris apa pun (fail-closed).
--
-- Tujuan: menambahkan lapisan pengaman DB agar satu query yang lupa filter
-- `org_id`/`tenant_id` TIDAK membocorkan data lintas-tenant. Isolasi tetap
-- juga ditegakkan di application-layer (WHERE org_id=$1) seperti sekarang;
-- ini hanya jaring pengaman tambahan.
--
-- Model: setiap koneksi aplikasi WAJIB menetapkan GUC `app.current_org` sebelum
-- query tenant — gunakan primitive `platform_rls.tenant_connection` (lihat ADR-0013).
-- Policy hanya mengizinkan baris yang cocok. Bila GUC tidak di-set (NULL) ATAU
-- kosong ('') → tidak ada baris (fail-closed, aman).
--
-- CATATAN cast: memakai NULLIF(current_setting(...),'')::uuid — BUKAN cast polos.
-- current_setting('app.current_org', true) mengembalikan '' (bukan NULL) setelah
-- GUC pernah di-set lalu direset (mis. asyncpg `RESET ALL` saat koneksi dilepas ke
-- pool); ''::uuid akan ERROR (bukan 0 baris) → NULLIF menjadikannya NULL = 0 baris.
--
-- Idempoten: aman dijalankan ulang (DROP POLICY IF EXISTS sebelum CREATE).
-- ============================================================================

BEGIN;

-- 1) Tabel tenant yang di-key oleh kolom `org_id` atau `tenant_id`.
--    Enable + FORCE RLS lalu pasang policy tenant_isolation.
DO $$
DECLARE
    r RECORD;
    col TEXT;
BEGIN
    FOR r IN
        SELECT c.table_name,
               MAX(CASE WHEN c.column_name = 'org_id'    THEN 1 ELSE 0 END) AS has_org,
               MAX(CASE WHEN c.column_name = 'tenant_id' THEN 1 ELSE 0 END) AS has_tenant
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND c.column_name IN ('org_id', 'tenant_id')
        GROUP BY c.table_name
    LOOP
        -- Prioritaskan org_id bila ada; kalau tidak, pakai tenant_id.
        col := CASE WHEN r.has_org = 1 THEN 'org_id' ELSE 'tenant_id' END;

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', r.table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;', r.table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I;', r.table_name);
        EXECUTE format($f$
            CREATE POLICY tenant_isolation ON public.%I
            USING (%I = NULLIF(current_setting('app.current_org', true), '')::uuid)
            WITH CHECK (%I = NULLIF(current_setting('app.current_org', true), '')::uuid);
        $f$, r.table_name, col, col);

        RAISE NOTICE 'RLS aktif pada %.% (kolom %)', 'public', r.table_name, col;
    END LOOP;
END $$;

-- 2) Tabel organizations di-key oleh kolom `id` (bukan org_id).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name='organizations') THEN
        ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON public.organizations;
        CREATE POLICY tenant_isolation ON public.organizations
            USING (id = NULLIF(current_setting('app.current_org', true), '')::uuid)
            WITH CHECK (id = NULLIF(current_setting('app.current_org', true), '')::uuid);
    END IF;
END $$;

-- 3) CATATAN: tabel lintas-tenant / sistem (mis. roles/permissions global,
--    plans, marketplace_templates publik) TIDAK diberi RLS di sini karena
--    memang di-share semua tenant. Tinjau daftar di README sebelum apply.

COMMIT;

-- ROLLBACK (jika perlu menonaktifkan lagi):
--   Untuk tiap tabel: DROP POLICY IF EXISTS tenant_isolation ON public.<t>;
--                     ALTER TABLE public.<t> NO FORCE ROW LEVEL SECURITY;
--                     ALTER TABLE public.<t> DISABLE ROW LEVEL SECURITY;
