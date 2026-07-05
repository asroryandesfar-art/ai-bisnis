# Security Audit BotNesia

> White-box defensive audit — repo lokal (`/home/asrory/Documents/OneDrive-Dokumen/ai bisnis`).
> Tanggal: 2026-07-05 · Auditor: Senior Security Engineer (AI-assisted).
> Metode: static review (source), enumerasi endpoint, cek isolasi tenant, dependency audit (`pip-audit`/`npm audit`).
> Tidak ada exploit destruktif, tidak ada perubahan kode fitur, tidak ada reset DB. Laporan-only sesuai instruksi.

---

## Ringkasan Eksekutif

BotNesia secara umum **sudah menerapkan banyak kontrol keamanan yang benar**: query DB konsisten difilter `org_id` (isolasi tenant kuat di `main.py`), verifikasi signature webhook Meta & Midtrans (fail-closed, `hmac.compare_digest`), SSRF-guard pada URL ingestion (`tool_registry._validate_url`), escaping XSS pada markdown (`mdInline` meng-`esc()` sebelum transform, link dibatasi `http(s)://`), SQL query di-parameterize (termasuk AI tool `_exec_database_query` yang pakai allowlist tabel/kolom), dan token mobile disimpan di keychain (`expo-secure-store`).

Temuan tersisa terpusat pada: **konfigurasi rahasia default tanpa guard**, **bypass billing/limit**, **abuse kuota via endpoint publik**, **eskalasi privilege admin→owner**, dan sejumlah hardening deployment (CORS, security headers, dependency).

| Metrik | Jumlah |
|---|---|
| **Total celah** | 20 |
| 🔴 Critical | 1 |
| 🟠 High | 4 |
| 🟡 Medium | 7 |
| 🔵 Low | 6 |
| ⚪ Info | 2 |

**Status remediasi (per 2026-07-05, branch `security/critical-high-fixes`):** Critical 1/1 Fixed · High 4/4 Fixed (H-04 partial) · Medium: M-01/M-03/M-04/M-05 Fixed, M-02/M-07 Fixed-partial, M-06 Deferred · Low/Info belum. Detail & commit di `docs/SECURITY_FIX_LOG.md`. 0 regresi test vs baseline `main`.

**Catatan arsitektur penting:** aplikasi memakai **asyncpg langsung ke PostgreSQL, bukan Supabase client + RLS**. Artinya isolasi tenant sepenuhnya bergantung pada klausa `WHERE org_id=$1` di application-layer. Tidak ada Row-Level Security sebagai defense-in-depth: **satu endpoint yang lupa filter `org_id` = kebocoran lintas-tenant langsung.** (lihat H-ARCH / M-07).

---

## Tabel Prioritas

