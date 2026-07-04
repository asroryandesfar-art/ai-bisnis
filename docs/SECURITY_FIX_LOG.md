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

_(menyusul)_
