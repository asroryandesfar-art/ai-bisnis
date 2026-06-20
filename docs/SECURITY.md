# BotNesia — Desain Keamanan

> Semua klaim di dokumen ini diverifikasi langsung terhadap source code
> (bukan ditebak) — lihat anotasi file:baris di setiap bagian.

## 1. Autentikasi

- **JWT** (`main.py`, `jwt.encode(payload, cfg.secret_key, algorithm="HS256")`,
  `main.py:1430`) — dipakai untuk semua sesi web/app. `exp` claim wajib.
- **API Key** (tabel `api_keys`) — untuk integrasi backend-ke-backend, dengan
  `scopes` (array), `expires_at`, `rotated_at`, `usage_count`. Disimpan
  sebagai hash, dicocokkan saat request (bukan disimpan plaintext utuh).
- Kedua mekanisme menghasilkan `user`/`org_id` context yang sama, sehingga
  semua endpoint downstream (RBAC, rate limit, audit log) tidak perlu tahu
  metode auth mana yang dipakai.

## 2. RBAC (Role-Based Access Control)

- 5 role sistem (immutable, `org_id IS NULL`): **owner, admin, manager,
  agent, viewer** (`bn_platform/rbac.py`).
- Permission granular per domain disimpan di tabel `permissions`, dipetakan
  ke role lewat `role_permissions`. Setiap fase AI Workforce menambah
  permission baru dengan pola `<domain>.read` / `<domain>.write` /
  `<domain>.approve`.
- **Gradien konservatisme yang disengaja** (bukan asal sama untuk semua
  domain):

  | Domain | manager | viewer | Alasan |
  |---|---|---|---|
  | finance/marketing/hr/operations | read+write | read | Operasional harian, risiko rendah per-aksi |
  | security | owner/admin saja | owner/admin saja | Sama konservatif dengan `audit.read`/`apikeys.manage` yang sudah ada |
  | executive | owner/admin saja | owner/admin saja | Menyentuh data Finance+HR+Security sekaligus — paling sensitif |
  | workforce (orkestrasi) | read+write | — | Koordinasi task lintas-agent adalah kerja level manager |
  | learning (Self-Learning) | read+write | read | Scan hanya membuat insight 'candidate' (inert); **`learning.approve` tetap owner/admin-only** karena approve mengubah jawaban bot ke SEMUA pelanggan |

- Enforcement: setiap route dependency-inject `Depends(require_permission("x.y"))`
  — tidak ada endpoint AI Workforce yang melewati pengecekan ini (diverifikasi
  per-router lewat test `test_router_gates_every_route_with_*_permission`,
  satu per modul).
- Migrasi role lama → RBAC dilakukan **lazy** (saat user pertama login
  setelah upgrade), bukan migrasi data massal — lihat
  [`bn_platform/ARCHITECTURE.md`](../bn_platform/ARCHITECTURE.md) §0.

## 3. Isolasi multi-tenant (`org_id` scoping)

- Setiap tabel tenant punya kolom `org_id`; **setiap query** di seluruh
  codebase memfilter `WHERE org_id = $1` secara eksplisit (tidak ada Row
  Level Security Postgres — isolasi ditegakkan di level aplikasi/query).
- `org_id` diturunkan dari JWT/API key yang sudah diverifikasi, tidak pernah
  dari input klien (request body/query param) untuk operasi tulis.
- Phase 5 (Security Agent) menambahkan `check_tenant_isolation()` yang
  secara aktif men-scan 3 invariant cross-table (human_queue↔conversations,
  workflow_executions↔workflows, sessions↔users) untuk mendeteksi kebocoran
  isolasi — hasil scan masuk ke `ops_alerts` dengan `source='security'`.

## 4. Human-approval gate — mekanisme keamanan inti AI Workforce

Pola yang diterapkan konsisten di Phase 7 (Workforce Orchestration) dan
Phase 8 (Self Learning Company), dan menjadi **satu-satunya** jalan bagi
keputusan AI Workforce mempengaruhi sesuatu yang berdampak nyata:

- `workforce_tasks.requires_approval` — task dengan flag ini **tidak bisa**
  ditransisikan ke status `completed` tanpa `approved_by`/`approved_at`
  terisi (`update_task_status()` melempar `ValueError` jika dilanggar).
- `organizational_memory.status` — insight hasil scan otomatis selalu mulai
  sebagai `candidate`. Hanya baris dengan `status='approved'` yang
  diambil oleh `build_organizational_learning_context()` — fungsi inilah
  satu-satunya titik di mana AI Workforce menyentuh pipeline chat
  pelanggan (`main.py chat()`), dan ia **read-only, tanpa LLM call**.
- Permission `*.approve` selalu dipisah dari `*.write` dan dibatasi
  owner/admin — lihat tabel gradien di §2.
- Implikasi: AI tidak pernah mengubah perilaku sistem terhadap pelanggan
  tanpa keputusan manusia yang tercatat (`approved_by` = user id nyata,
  bukan `NULL`/system).

## 5. Audit log

- Tabel `audit_logs` (`bn_platform/schema_platform.sql`): `actor_user_id`,
  `actor_email`, `action`, `resource_type`, `resource_id`, `ip_address`,
  `metadata` JSONB, `created_at`. Index per `org_id`+`actor`+`action`+`resource`.
  `org_id IS NULL` dipakai untuk aksi level-platform (security scan otomatis).
- Setiap endpoint AI Workforce yang melakukan mutasi (approve, scan,
  status update) memanggil `write_audit_log(...)` — bisa diverifikasi lewat
  `GET /api/security/audit-logs`.

## 6. Rate limiting

- In-memory sliding window per `org_id` (atau per `<scope>:<org_id>` untuk
  endpoint yang lebih sensitif), via `_check_rate_limit()` di
  `bn_platform/security.py`.
- Endpoint scan AI Workforce dibatasi ketat: 5 request/menit per org untuk
  `operations/scan`, `executive/reports/generate`, `improvement/scan`,
  `learning/scan`, dst — mencegah biaya LLM membludak dari spam klik.
- Endpoint billing dibatasi via `_BILLING_MAX_REQUESTS` (lihat `bn_platform/billing.py`).

## 7. Enkripsi kredensial channel

- Token channel (WhatsApp/Telegram/Instagram/Facebook) dienkripsi simetris
  pakai **Fernet** (AES-128-CBC + HMAC), kunci dari `CHANNEL_ENCRYPTION_KEY`
  di `.env` (`bn_platform/security.py:4-6`, `bn_platform/config.py:44-45`).
- Meta OAuth (`bn_platform/meta_oauth.py:290`) menolak start flow jika
  `CHANNEL_ENCRYPTION_KEY` belum dikonfigurasi — fail-closed, bukan fallback
  diam-diam ke plaintext untuk channel ini.
- Webhook Meta diverifikasi signature HMAC-SHA256 sebelum diproses.

## 8. Gotcha keamanan yang sudah pernah ditemukan & diperbaiki (referensi historis)

- Race antar dua scan SQL pattern yang ambigu di test (`FakePool` substring
  collision) pernah membuat hasil scan security ketukar dengan hasil query
  lain — bukan bug produksi, tapi pengingat untuk selalu memakai pattern SQL
  yang spesifik & tidak ambigu di test maupun query nyata.
- `UUID` dari asyncpg adalah objek `uuid.UUID`, bukan `str` — perbandingan
  `id in list_of_str` pernah gagal diam-diam (tanpa exception) di
  `workforce.py` sebelum dirilis; selalu normalisasi `str(id)` di kedua sisi.