| No | Severity | Area | Celah | Dampak | File/Endpoint | Status | Rekomendasi |
|----|----------|------|-------|--------|---------------|--------|-------------|
| C-01 | 🔴 Critical | Auth/Secrets | `secret_key` default `"change-me-in-production"` tanpa startup guard | Forge JWT → takeover semua akun/tenant; sekaligus lemahkan enkripsi OAuth/WA secret | `main.py:130,1528,1535` | **Fixed** (guard + pisah enc key; owner set STRICT_SECRETS=1) | Fail-fast jika secret default/kosong; pisahkan key enkripsi |
| H-01 | 🟠 High | Billing | `PATCH /org/plan` set plan & limit langsung tanpa pembayaran | Owner self-upgrade ke `scale` gratis; desync dgn `subscriptions` | `main.py:1844-1889` | **Fixed** (upgrade→402, downgrade-only) | Hapus/kunci endpoint; plan hanya via webhook terverifikasi |
| H-02 | 🟠 High | API/Billing | Rate limit `POST /chat/{bot_id}` di-key oleh `user_meta.userId` (client-controlled) | Bypass limit → kuras kuota percakapan + biaya AI tenant korban (financial DoS) | `main.py:4646-4699` | **Fixed** (kunci IP anti-spoof) | Rate limit per-IP/bot server-side; jangan percaya key dari klien |
| H-03 | 🟠 High | RBAC | Admin (`team.manage`) bisa assign role `owner` (termasuk ke diri sendiri) | Eskalasi privilege admin→owner (dapat `billing.manage`,`bots.delete`) | `bn_platform/rbac.py:413-431,217-230` | **Fixed** | Larang grant role ≥ role aktor; hanya owner boleh buat owner |
| H-04 | 🟠 High | AI Agent | Local Agent eksekusi command server via `shell=True`, gate hanya heuristik blocklist | RCE di komputer user bila channel command/otorisasi lemah/bypass heuristik | `botnesia_local_agent.py:187-197` | **Fixed (Partial)** hard-denylist+secret+cwd guard; shell=True dipertahankan | Allowlist perintah, autentikasi per-user kuat, hindari `shell=True` |
| M-01 | 🟡 Medium | API/Info-leak | Error internal bocor ke klien `detail=f"...{e}"` | Stack/DB error → info disclosure bantu attacker | `main.py:1681-1684,1744-1748` | **Fixed** | Pesan generik ke user, log detail server-side |
| M-02 | 🟡 Medium | Storage/IDOR | `GET /media/{path}` publik tanpa auth/cek tenant | File media lintas-tenant diakses siapa pun yg tahu path (obscurity UUID) | `main.py:2957-2962` | **Fixed (Partial)** signed-URL, set MEDIA_REQUIRE_SIGNATURE=1 | Wajibkan auth + verifikasi kepemilikan file per-org |
| M-03 | 🟡 Medium | CORS | `allow_origins=*` default + all methods/headers | Origin mana pun bisa panggil API (risiko naik jika pindah ke cookie auth) | `main.py:205,382-387` | **Fixed** (restrict app, buka widget) | Whitelist origin produksi, jangan `*` |
| M-04 | 🟡 Medium | Deployment | Tidak ada security headers (CSP/HSTS/X-Frame-Options) | Clickjacking dashboard; XSS defense-in-depth hilang | `main.py` (tak ada middleware) | **Fixed** (CSP ketat ditunda) | Tambah middleware header keamanan |
| M-05 | 🟡 Medium | Dependency | `python-jose==3.3.0` & `python-multipart==0.0.9` versi ber-CVE | Algo-confusion/DoS JWT; DoS multipart | `requirements.txt:5,10` | **Fixed** (pin 3.5.0/0.0.30) | Upgrade jose≥3.4, multipart≥0.0.18 |
| M-06 | 🟡 Medium | Frontend | JWT web disimpan di `localStorage` | Token dicuri jika ada XSS mana pun | `frontend/api-client.js:71-73` | **Deferred** (accepted; XSS ter-mitigasi) | Pertimbangkan cookie httpOnly+SameSite atau memory + refresh |
| M-07 | 🟡 Medium | Arsitektur/DB | Tidak ada RLS/DB-level tenant isolation | Satu query lupa `org_id` = bocor lintas-tenant, tanpa jaring pengaman | seluruh data layer | **Fixed (Partial)** migration siap, belum di-apply | Aktifkan RLS Postgres per-tenant sbg defense-in-depth |
| L-01 | 🔵 Low | Auth | Enumerasi user (register 400 "sudah terdaftar"; login skip-hash saat user tak ada → timing) | Attacker validasi email terdaftar | `main.py:1651-1652,1719-1731` | **Fixed** (timing login; register dicatat) | Pesan seragam; dummy-verify utk timing konstan |
| L-02 | 🔵 Low | Deployment | Swagger `/docs` terbuka publik | Enumerasi seluruh skema API | `main.py:377` | **Fixed** (default off, ENABLE_API_DOCS) | Nonaktif/proteksi di produksi |
| L-03 | 🔵 Low | Path | `serve_media`/`frontend_asset` pakai `startswith(str(dir))` tanpa separator | Edge-case akses sibling-dir berprefix sama | `main.py:2960,458-460` | **Fixed** (is_relative_to) | Bandingkan pakai `Path.is_relative_to()` |
| L-04 | 🔵 Low | Crypto | Satu `secret_key` dipakai untuk sign JWT + enkripsi integration secret | Kompromi satu fungsi = kompromi keduanya | `main.py:1528,816,904` | Open | Pisahkan `JWT_SECRET` vs `ENCRYPTION_KEY` |
| L-05 | 🔵 Low | SSRF | DNS-rebinding TOCTOU pada URL ingestion (sudah didokumentasikan) | Fetch host internal via rebinding (celah sempit) | `tool_registry.py:362`, `main.py:5506` | Open | Resolve→pin IP→validasi→connect ke IP tsb |
| L-06 | 🔵 Low | Dependency | `npm audit`: 12 moderate (transitive Expo) | Kerentanan moderate di rantai build mobile | `mobile/package-lock.json` | Open | `npm audit fix`; pantau advisory Expo |
| I-01 | ⚪ Info | RBAC | Audit metadata dibangun via f-string JSON (`role_key`) | Brittle; injeksi JSON tercegah krn role divalidasi dulu | `bn_platform/rbac.py:429,447` | Open | Pakai `json.dumps()` konsisten |
| I-02 | ⚪ Info | Supply chain | Dependency di-vendor (`vendor/`, `.tts_vendor/`) di luar `requirements.txt` | Salinan lib tak terpantau tool audit/patch | `vendor/`, `.tts_vendor/` | Open | Pin & audit vendored deps, atau kembali ke pip-managed |

