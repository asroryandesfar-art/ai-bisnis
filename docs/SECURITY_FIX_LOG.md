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
- **Commit:** `ddef3e9`

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
- **Commit:** `4af3307`

### H-03 (audit ref H-02) — Rate limit chat publik di-bypass via `user_meta.userId`
- **Severity:** 🟠 High
- **Masalah:** `POST /chat/{bot_id}` mengunci rate limit pada `user_meta.userId`/email/name dari body (dikontrol klien). Rotasi `userId` per request melewati limit → kuras kuota percakapan + biaya AI tenant korban (financial DoS).
- **File diubah:** `main.py` (`_rate_limit_client_key`, `chat` menerima `request: Request`, kunci limiter dari IP server), `test_chat_rate_limit.py` (baru).
- **Cara fix:** Kunci rate-limit diambil **server-side, anti-spoof**: prioritas `CF-Connecting-IP` (di-set Cloudflare di depan tunnel), fallback IP koneksi; **X-Forwarded-For leftmost & identitas body sengaja diabaikan**. `user_meta` tetap dipakai untuk identitas percakapan/memory (fitur tak berubah). Layer per-org/plan & per-bot pada RateLimiter dipertahankan. Ukuran input tetap dibatasi `ChatReq.message` max 2000 (server-side).
- **Test ditambahkan:** kunci pakai CF-Connecting-IP; XFF spoof diabaikan; kunci tak bergantung body userId; IP sama dispam → BLOCKED; IP berbeda dilacak terpisah; pesan >2000 char ditolak.
- **Hasil test:** `test_chat_rate_limit.py` 6 passed; regresi (public demo + smoke) 21 passed.
- **Commit:** `c0ba092`

### H-04 — Local Agent command/shell risk (RCE + kebocoran secret)
- **Severity:** 🟠 High
- **Masalah:** `botnesia_local_agent.py` menjalankan command via `shell=True` dengan gate hanya heuristik blocklist; `SAFE_READONLY_COMMANDS` meng-auto-run `cat`/`env`/`printenv` (bisa baca `.env`/kunci). Tidak ada hard-block, pembatasan direktori, atau audit.
- **File diubah:** `botnesia_local_agent.py` (hard denylist, secret-file guard, env-dump guard, cwd restriction, audit log; guard di `tool_run_command`/`tool_read_file`/`tool_write_file`; `cat`/`env`/`printenv` dikeluarkan dari auto-safe), `test_local_agent_command_guard.py` (baru).
- **Cara fix:**
  1. **Hard denylist** (`is_forbidden`): rm -rf / ~, sudo/su, mkfs, dd, shutdown/reboot, chmod 777, `curl|bash`/`wget|sh`, fork bomb → diblok TOTAL (tak bisa di-approve).
  2. **Secret guard** (`references_secret`): blok referensi `.env`/`id_rsa`/`*.pem`/`*.key`/`.ssh`/`.aws`/`credentials`/`service_role`/`.pgpass`/dll; `.env.example` dikecualikan. Diterapkan juga ke read/write file.
  3. **Env-dump guard**: `env`/`printenv`/`echo $*KEY*` diblok.
  4. **Working-directory restriction** (`is_within_allowed_dir`): default HOME (override `BOTNESIA_AGENT_ROOTS`); path traversal/keluar area ditolak (setelah `realpath`).
  5. **Audit log** lokal `~/.botnesia/agent_audit.log` untuk tiap keputusan. Timeout (30s) & output cap (50KB) dipertahankan. `shell=True` dipertahankan (fitur pipe/glob) TAPI kini di belakang hard-guard ketat — keputusan owner: fitur tidak dihapus.
