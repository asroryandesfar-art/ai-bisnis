# ADR-0013 — Tenant-context primitive untuk rollout RLS (M-07 step-a)

- **Status:** Accepted — paket `platform_rls` (GUC per-koneksi) + hardening policy migration selesai; ENABLE RLS di prod MASIH DITAHAN
- **Tanggal:** 2026-07-23
- **Konteks:** Security hardening — gap audit "tenant isolation by-convention (tanpa RLS)"
- **Terkait:** `migrations/2026-07-05_row_level_security.sql` + `README_RLS_ROLLOUT.md` (M-07)

## Konteks
Isolasi tenant ditegakkan di application-layer (`WHERE org_id=$1`). Migration RLS
(M-07) sebagai defense-in-depth SUDAH ada tapi sengaja TIDAK dijalankan: policy
**fail-closed** (`org_id = current_setting('app.current_org', true)::uuid`) →
tanpa GUC ter-set, aplikasi "kosong". Blokir utama rollout = **step-a**: kode yang
menetapkan GUC `app.current_org` per koneksi tenant belum ada. Selain itu app
connect sebagai `postgres` **superuser** → RLS di-bypass total (bahkan dengan FORCE).

## Keputusan
Paket mandiri **`platform_rls`**: `set_tenant/clear_tenant/current_tenant` +
context manager **`tenant_connection(pool, org_id)`** yang men-`set_config(
'app.current_org', org, false)` (SESSION-scoped — menempel selama checkout koneksi;
`SET LOCAL` hanya bertahan 1 transaksi, tak cocok untuk pool autocommit) dan
**me-reset saat release** agar koneksi yang kembali ke pool tak membocorkan org ke
penyewa berikutnya. Additive & opt-in: TIDAK mengubah jalur query lama, TIDAK
menjalankan migration → default byte-identik.

Sekaligus **hardening policy migration**: cast diganti
`NULLIF(current_setting('app.current_org', true), '')::uuid`. Sebab `current_setting`
mengembalikan `''` (bukan NULL) setelah GUC pernah di-set lalu direset (mis. asyncpg
`RESET ALL` saat koneksi dilepas) → `''::uuid` akan ERROR, bukan 0 baris. NULLIF
menjadikan '' → NULL → fail-closed benar (0 baris), bukan crash.

## Alternatif
1. **Wire GUC di `get_pool` global (semua request).** Ditolak untuk gate ini: menyentuh SETIAP jalur query = risiko tinggi di prod live; lebih baik primitive opt-in + adopsi bertahap per-jalur.
2. **`SET LOCAL` per transaksi.** Tak cocok: app banyak `pool.fetch` autocommit (bukan transaksi eksplisit) → LOCAL tak bertahan. Session-scoped per-checkout + reset = pragmatis untuk pool.
3. **Primitive `tenant_connection` opt-in (DIPILIH).** Reversible, testable, unblok rollout tanpa risiko prod.

## Konsekuensi
**Positif:** step-a rollout RLS tersedia & TERVALIDASI end-to-end — test membuktikan
isolasi lintas-tenant NYATA (via `SET ROLE` ke role non-superuser pada tabel
throwaway dengan policy identik migration): orgA hanya lihat baris orgA, GUC kosong
→ 0 baris (tanpa error cast), superuser bypass terbukti. Hardening NULLIF mencegah
landmine fail-closed. **Batasan (JUJUR — belum aman ENABLE di prod):** (b) app masih
`postgres` superuser → RLS tak berefek sampai ada **role DB non-superuser**; adopsi
`tenant_connection` di jalur query per-tenant belum dilakukan; ENABLE/FORCE di tabel
prod menunggu validasi staging + maintenance window (README M-07). Cache/observability
tak terpengaruh.

## Rencana
- **step-a (selesai):** `platform_rls` + hardening policy migration + 4 test (mekanisme + isolasi RLS end-to-end).
- **berikutnya:** (b) buat role `botnesia_app` non-superuser + arahkan `DATABASE_URL`; adopsi `tenant_connection` di jalur query per-tenant (bertahap, ukur "query kosong"); validasi staging; ENABLE RLS saat maintenance window; rollback siap (blok akhir SQL migration).

## Rollback
Paket additive/idle bila tak dipakai. Migration tetap TIDAK auto-run. Bila sudah
di-ENABLE dan bermasalah: DROP POLICY + NO FORCE + DISABLE RLS (blok akhir file SQL).