---

## Detail Celah

### C-01 — Default `SECRET_KEY` tanpa startup guard (JWT forgery + weak secret encryption)
- **Severity:** 🔴 Critical
- **Lokasi:** `main.py:130` (`secret_key: str = "change-me-in-production"`), dipakai di `create_token` (`:1528`), `get_current_user` (`:1535`), dan `decrypt_dict/db_set_integration` (`:816,904,1904…`).
- **Masalah:** Nilai default hard-coded dan **tidak ada validasi startup** yang menolak boot bila `SECRET_KEY` tak di-set. Jika deploy tanpa env (atau env salah), server berjalan dengan secret yang diketahui publik (ada di source).
- **Dampak bisnis:** Siapa pun yang tahu default bisa **menandatangani JWT sendiri** dengan `sub=<user_id korban>` & `org=<org korban>` → login sebagai user/tenant mana pun → takeover penuh platform. Karena secret yang sama dipakai untuk **mengenkripsi integration secret** (token Gmail/WhatsApp/Meta), secret lemah juga membocorkan kredensial channel tersimpan.
- **Skenario penyalahgunaan (aman):** Di lab, `jwt.encode({"sub": any_uuid, "org": any_uuid, "exp": ...}, "change-me-in-production", algorithm="HS256")` menghasilkan token yang diterima `/org`, `/bots`, dst. Tidak perlu password.
- **Cara memperbaiki:**
  1. Tambah guard di startup: `if cfg.secret_key in ("", "change-me-in-production") or len(cfg.secret_key) < 32: raise SystemExit("SECRET_KEY wajib di-set, min 32 char acak")`.
  2. Generate `SECRET_KEY` acak kuat (`secrets.token_urlsafe(48)`).
  3. Pisahkan key enkripsi integrasi dari key JWT (lihat L-04).
- **Checklist verifikasi:**
  - [ ] Boot dengan `SECRET_KEY` default → server menolak start.
  - [ ] Token yang di-sign dgn key lama/default ditolak (401).
  - [ ] `SECRET_KEY` produksi ≥ 32 char & hanya di secret manager, bukan di repo.