- **Test ditambahkan:** 39 kasus — destruktif diblok; baca-secret/env-dump diblok; `.env.example` diizinkan; command wajar tetap jalan; cwd di luar root & path traversal ditolak; limit terkonfigurasi.
- **Hasil test:** `test_local_agent_command_guard.py` 39 passed; regresi `test_local_agent_router.py` total 48 passed.
- **Commit:** `144253c` (+ `05e6b2f` isolasi rate-limiter e2e untuk H-02)

## Fixed Medium

### M-01 — Kebocoran error internal ke klien
- **Severity:** 🟡 Medium
- **Masalah:** `/auth/login`, `/auth/register`, dan `get_pool` mengirim `detail=f"...{e}"` (detail exception DB/skema/DSN) ke klien.
- **File diubah:** `main.py` (3 handler → pesan generik + `logger.exception/error`), `test_error_no_leak.py` (baru).
- **Cara fix:** Pesan generik ke user; detail lengkap hanya di log server. CSV-import error (parse file user sendiri) sengaja dipertahankan sebagai UX (bukan info-leak internal).
- **Test:** paksa error internal → status 500 & detail tidak memuat marker sensitif. 2 passed.
- **Commit:** `5579fda`

### M-05 — Dependency ber-CVE (`python-jose`, `python-multipart`)
- **Severity:** 🟡 Medium
- **Masalah:** `requirements.txt` mem-pin `python-jose==3.3.0` (CVE algorithm-confusion/DoS) & `python-multipart==0.0.9` (CVE DoS multipart) di jalur auth/upload.
- **Temuan:** environment yang berjalan SUDAH memakai versi lebih baru & aman (`python-jose 3.5.0`, `python-multipart 0.0.30`) — hanya pin di `requirements.txt` yang usang.
- **File diubah:** `requirements.txt` (pin → 3.5.0 & 0.0.30, versi terpasang & teruji).
- **Cara fix:** Selaraskan pin dengan versi patched yang sudah terpasang; hindari force-downgrade.
- **Test:** JWT round-trip (`test_secret_guard`) + smoke = 28 passed dengan versi terpasang. Deploy/CI harus `pip install -r requirements.txt` agar pin efektif.
- **Commit:** `1bb4c53`

