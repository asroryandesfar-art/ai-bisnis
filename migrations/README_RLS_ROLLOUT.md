# Rollout RLS (M-07) — JANGAN apply sebelum baca ini

RLS ini adalah **defense-in-depth**. Isolasi tenant tetap ditegakkan di
application-layer (`WHERE org_id=$1`). RLS menambah jaring pengaman DB agar
satu query yang lupa filter tidak membocorkan data lintas-tenant.

> ⚠️ **Belum diterapkan.** File `2026-07-05_row_level_security.sql` sengaja
> TIDAK dijalankan otomatis. Urutan rollout yang salah bisa membuat aplikasi
> tidak melihat baris apa pun (policy fail-closed saat GUC tidak di-set).

## Prasyarat penting

1. **Aplikasi harus menetapkan GUC per koneksi tenant.** Primitive **sudah
   tersedia** (step-a): `platform_rls.tenant_connection` (lihat ADR-0013).
   ```python
   from platform_rls import tenant_connection
   async with tenant_connection(pool, org_id) as conn:
       rows = await conn.fetch("SELECT ... FROM leads")   # RLS memfilter per-org
   ```
   Ia menjalankan `set_config('app.current_org', org, false)` (session-scoped —
   menempel selama checkout, cocok untuk pool autocommit; `SET LOCAL` hanya
   bertahan 1 transaksi) dan **me-reset saat koneksi dilepas** agar tak bocor ke
   penyewa berikutnya. Tanpa GUC, `current_setting('app.current_org', true)` =
   NULL/'' → policy menolak semua baris (aman tapi aplikasi "kosong").

   > **Cast fail-closed:** policy memakai `NULLIF(current_setting(...),'')::uuid`
   > (bukan cast polos) karena `current_setting` mengembalikan `''` (bukan NULL)
   > setelah GUC pernah di-set lalu direset (mis. asyncpg `RESET ALL` saat release);
   > `''::uuid` akan ERROR — NULLIF menjadikannya 0 baris, bukan error.

   Adopsi bertahap: bungkus jalur query per-tenant dengan `tenant_connection`
   SEBELUM menjalankan migration. Tanpa RLS aktif, ini tak berefek (aman diuji).

2. **Peran DB tidak boleh bypass RLS.** Superuser & (tanpa FORCE) pemilik tabel
   otomatis melewati RLS. Migration memakai `FORCE ROW LEVEL SECURITY` supaya
   pemilik tabel pun tunduk. Pastikan aplikasi **tidak** connect sebagai
   superuser. Idealnya buat role khusus non-owner:
   ```sql
   CREATE ROLE botnesia_app LOGIN PASSWORD '<kuat>';
   GRANT USAGE ON SCHEMA public TO botnesia_app;
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO botnesia_app;
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO botnesia_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO botnesia_app;
   ```
   Lalu arahkan `DATABASE_URL` aplikasi ke role ini.

## Urutan rollout yang AMAN

1. **Deploy perubahan kode dulu** yang menetapkan `SET LOCAL app.current_org`
   di setiap transaksi request (belum ada RLS → tidak ada efek, aman diuji).
2. Verifikasi di staging bahwa GUC ter-set benar (log/`SHOW app.current_org`).
3. Baru **jalankan migration** `2026-07-05_row_level_security.sql` di staging;
   uji lintas-tenant: user org A tidak bisa membaca data org B walau query salah.
4. Jalankan di produksi saat maintenance window. Pantau error "kosong" (tanda
   GUC tak ter-set di suatu jalur) dan siapkan rollback.

## Tabel yang DIKECUALIKAN (shared/global) — tinjau sebelum apply
Tabel sistem yang memang dibagikan semua tenant TIDAK boleh kena policy tenant,
mis.: `roles`/`permissions`/`role_permissions` global (org_id NULL), `plans`,
`marketplace_templates` publik. Migration hanya menyentuh tabel yang punya
kolom `org_id`/`tenant_id` + `organizations`. Periksa `RAISE NOTICE` output dan
sesuaikan bila ada tabel yang seharusnya dikecualikan (mis. baris dengan
`org_id NULL` yang sengaja shared) — untuk itu policy bisa ditambah
`OR org_id IS NULL` sesuai kebutuhan.

## Rollback
Lihat blok komentar di akhir file SQL (DROP POLICY + NO FORCE + DISABLE RLS).

## Status
Audit **M-07: Partially Fixed** — migration & panduan siap; **(a) primitive GUC
per-koneksi kini TERSEDIA & tervalidasi** (`platform_rls.tenant_connection`,
ADR-0013; isolasi lintas-tenant dibuktikan end-to-end via test dengan role
non-superuser). Penerapan penuh masih menunggu: **adopsi** `tenant_connection` di
jalur query per-tenant, **(b) role DB non-owner** (app kini connect sebagai
`postgres` superuser → RLS DI-BYPASS; role non-superuser wajib), **(c) validasi
staging + maintenance window**. Migration tidak dijalankan otomatis sesuai keputusan
owner.