### H-01 — `PATCH /org/plan` upgrade plan/limit tanpa pembayaran
- **Severity:** 🟠 High
- **Lokasi:** `main.py:1844-1889`.
- **Masalah:** Endpoint meng-`UPDATE organizations SET plan, bot_limit, conv_limit, doc_limit` langsung ke tier apa pun (`starter/growth/scale`) hanya bermodal permission `billing.manage` (dimiliki owner). Tidak ada invoice/pembayaran. Sumber kebenaran limit sebenarnya (`check_limit`) baca dari tabel `subscriptions` (hanya diubah lewat webhook terverifikasi) — sehingga endpoint ini **membuat state billing tidak konsisten** dan, pada jalur fallback yang membaca `organizations.*_limit` langsung (mis. `main.py:4216-4223`, `get_org`), **menaikkan limit tanpa bayar**.
- **Dampak bisnis:** Kehilangan pendapatan (self-upgrade gratis), data billing tidak akurat, potensi penyalahgunaan kuota.
- **Skenario (aman):** Owner tenant trial memanggil `PATCH /org/plan {"plan":"scale"}` → `organizations.plan=scale` + limit naik, tanpa transaksi Midtrans.
- **Cara memperbaiki:** Jadikan perubahan plan **hanya** efek samping dari `_mark_invoice_paid`/`activate_subscription`. Jika endpoint diperlukan untuk admin internal, batasi ke platform-superadmin (bukan owner tenant) + audit.
- **Checklist verifikasi:**
  - [ ] Owner tenant tak bisa naikkan plan tanpa invoice `paid`.
  - [ ] `organizations.plan` selalu sinkron dengan `subscriptions.plan_id`.
  - [ ] Downgrade/upgrade tercatat di audit log.

### H-02 — Rate limit chat publik di-key oleh identitas dari klien
- **Severity:** 🟠 High
- **Lokasi:** `main.py:4646-4699` (`user_key = user_meta.get("userId") or email or name or "anonymous"`).
- **Masalah:** `POST /chat/{bot_id}` publik (widget). Rate limiter memakai `user_key` yang **sepenuhnya dikontrol klien** via `user_meta`. Attacker cukup merotasi `userId` tiap request untuk melewati limit per-user. Kuota bulanan per-org tetap ada (baik), tapi itu justru bisa **dihabiskan** oleh attacker → korban ter-DoS + biaya token AI membengkak.
- **Dampak bisnis:** Financial DoS (biaya LLM), penolakan layanan ke pelanggan sah tenant, distorsi analitik.
- **Skenario (aman):** Skrip kirim 10k request ke `/chat/{bot_id}` dgn `user_meta.userId` acak per request → tiap request dianggap user baru, lolos throttle per-user, kuota org habis.
- **Cara memperbaiki:** Rate limit berbasis **IP + bot_id** (server-derived) dan/atau proof-of-work/captcha untuk widget anonim; batasi biaya per-conversation; `userId` klien hanya untuk memory thread, bukan untuk rate-limit key.
- **Checklist verifikasi:**
  - [ ] Rotasi `userId` tidak menaikkan throughput yang diizinkan.
  - [ ] Ada cap request/menit per IP per bot.
  - [ ] Uji beban menunjukkan limit ditegakkan meski `user_meta` di-spoof.