### M-04 — Security headers hilang
- **Severity:** 🟡 Medium
- **Masalah:** Tak ada `X-Frame-Options`/`X-Content-Type-Options`/`HSTS`/`Referrer-Policy` → clickjacking dashboard & kurang defense-in-depth.
- **File diubah:** `main.py` (middleware `_security_headers`), `test_security_headers.py` (baru).
- **Cara fix:** Middleware set `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, `HSTS max-age=31536000`. CSP ketat SENGAJA tidak dipasang (SPA pakai inline script/style; akan rusak) — dicatat sebagai residual (bisa CSP report-only nanti). Aman utk widget (inline, bukan iframe halaman BotNesia).
- **Test:** header hadir di `/dashboard` & `/health`; widget.js tetap tersaji. 3 passed.
- **Commit:** `74809f6`

### M-02 — `GET /media/{path}` publik tanpa cek tenant
- **Severity:** 🟡 Medium
- **Masalah:** Media disajikan publik tanpa auth/cek pemilik; hanya mengandalkan UUID acak (obscurity).
- **File diubah:** `main.py` (`_sign_media_rel`/`_media_signed_url`, enforcement di `serve_media`, sign di image-gen/doc-gen/history), `.env.example`, `test_media_signed_url.py` (baru).
- **Cara fix (keputusan owner: signed-URL flag default-off):** URL media ditandatangani HMAC (key enkripsi) saat dikirim ke klien; DB tetap simpan path kanonik. `serve_media` menegakkan `?sig=` sah HANYA bila `MEDIA_REQUIRE_SIGNATURE=1` (default 0 = URL lama tetap terbuka, tak ada breakage). Aktifkan flag saat siap; URL baru sudah bertanda tangan. `<img>` tetap jalan (sig di query, bukan header).
- **Test:** sign deterministik & idempoten; non-media diabaikan; flag off → terbuka; flag on → tanpa/sig-salah 403, sig sah 200. 5 passed; regresi image/doc 55 passed.
- **Status:** Partially Fixed (mekanisme siap; enforcement penuh saat owner set `MEDIA_REQUIRE_SIGNATURE=1`).
- **Commit:** `40d2999`

### M-03 — CORS terlalu terbuka (`*`)
- **Severity:** 🟡 Medium
- **Masalah:** Default `allow_origins=*` untuk semua route.
- **File diubah:** `main.py` (ganti `CORSMiddleware` dgn middleware kustom `_cors_middleware` + `_cors_allow_origin_for`; default origin diubah dari `*`), `.env.example`, `test_cors_policy.py` (baru).
- **Cara fix (keputusan owner: restrict app / buka widget):** Origin app dibatasi ke `CORS_ALLOWED_ORIGINS` (default aman = `APP_URL` + localhost dev; `*` = escape hatch eksplisit). Endpoint publik widget (`/chat/*`, `/bots/{id}/config`, `/health`, `/ready`) SELALU dibuka untuk semua origin (widget pelanggan tetap jalan). Preflight OPTIONS ditangani. `allow_credentials` tetap off (Bearer). Dashboard same-origin & mobile (non-browser) tak terpengaruh.
- **Test:** path publik echo origin apa pun; path app tolak origin asing, terima origin terkonfigurasi; preflight /chat 200. 6 passed; regresi headers+smoke 13 passed.
- **Commit:** `68d9ffc`

### M-07 — Tidak ada RLS/DB-level tenant isolation (defense-in-depth)
- **Severity:** 🟡 Medium
- **Masalah:** Isolasi tenant hanya app-layer `WHERE org_id`; tak ada jaring pengaman DB.
- **File ditambah:** `migrations/2026-07-05_row_level_security.sql` (idempoten, dinamis: enable+FORCE RLS + policy `tenant_isolation` pada semua tabel ber-`org_id`/`tenant_id` + `organizations`), `migrations/README_RLS_ROLLOUT.md` (urutan rollout aman, role non-owner, GUC `app.current_org`, rollback).
- **Cara fix (keputusan owner: siapkan migration, JANGAN apply):** Migration disiapkan lengkap namun **tidak dijalankan** ke DB produksi. Penerapan penuh butuh (a) kode set `SET LOCAL app.current_org` per-request, (b) role DB non-owner, (c) maintenance window. Policy fail-closed (GUC kosong → 0 baris).
- **Test:** tidak dijalankan ke DB (sesuai keputusan). SQL memakai dollar-quoting bersarang valid; idempoten.
- **Status:** Partially Fixed (artefak siap-apply).
- **Commit:** `2b79706`

### M-06 — JWT web di localStorage — DITUNDA (accepted)
- **Severity:** 🟡 Medium
- **Keputusan owner:** Tunda. Pindah ke cookie httpOnly = refactor auth besar (web + mobile), berisiko memutus sesi.
- **Mitigasi yang sudah ada:** XSS sudah dimitigasi kuat (markdown di-`esc()` sebelum transform, link `http(s)://` saja), sehingga jalur pencurian token via XSS sangat sempit.
- **Rekomendasi:** Saat ada slot refactor, pindahkan sesi web ke cookie httpOnly+SameSite atau token in-memory + refresh; mobile tetap Bearer/SecureStore.
- **Status:** Deferred (risiko diterima sementara). Tidak ada perubahan kode.

## Fixed Low / Info

### L-01 — Enumerasi user via timing login
- **Severity:** 🔵 Low
- **Masalah:** Saat email tak ditemukan, login melewati verifikasi password → beda waktu respons membocorkan email terdaftar/tidak.
- **File diubah:** `main.py` (`_DUMMY_PWD_HASH` + verify dummy pada cabang not-found), `test_login_enumeration.py` (baru).
- **Cara fix:** Selalu jalankan `verify_password` terhadap hash dummy valid saat email tak ada → durasi setara. Pesan sudah seragam ("Email atau password salah"). Catatan: register masih memberi tahu "email sudah terdaftar" (kebutuhan UX tanpa email-verification) — risiko rendah, dicatat.
- **Test:** dummy hash valid; cabang not-found tetap memanggil verify dgn dummy hash; status 401. 2 passed.
- **Commit:** `b22a233`

### L-02 — Swagger `/docs` terbuka publik
- **Severity:** 🔵 Low
- **Masalah:** `/docs` (+ `/openapi.json`) mengekspos seluruh skema API tanpa auth.
- **File diubah:** `main.py` (`enable_api_docs` + docs/redoc/openapi conditional), `.env.example`, `test_docs_disabled.py` (baru).
- **Cara fix:** Default nonaktif (`docs_url=redoc_url=openapi_url=None`); aktifkan di dev via `ENABLE_API_DOCS=1`.
- **Test:** default → /docs, /redoc, /openapi.json 404. 1 passed; smoke 10 passed.
- **Commit:** `b2f3186`

## Status Akhir per Severity
- 🔴 **Critical (1/1):** C-01 Fixed (warn-mode; owner aktifkan STRICT_SECRETS=1).
- 🟠 **High (4/4):** H-01, H-02, H-03 Fixed; H-04 Fixed (Partial — shell=True dipertahankan per keputusan owner).
- 🟡 **Medium (7):** M-01 Fixed · M-04 Fixed · M-05 Fixed · M-02 Fixed(Partial, flag off) · M-03 Fixed · M-07 Fixed(Partial, migration belum di-apply) · M-06 Deferred(accepted).
- 🔵 **Low (6) & ⚪ Info (2):** belum dikerjakan (di luar scope permintaan).

## Ringkasan & Verifikasi Suite (setelah semua Critical+High+Medium)
- **Baseline `main`:** 20 failed, 1112 passed (kegagalan pra-ada: tes AI/prompt/reasoning/e2e yang butuh provider AI live — di luar scope).
- **Branch `security/critical-high-fixes`:** 20 failed — **set kegagalan IDENTIK dengan `main` → 0 regresi baru**; +~91 test keamanan baru.
- Collection penuh 1212+ tests tanpa import-error.
- **Commit High/Critical:** `ddef3e9` C-01 · `b6b1cbd` H-01 · `4af3307` H-02 · `c0ba092` H-03 · `144253c` H-04 · `05e6b2f` e2e-isolasi.
- **Commit Medium:** `5579fda` M-01 · `1bb4c53` M-05 · `74809f6` M-04 · `40d2999` M-02 · `68d9ffc` M-03 · `2b79706` M-07 · `c1a75e3` M-06(deferred).

## Catatan / Risiko Tersisa & Aksi Owner
- **C-01:** guard warn-only sampai owner set `SECRET_KEY` kuat (≥32 char) + `STRICT_SECRETS=1`; saat rotasi set `INTEGRATION_ENCRYPTION_KEY`=SECRET_KEY lama.
- **M-02:** aktifkan `MEDIA_REQUIRE_SIGNATURE=1` saat siap (URL baru sudah bertanda tangan).
- **M-03:** default kini membatasi origin ke `APP_URL`+localhost; tambah origin lain via `CORS_ALLOWED_ORIGINS` bila ada klien browser cross-origin lain.
- **M-05:** deploy/CI harus `pip install -r requirements.txt` agar pin efektif.
- **M-07:** jalankan migration RLS mengikuti `migrations/README_RLS_ROLLOUT.md` (butuh kode GUC + role non-owner + maintenance window).
- **M-06 & Low/Info:** belum ditangani; rekomendasi ada di audit.
- **H-04 `shell=True`:** dipertahankan per keputusan owner; guard mempersempit drastis, audit log membantu deteksi.
