# BotNesia — Deployment & Migration Plan

> Topologi saat ini: **single VM, single PostgreSQL, single FastAPI
> process**, di belakang Cloudflare Tunnel. Untuk runbook Cloudflare lengkap
> (DNS, named tunnel, SSL, rollback DNS) lihat
> [`docs/DEPLOY_BOTNESIA_ID.md`](DEPLOY_BOTNESIA_ID.md) — dokumen ini
> melengkapi dengan urutan migrasi schema, peta layanan systemd, dan filosofi
> migrasi yang dipakai di seluruh AI Workforce phases.

## 1. Topologi production saat ini

```
Pengguna ──HTTPS──> Cloudflare Edge ──Named Tunnel──> cloudflared (systemd)
                                                              │
                                                              ▼
                                                   127.0.0.1:8000 (FastAPI)
                                                              │
                                                              ▼
                                                   127.0.0.1:5432 (PostgreSQL 16)
```

**Fakta penting:** `/home/asrory/.local/share/botnesia/app` adalah **symlink**
ke working directory git ini (`ai bisnis/`) — tidak ada langkah build/sync
terpisah. `git commit` di repo ini = kode yang langsung dijalankan systemd
setelah `systemctl --user restart botnesia-api.service`.

## 2. Layanan systemd (`~/.config/systemd/user/`)

| Service | Tipe | Menjalankan | Bergantung pada |
|---|---|---|---|
| `botnesia-postgres.service` | simple | `start_postgres.sh` — PostgreSQL 16 embedded runtime | — |
| `botnesia-api.service` | simple, `Restart=on-failure` | `uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1`, `ExecStartPre=migrate_database.sh` | `botnesia-postgres.service` |
| `botnesia-tunnel.service` | simple, `Restart=always` | `run_https_tunnel.sh` — Cloudflare named tunnel | `botnesia-api.service` |
| `botnesia-backup.service` | oneshot | `backup_database.sh` — dump PostgreSQL harian | `botnesia-postgres.service` |

Perintah operasional sehari-hari:
```bash
systemctl --user restart botnesia-api.service   # deploy kode baru (lihat §1)
journalctl --user -u botnesia-api.service -n 50 --no-pager   # cek log
systemctl --user status botnesia-postgres.service botnesia-api.service botnesia-tunnel.service
```

## 3. Urutan migrasi database

`migrate_database.sh` (dipanggil otomatis sebagai `ExecStartPre` setiap kali
`botnesia-api.service` start/restart — **migrasi berjalan setiap deploy,
bukan langkah manual terpisah**):

```bash
1. tunggu PostgreSQL ready (pg_isready, retry 30x @ 1s)
2. psql -f schema.sql                              # Core
3. psql -f intelligence/schema_intelligence.sql     # Phase 1
4. psql -f bn_platform/schema_platform.sql          # Phase 2 + AI Workforce
```

Semua 3 file memakai `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` — **idempoten**, aman
dijalankan berkali-kali, tidak butuh tooling migrasi versi (Alembic, dst).
`ON_ERROR_STOP=1` memastikan deploy gagal loud jika ada DDL yang error,
bukan diam-diam skip.

### Filosofi migrasi yang dipakai di setiap fase AI Workforce

1. **Tambah, jangan ubah/hapus** — tabel/kolom baru ditambah dengan `IF NOT
   EXISTS`; kolom existing diperluas lewat `ALTER TABLE ... ADD COLUMN IF
   NOT EXISTS ... DEFAULT ...` (contoh: kolom `source` di `ops_alerts`/
   `ops_reports` dari Phase 5), bukan `DROP`/rename yang memutus kompatibilitas.
2. **Tidak pernah migrasi data massal big-bang** — migrasi role RBAC
   dilakukan lazy per-user saat login, bukan `UPDATE` 1 kali ke semua baris.
3. **Setiap fase dijalankan dulu di DB live dengan smoke test manual**
   (insert/approve/delete data uji dengan ID eksplisit, bukan pattern), baru
   dianggap selesai — lihat riwayat git log `AI Workforce Phase N` untuk
   pola commit per fase.

## 4. Backup & rollback

- `backup_database.sh` (`botnesia-backup.service`, oneshot harian) — dump
  PostgreSQL penuh. Restore manual via `psql < dump.sql` ke instance baru.
- **Rollback kode**: karena deploy = `git commit` + restart service,
  rollback kode adalah `git revert`/`checkout` commit sebelumnya + restart.
  Tidak ada "versi terdeploy" yang berbeda dari HEAD git.
- **Rollback schema**: tidak ada `DROP COLUMN`/`DROP TABLE` otomatis — fase
  manapun yang perlu dibatalkan idealnya dibatalkan dengan menulis migrasi
  forward baru yang menonaktifkan fitur (gate via permission/flag), bukan
  menghapus kolom yang mungkin sudah dipakai data production.
- **Rollback DNS/tunnel**: lihat [`docs/DEPLOY_BOTNESIA_ID.md`](DEPLOY_BOTNESIA_ID.md) §rollback.

## 5. Checklist sebelum menambah fase/fitur baru (AI Workforce atau lainnya)

- [ ] Cek dulu apakah tabel/router/permission serupa sudah ada (`grep`/`Explore` agent) — jangan rebuild.
- [ ] Tambah kolom/tabel baru dengan `IF NOT EXISTS`, jangan ubah kolom existing yang sudah dipakai data production.
- [ ] Permission baru: tambah di `rbac.py` PERMISSIONS dict **dan** `schema_platform.sql` seed `INSERT INTO permissions` **dan** `role_permissions` untuk role yang relevan — 3 tempat, sering lupa salah satu.
- [ ] Endpoint baru: pastikan `Depends(require_permission(...))` terpasang, ditest lewat `test_router_gates_every_route_with_*_permission`.
- [ ] Jalankan full pytest suite sebelum & setelah migrasi live.
- [ ] Smoke test di DB live dengan ID eksplisit, hapus data uji dengan ID eksplisit (bukan pattern/LIKE) setelah selesai.
- [ ] Restart `botnesia-api.service`, cek `journalctl` untuk error startup, baru anggap deploy selesai.