### H-03 — Eskalasi privilege: admin bisa memberi role `owner`
- **Severity:** 🟠 High
- **Lokasi:** `bn_platform/rbac.py:413-431` (`/rbac/assign`), `assign_role` `:217-230`. Guard-nya hanya `require_permission("team.manage")`.
- **Masalah:** Role `admin` punya semua permission kecuali `billing.manage` & `bots.delete` — termasuk `team.manage`. `assign_role` menerima `role_key="owner"` tanpa larangan. Jadi admin bisa `POST /rbac/assign {user_id: <dirinya>, role_key: "owner"}` dan mendapatkan seluruh permission (termasuk `billing.manage`, `bots.delete`).
- **Dampak bisnis:** Pemisahan peran (least privilege) runtuh; admin efektif = owner; bisa ubah billing & hapus bot.
- **Skenario (aman):** User ber-role admin memanggil `/rbac/assign` untuk menaikkan dirinya menjadi owner → `/org/plan` & delete-bot terbuka.
- **Cara memperbaiki:** Larang meng-assign role dengan privilege ≥ role aktor; khususkan pembuatan `owner` hanya oleh `owner`; tambah cek "tidak boleh grant permission yang aktor sendiri tak punya".
- **Checklist verifikasi:**
  - [ ] Admin gagal (403) saat assign `owner`.
  - [ ] Hanya owner yang bisa membuat owner baru.
  - [ ] Uji: aktor tak bisa memberi permission yang tidak dimilikinya.

### H-04 — Local Agent menjalankan perintah server dengan `shell=True` (RCE-by-design)
- **Severity:** 🟠 High (perlu review otorisasi)
- **Lokasi:** `botnesia_local_agent.py:187-197`.
- **Masalah:** Local Agent (berjalan di mesin user, opt-in) mengeksekusi `command` dari server pakai `subprocess.run(command, shell=True, …)`. Gate hanya heuristik `is_dangerous()` (blocklist) + approval untuk yang "berbahaya"; perintah "aman" jalan otomatis. Blocklist mudah di-bypass (obfuscation, chaining), dan `shell=True` memperluas permukaan injeksi.
- **Dampak bisnis:** Jika kanal command/otorisasi per-user lemah (atau server dikompromi), attacker dapat RCE pada komputer pelanggan.
- **Skenario (aman):** Perintah yang tidak match blocklist namun berefek samping (mis. exfil via util standar) lolos tanpa approval.
- **Cara memperbaiki:** Allowlist perintah + argumen, hilangkan `shell=True` (pakai list argv), autentikasi kuat per-koneksi Local Agent, default deny + approval untuk semua write, dan tampilkan perintah persis ke user.
- **Checklist verifikasi:**
  - [ ] Perintah di luar allowlist ditolak.
  - [ ] Tidak ada `shell=True` pada jalur command.
  - [ ] Koneksi agent terikat token per-user yang bisa dicabut.

### M-01 — Error internal bocor ke response
- **Severity:** 🟡 Medium · **Lokasi:** `main.py:1681-1684` (register), `:1744-1748` (login).
- **Masalah:** `raise HTTPException(500, detail=f"Login gagal: {e}")` mengirim pesan exception mentah (bisa memuat detail DB/skema) ke klien.
- **Dampak:** Information disclosure yang mempermudah serangan lanjutan.
- **Perbaikan:** Kembalikan pesan generik; log `e` lengkap di server (`logger.exception`).
- **Checklist:** [ ] Error 500 tak lagi memuat detail internal · [ ] Detail tetap ada di log server.

### M-02 — `GET /media/{path}` publik tanpa otorisasi tenant
- **Severity:** 🟡 Medium · **Lokasi:** `main.py:2957-2962`.
- **Masalah:** Path-traversal sudah dicegah (`resolve()`+`startswith`), tapi endpoint **tanpa auth dan tanpa cek pemilik**. Siapa pun yang tahu/mengira path (UUID) bisa unduh media milik tenant lain.
- **Dampak:** Kebocoran dokumen/gambar lintas-tenant (obscurity ≠ security).
- **Perbaikan:** Wajibkan auth + verifikasi file milik `org_id` pemanggil (mapping file→org di DB), atau pakai signed URL berumur pendek.
- **Checklist:** [ ] Akses media tanpa token → 401 · [ ] Token org lain → 404/403 · [ ] Signed URL kedaluwarsa.

