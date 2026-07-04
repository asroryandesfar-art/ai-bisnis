# Security Fix Log BotNesia

Branch: `security/critical-high-fixes` · Mulai: 2026-07-05
Setiap celah = satu commit. Test dijalankan setelah tiap fix.

## Fixed Critical

### C-01 — SECRET_KEY default tanpa guard startup
- **Severity:** 🔴 Critical
- **Masalah:** `SECRET_KEY` default `"change-me-in-production"`, tanpa validasi startup → JWT bisa dipalsukan (takeover akun/tenant). Key yang sama juga dipakai mengenkripsi kredensial integrasi (Gmail/WhatsApp/Meta), jadi key lemah = enkripsi lemah.
- **File diubah:** `main.py` (Settings + `audit_secret_key`/`validate_startup_secrets` + hook startup + 11 call-site enkripsi), `.env.example`, `test_secret_guard.py` (baru).
- **Cara fix (sesuai keputusan owner):**
  1. Tambah guard kekuatan secret: tolak nilai default/known-weak & terlalu pendek (<32) & entropi rendah.
  2. Perilaku **warn-by-default** (server live tetap boot) + **fail-closed** bila `STRICT_SECRETS=1`.
  3. **Pisahkan key enkripsi** integrasi: `INTEGRATION_ENCRYPTION_KEY` (default fallback ke `SECRET_KEY` → backward-compat). Saat rotasi `SECRET_KEY`, set `INTEGRATION_ENCRYPTION_KEY`=key lama agar integrasi lama tetap terbaca. 11 call-site enkripsi dipindah ke `effective_encryption_key`; JWT tetap pakai `secret_key`.
  4. `.env.example` diberi placeholder aman + instruksi generate secret.
- **Test ditambahkan:** `test_secret_guard.py` — default/empty/short/low-entropy ditolak; strong diterima; strict raise; warn-mode tidak raise tapi melaporkan; fallback & pemisahan encryption key.
- **Hasil test:** `test_secret_guard.py` + `test_app_smoke.py` = 28 passed. Integrasi (meta/whatsapp/channel/omnichannel) = 65 passed. Tidak ada regresi.
- **Tindakan owner yang diperlukan (di luar kode):** set `SECRET_KEY` kuat (≥32 char acak) di `.env`, set `INTEGRATION_ENCRYPTION_KEY`=SECRET_KEY lama saat rotasi, lalu `STRICT_SECRETS=1`.
- **Commit:** _(diisi setelah commit)_

## Fixed High

### H-01 (audit ref H-03) — RBAC privilege escalation (admin bisa jadi owner)
- **Severity:** 🟠 High
- **Masalah:** `/rbac/assign` & `/rbac/invite` bergating `team.manage` (dimiliki admin), tapi tak ada plafon privilege → admin bisa assign role `owner`/`admin` ke dirinya sendiri → eskalasi.
- **File diubah:** `bn_platform/rbac.py` (helper `_role_rank`, `assert_can_grant_role`, `actor_highest_rank` + enforcement di assign/invite/revoke), `test_rbac_privilege_escalation.py` (baru).
- **Cara fix:**
  1. Hanya Owner (rank 0) boleh memberikan/mencabut role owner/admin.
  2. Aktor tak boleh memberi role lebih tinggi dari role tertinggi miliknya (anti self-promote & lateral escalate).
  3. Tenant isolation sudah ada (assign/revoke cek `org_id`); audit log role_change sudah ada — dipertahankan.
- **Test ditambahkan:** `test_rbac_privilege_escalation.py` — owner grant apa saja OK; admin gagal grant owner/admin; manager/viewer gagal eskalasi; self-promote admin→owner ditolak 403.
- **Hasil test:** 12 passed; regresi permission (`test_bot_permission`, `test_org_plan_permission`, smoke) 19 passed.
- **Commit:** `b6b1cbd`

### H-02 (audit ref H-01) — Billing bypass via `PATCH /org/plan` (upgrade tanpa bayar)
- **Severity:** 🟠 High
- **Masalah:** `PATCH /org/plan` menaikkan `organizations.plan` + limit ke tier apa pun (owner) tanpa pembayaran → self-upgrade gratis + desync dgn `subscriptions`.
- **File diubah:** `main.py` (`_PLAN_RANK` + guard upgrade di `update_org_plan`), `test_org_plan_permission.py` (diperbarui + test baru).
- **Cara fix:** Endpoint legacy hanya boleh **downgrade / tetap sama tier**. Upgrade ke tier lebih mahal ditolak `402` dan diarahkan ke `/api/billing/checkout` (invoice + webhook Midtrans terverifikasi = satu-satunya jalur menaikkan plan). Guard independen dari wiring RBAC. Permission `billing.manage` tetap wajib. Fitur downgrade & sinkronisasi limit dipertahankan.
- **Test ditambahkan/diperbarui:** downgrade & same-tier sukses; upgrade (starter→scale/growth) ditolak 402; upgrade tetap 402 walau platform RBAC unavailable; validasi limit downgrade (409) dipertahankan; permission deny (403).
- **Hasil test:** `test_org_plan_permission.py` 6 passed; `test_billing_checkout_transaction`, `test_billing_webhook_race` 4 passed.
- **Commit:** _(diisi setelah commit)_