### M-03 — CORS `*` default
- **Severity:** 🟡 Medium · **Lokasi:** `main.py:205,380-387`.
- **Masalah:** `cors_allowed_origins` default `"*"`, `allow_methods=["*"]`, `allow_headers=["*"]`. Saat ini auth via Bearer header (bukan cookie) sehingga bukan CSRF klasik, tapi terlalu permisif dan berbahaya bila kelak pindah ke cookie/kredensial.
- **Perbaikan:** Set origin produksi eksplisit; jangan `*`. Pastikan `allow_credentials` tetap `False` selama pakai Bearer.
- **Checklist:** [ ] Origin tak dikenal ditolak preflight · [ ] Daftar origin dari env.

### M-04 — Tidak ada security headers
- **Severity:** 🟡 Medium · **Lokasi:** `main.py` (dashboard di-serve dari origin yang sama).
- **Masalah:** Tak ada `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`/`frame-ancestors`, `X-Content-Type-Options`.
- **Dampak:** Clickjacking dashboard, hilangnya lapisan pertahanan tambahan terhadap XSS/MIME-sniffing.
- **Perbaikan:** Tambah middleware header (CSP ketat untuk `/dashboard`, HSTS, `X-Frame-Options: DENY`, `nosniff`).
- **Checklist:** [ ] Header muncul di response · [ ] Dashboard tak bisa di-`<iframe>` lintas-origin.

### M-05 — Dependency ber-CVE (`python-jose`, `python-multipart`)
- **Severity:** 🟡 Medium · **Lokasi:** `requirements.txt:5,10`.
- **Masalah:** `python-jose==3.3.0` (isu algorithm-confusion & DoS pada dekode JWE/JWT) dan `python-multipart==0.0.9` (DoS parsing multipart, diperbaiki di 0.0.18). Keduanya di jalur auth & upload.
- **Perbaikan:** Upgrade `python-jose>=3.4.0`, `python-multipart>=0.0.18`; jalankan `pip-audit` di CI. *(Catatan: `pip-audit` tidak bisa membuat venv di lingkungan audit — `python3.12-venv` belum terpasang; verifikasi ulang di CI.)*
- **Checklist:** [ ] Versi ter-upgrade · [ ] `pip-audit` bersih di CI.

### M-06 — JWT web di `localStorage`
- **Severity:** 🟡 Medium · **Lokasi:** `frontend/api-client.js:71-73`.
- **Masalah:** Token disimpan di `localStorage` → dapat dibaca JS mana pun; setiap XSS = pencurian token. (XSS markdown sudah dimitigasi baik, tapi ini menghapus safety-net.)
- **Perbaikan:** Cookie `httpOnly`+`Secure`+`SameSite=Strict` untuk sesi, atau simpan token di memory + refresh token httpOnly.
- **Checklist:** [ ] Token tak terekspos ke `document`/JS · [ ] Logout mencabut sesi server-side.

### M-07 — Tidak ada RLS/DB-level tenant isolation (arsitektur)
- **Severity:** 🟡 Medium · **Lokasi:** seluruh data layer (asyncpg + single DB role).
- **Masalah:** Isolasi tenant hanya via `WHERE org_id=$1` di aplikasi. Tidak ada Postgres RLS. Review menemukan filter konsisten di `main.py`, **tetapi** tidak ada jaring pengaman: satu endpoint baru yang lupa filter langsung membocorkan data lintas-tenant.
- **Perbaikan:** Aktifkan RLS Postgres (policy `org_id = current_setting('app.org_id')`), set `SET LOCAL app.org_id` per-request, sebagai defense-in-depth. Tambah test lintas-tenant otomatis.
- **Checklist:** [ ] RLS aktif di tabel sensitif · [ ] Test: user org A tak bisa baca data org B walau query salah.

### L-01 — Enumerasi user/email
- **Severity:** 🔵 Low · **Lokasi:** `main.py:1651-1652` (register "Email sudah terdaftar"), `:1719-1731` (login lewati hashing saat user tak ada → timing oracle).
- **Perbaikan:** Pesan seragam untuk register/login; lakukan dummy `verify_password` saat user tak ditemukan agar waktu respons konstan.
- **Checklist:** [ ] Respons/timing register & login tak membedakan email ada/tidak.

### L-02 — Swagger `/docs` publik
- **Severity:** 🔵 Low · **Lokasi:** `main.py:377`.
- **Perbaikan:** `docs_url=None` di produksi atau lindungi dgn auth.
- **Checklist:** [ ] `/docs` & `/openapi.json` tak dapat diakses anonim di prod.

### L-03 — Cek path pakai `startswith` tanpa separator
- **Severity:** 🔵 Low · **Lokasi:** `main.py:2960` (`serve_media`), `:458-460` (`frontend_asset`).
- **Masalah:** `str(p).startswith(str(_MEDIA_DIR))` bisa lolos untuk sibling berprefix sama (mis. `/app/media` vs `/app/media-secret`).
- **Perbaikan:** Gunakan `p.is_relative_to(_MEDIA_DIR)` (Py3.9+).
- **Checklist:** [ ] Uji path sibling berprefix → 404.

### L-04 — Satu secret untuk sign & enkripsi
- **Severity:** 🔵 Low · **Lokasi:** `main.py:1528` (JWT) & `:816,904,1904…` (enkripsi integrasi).
- **Perbaikan:** Pisahkan `JWT_SECRET` dan `INTEGRATION_ENCRYPTION_KEY`.
- **Checklist:** [ ] Dua key berbeda di config · [ ] Rotasi salah satu tak memengaruhi yang lain.

### L-05 — SSRF residual: DNS-rebinding TOCTOU
- **Severity:** 🔵 Low · **Lokasi:** `tool_registry.py:362` (`_validate_url`), `main.py:5506` (`_fetch_website_text`).
- **Masalah:** Validasi host publik dilakukan sebelum connect; DNS bisa berubah antara validasi & fetch (sudah didokumentasikan di kode).
- **Perbaikan:** Resolve DNS → pilih IP → validasi IP → connect ke IP itu (pin), tolak private ranges pada IP final.
- **Checklist:** [ ] Fetch memakai IP tervalidasi, bukan re-resolve.

### L-06 — `npm audit`: 12 moderate (Expo transitive)
- **Severity:** 🔵 Low · **Lokasi:** `mobile/package-lock.json` (`@expo/config`, `expo-constants`, `expo-asset`, `expo-linking`).
- **Perbaikan:** `npm audit fix`; pantau rilis Expo SDK.
- **Checklist:** [ ] `npm audit` moderate = 0 atau ter-triage.

### I-01 — Audit metadata via f-string JSON
- **Severity:** ⚪ Info · **Lokasi:** `bn_platform/rbac.py:429,447`.
- **Masalah:** `f'{{"granted_role": "{body.role_key}"}}'` — injeksi tercegah karena `role_key` divalidasi sebelum insert, tapi rapuh.
- **Perbaikan:** Pakai `json.dumps({...})`.

### I-02 — Dependency di-vendor di luar `requirements.txt`
- **Severity:** ⚪ Info · **Lokasi:** `vendor/`, `.tts_vendor/`.
- **Masalah:** Salinan lib (httpx, openai, aiohttp, requests, dll.) di-vendor; tidak terpantau `pip-audit`/patch otomatis.
- **Perbaikan:** Pin & catat versi vendored, jadwalkan audit manual, atau kembali ke pip-managed dengan lockfile.

---

## 10 Celah Paling Berbahaya (urut prioritas perbaikan)

1. **C-01** — Default `SECRET_KEY` tanpa guard → forge JWT / takeover total. *(Perbaiki paling awal.)*
2. **H-03** — Admin bisa self-assign `owner` (eskalasi privilege).
3. **H-01** — `PATCH /org/plan` upgrade plan tanpa bayar (revenue bypass).
4. **H-02** — Bypass rate limit chat publik → financial DoS / kuras kuota.
5. **H-04** — Local Agent `shell=True` + gate heuristik → RCE-by-design.
6. **M-02** — `GET /media/{path}` publik tanpa cek tenant (kebocoran file).
7. **M-07** — Tak ada RLS: satu query lupa `org_id` = bocor lintas-tenant.
8. **M-05** — `python-jose`/`python-multipart` ber-CVE di jalur auth/upload.
9. **M-01** — Kebocoran error internal ke klien.
10. **M-03 / M-04** — CORS `*` + tanpa security headers (hardening deployment).

---

## Checklist Fix Bertahap

### 🔴 Fix hari ini (blocker keamanan)
- [ ] **C-01** Guard startup `SECRET_KEY` (tolak default/kosong/<32 char) + set secret acak kuat di produksi.
- [ ] **H-03** Larang assign role `owner`/role ≥ aktor via `/rbac/assign`.
- [ ] **H-01** Kunci/hapus `PATCH /org/plan`; plan hanya via webhook terverifikasi.
- [ ] **M-01** Ganti `detail=f"...{e}"` jadi pesan generik + log server.

### 🟠 Fix minggu ini
- [ ] **H-02** Rate limit chat berbasis IP+bot (server-side), abaikan `userId` klien untuk limit.
- [ ] **M-02** Auth + cek kepemilikan pada `GET /media/{path}` (atau signed URL).
- [ ] **M-05** Upgrade `python-jose`, `python-multipart`; tambah `pip-audit` di CI.
- [ ] **M-03/M-04** Set CORS origin eksplisit + middleware security headers (CSP/HSTS/X-Frame-Options/nosniff).
- [ ] **L-01/L-02** Seragamkan pesan auth (anti-enumerasi); matikan `/docs` di prod.

### 🟢 Fix sebelum production
- [ ] **H-04** Hardening Local Agent (allowlist, hapus `shell=True`, auth per-user).
- [ ] **M-06** Pindahkan sesi web ke cookie httpOnly / memory + refresh.
- [ ] **L-03** Ganti cek path ke `Path.is_relative_to()`.
- [ ] **L-04** Pisahkan key JWT vs enkripsi integrasi.
- [ ] **L-06** `npm audit fix` pada mobile.
- [ ] Tambah **test isolasi lintas-tenant** otomatis (user org A vs data org B) di suite CI.

### 🔵 Fix setelah scale besar
- [ ] **M-07** Aktifkan Postgres RLS per-tenant sebagai defense-in-depth.
- [ ] **L-05** Mitigasi DNS-rebinding (pin IP tervalidasi) pada URL ingestion.
- [ ] **I-02** Audit & pin dependency vendored (`vendor/`, `.tts_vendor/`) atau kembalikan ke pip-managed.
- [ ] **I-01** Rapikan pembuatan JSON audit (`json.dumps`).
- [ ] Rotasi rutin `SECRET_KEY`/API key + secret scanning di CI (pre-commit).

---

## Catatan Positif (kontrol yang sudah benar — jangan diubah)
- Isolasi tenant konsisten `WHERE org_id=$1` di seluruh endpoint `main.py` (bots, conversations, messages, sources, knowledge).
- Webhook Meta & Midtrans: signature HMAC/SHA512 fail-closed + `hmac.compare_digest` + idempotency (`payment_history` unique).
- SSRF-guard `_validate_url` (tolak loopback/private/link-local/metadata) + re-validasi redirect.
- XSS markdown: `mdInline` meng-`esc()` sebelum transform; link dibatasi `http(s)://`; user message pakai `esc()`.
- AI tool DB query (`_exec_database_query`) pakai allowlist tabel/kolom + parameterized value + scope `org_id`.
- Password: `pbkdf2_sha256` (passlib); sesi punya revoke via `sid` + tabel `sessions`.
- Token mobile di `expo-secure-store` (keychain), bukan storage biasa.
- `.env` ter-`gitignore`; tidak ditemukan API key hard-coded di file yang di-track git.
